"""Calculs purs du dashboard : indices, position de la barre, périodes, tranches, séries.

Aucune entrée-sortie, aucune dépendance à ClickHouse, à Flask ni au HTML. Les formules sont
justifiées dans `DESIGN.md` (formule de la barre d'opinion) et `AGENTS.md`. Les lignes reçues portent la clé de tranche
(début de tranche, UTC) calculée par ClickHouse (JSON `tableau` du contrat) ; le fuseau de référence est
`Europe/Paris`.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

FENETRE_MIN = 5  # largeur d'une fenêtre Spark (contrat du job)
Z95 = 1.96
STANCES = ("pour", "contre", "neutre", "mention", "ambigu", "non_evalue")
EMOTIONS = ("joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre")
EMOTION_NON_DETECTEE = "non_evalue"  # pipeline : aucune émotion détectée, comptée à part en v2 (emotions_non_evaluees)


# --- indices élémentaires --------------------------------------------------------------------
def indice_net(pour: int, contre: int) -> float | None:
    """(pour − contre) / (pour + contre), entre −1 et +1 ; `None` sans post évalué."""
    total = pour + contre
    return (pour - contre) / total if total > 0 else None


def couverture(evalues: int, cites: int) -> float | None:
    """Part des posts cités que le scoreur a évalués (pour ou contre) ; `None` sans post cité."""
    return evalues / cites if cites > 0 else None


@dataclass(frozen=True, slots=True)
class Comptes:
    """Décompte des posts d'une entité par stance, sur la période."""

    pour: int = 0
    contre: int = 0
    neutre: int = 0
    mention: int = 0
    ambigu: int = 0
    non_evalue: int = 0

    @property
    def cites(self) -> int:
        return self.pour + self.contre + self.neutre + self.mention + self.ambigu + self.non_evalue

    @property
    def evalues(self) -> int:
        """Posts évalués : stance « pour » ou « contre » (les posts décisifs)."""
        return self.pour + self.contre

    @property
    def indice(self) -> float | None:
        return indice_net(self.pour, self.contre)

    @property
    def couverture(self) -> float | None:
        return couverture(self.evalues, self.cites)


def agreger_cibles(lignes: Iterable[tuple[datetime, str, str, int]]) -> dict[str, Comptes]:
    """Somme les lignes `(tranche, entité, stance, nb)` par entité. Une stance inconnue compte comme non évaluée.

    La clé de tranche n'intervient pas : les lignes sont déjà filtrées sur la période.
    """
    brut: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(STANCES, 0))
    for _, entite, stance, nb in lignes:
        brut[entite][stance if stance in STANCES else "non_evalue"] += int(nb)
    return {e: Comptes(**c) for e, c in brut.items()}


# --- camps et position de la barre ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ResultatCamp:
    camp: str
    pour: int = 0
    contre: int = 0
    candidats: tuple[str, ...] = ()  # candidats du camp cités au moins une fois

    @property
    def evalues(self) -> int:
        """Évaluations du camp : somme sur ses candidats (un post qui en juge deux compte deux fois)."""
        return self.pour + self.contre

    @property
    def indice(self) -> float | None:
        return indice_net(self.pour, self.contre)


def resultats_par_camp(
    comptes: Mapping[str, Comptes], camp_de: Mapping[str, str], camps: Sequence[str] = ("gauche", "centre", "droite")
) -> dict[str, ResultatCamp]:
    """Agrège les comptes des candidats par camp. `camp_de` ne contient que des candidats classés."""
    pour: dict[str, int] = dict.fromkeys(camps, 0)
    contre: dict[str, int] = dict.fromkeys(camps, 0)
    membres: dict[str, list[str]] = {c: [] for c in camps}
    for entite, c in comptes.items():
        camp = camp_de.get(entite)
        if camp in pour:
            pour[camp] += c.pour
            contre[camp] += c.contre
            membres[camp].append(entite)
    return {c: ResultatCamp(c, pour[c], contre[c], tuple(sorted(membres[c]))) for c in camps}


def marge_position(gauche: ResultatCamp, droite: ResultatCamp) -> float:
    """Demi-largeur de l'intervalle à 95 % de la position (approximation indicative).

    Pour chaque camp, π = (P + 1) / (E + 2) et var(N) = 4π(1 − π) / (E + 2) : l'ajout d'un
    pseudo-post de chaque stance évite une variance nulle quand tous les avis concordent.
    Les posts sont supposés indépendants, ce qui sous-estime l'incertitude (reprises, fils).
    """

    def variance(r: ResultatCamp) -> float:
        e = r.evalues
        pi = (r.pour + 1) / (e + 2)
        return 4 * pi * (1 - pi) / (e + 2)

    return Z95 * 0.5 * math.sqrt(variance(gauche) + variance(droite))


@dataclass(frozen=True, slots=True)
class Position:
    """Position de la barre d'opinion et ses entrées.

    `etat` : `ok` (position calculée), `insuffisant` (sous le seuil), `aucun_camp` (le lexique ne
    rattache aucun candidat à la gauche ou à la droite).
    """

    etat: str
    seuil: int
    gauche: ResultatCamp
    centre: ResultatCamp
    droite: ResultatCamp
    valeur: float | None = None
    bas: float | None = None
    haut: float | None = None
    manquants: Mapping[str, int] = field(default_factory=dict)  # camp -> évaluations qui manquent


def position_barre(par_camp: Mapping[str, ResultatCamp], seuil: int, camps_renseignes: Iterable[str]) -> Position:
    """Position p = (N_droite − N_gauche) / 2, affichée si chaque côté atteint le seuil.

    Le centre est reporté mais n'entre pas dans p. `camps_renseignes` liste les camps qui ont au
    moins un candidat rattaché dans le lexique : sans la gauche ou la droite, la barre n'a pas de sens.
    """
    seuil = max(1, int(seuil))
    g, c, d = par_camp["gauche"], par_camp["centre"], par_camp["droite"]
    renseignes = set(camps_renseignes)
    if "gauche" not in renseignes or "droite" not in renseignes:
        return Position("aucun_camp", seuil, g, c, d)
    manquants = {camp.camp: seuil - camp.evalues for camp in (g, d) if camp.evalues < seuil}
    if manquants:
        return Position("insuffisant", seuil, g, c, d, manquants=manquants)
    p = (d.indice - g.indice) / 2  # type: ignore[operator]  (evalues >= seuil >= 1 : indices définis)
    m = marge_position(g, d)
    return Position("ok", seuil, g, c, d, valeur=p, bas=max(-1.0, p - m), haut=min(1.0, p + m))


# --- classement des entités -------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LigneClassement:
    entite: str
    comptes: Comptes
    rang: int | None  # None : trop peu de posts évalués pour un classement


def classer(comptes: Mapping[str, Comptes], seuil: int, ids: Iterable[str] | None = None) -> list[LigneClassement]:
    """Classe les entités par indice net décroissant ; sous le seuil, pas de rang ni d'indice affiché.

    Les entités classées viennent d'abord (égalité : plus de posts évalués, puis ordre alphabétique),
    puis les autres par nombre de posts cités décroissant.
    """
    seuil = max(1, int(seuil))
    retenues = [e for e in comptes if ids is None or e in set(ids)]
    classees = sorted(
        (e for e in retenues if comptes[e].evalues >= seuil),
        key=lambda e: (-(comptes[e].indice or 0.0), -comptes[e].evalues, e),
    )
    autres = sorted((e for e in retenues if comptes[e].evalues < seuil), key=lambda e: (-comptes[e].cites, e))
    return [LigneClassement(e, comptes[e], i + 1) for i, e in enumerate(classees)] + [
        LigneClassement(e, comptes[e], None) for e in autres
    ]


# --- périodes et tranches (heure de Paris) ----------------------------------------------------
# Contrat du JSON `tableau` : périodes nommées, plage de dates (`perso`), tranches alignées sur Paris.
FUSEAU = ZoneInfo("Europe/Paris")
PERIODES = ("24h", "7j", "30j", "tout")
PERIODE_PERSO = "perso"
DUREE_NOMMEE = {"24h": timedelta(hours=24), "7j": timedelta(days=7), "30j": timedelta(days=30)}
PAS_NOMME = {"24h": 60, "7j": 360, "30j": 1440}
PAS_TOUT_MAX_JOURS = 180  # `tout` : pas de 1440 min jusqu'à 180 jours, 10080 au-delà
PLAGE_JOURS_PAS = ((2, 60), (14, 360), (180, 1440))  # `perso` : jours inclus -> pas ; au-delà, 10080
PLAGE_JOURS_MAX = 1095  # trois ans : au-delà, la plage est refusée


class PeriodeInvalide(ValueError):
    """Période ou plage refusée (code inconnu, plage inversée, dans le futur, trop longue). L'API répond 400."""


def vers_utc(t: datetime) -> datetime:
    """Instant en UTC. Un datetime sans fuseau est lu comme UTC (convention de clickhouse-connect)."""
    return t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _local(t: datetime) -> datetime:
    """Heure locale de Paris, sans fuseau (pour l'arithmétique en heure murale)."""
    return vers_utc(t).astimezone(FUSEAU).replace(tzinfo=None)


def instant_paris(naif: datetime) -> datetime:
    """Heure murale de Paris vers instant UTC. Réservé aux bornes de tranche (0 h, 6 h, 12 h, 18 h, minuit) : jamais ambiguës."""
    return naif.replace(tzinfo=FUSEAU).astimezone(timezone.utc)


def minuit_paris(jour: date) -> datetime:
    """Minuit du jour donné, heure de Paris, en UTC."""
    return instant_paris(datetime.combine(jour, time()))


def debut_tranche(t: datetime, pas: int) -> datetime:
    """Début de la tranche de `pas` minutes qui contient `t` (UTC).

    60 : heure pleine (les décalages de Paris sont des heures entières, l'heure UTC suffit).
    360 : 0 h, 6 h, 12 h, 18 h heure de Paris. 1440 : minuit. 10080 : lundi minuit.
    Les frontières de 360, 1440 et 10080 tombent hors des heures ambiguës du changement d'heure.
    """
    t = vers_utc(t)
    if pas == 60:
        return t.replace(minute=0, second=0, microsecond=0)
    local = _local(t)
    minuit = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if pas == 1440:
        return instant_paris(minuit)
    if pas == 10080:
        return instant_paris(minuit - timedelta(days=local.weekday()))
    if pas == 360:
        return instant_paris(local.replace(hour=local.hour - local.hour % 6, minute=0, second=0, microsecond=0))
    raise ValueError(f"pas non géré : {pas}")


def avancer(debut: datetime, pas: int, n: int) -> datetime:
    """Début de la tranche située `n` tranches après `debut` (avant si `n` < 0).

    `debut` doit être aligné. Pour 60 minutes, l'avance est absolue ; sinon elle se fait en heure
    murale de Paris : une tranche de 6 h dure 5 ou 7 h le jour du changement d'heure, une de 1 jour 23 ou 25 h.
    """
    if pas == 60:
        return vers_utc(debut) + timedelta(hours=n)
    return instant_paris(_local(debut) + timedelta(minutes=pas * n))


def fin_tranche(t: datetime, pas: int) -> datetime:
    """Fin de la tranche qui contient `t` (UTC) : début de la suivante."""
    return avancer(debut_tranche(t, pas), pas, 1)


def _ceil(t: datetime, pas: int) -> datetime:
    """Plus petite frontière de tranche qui ne précède pas `t`."""
    d = debut_tranche(t, pas)
    return vers_utc(t) if d == vers_utc(t) else avancer(d, pas, 1)


def tranches_entre(debut: datetime, fin: datetime, pas: int) -> tuple[datetime, ...]:
    """Débuts des tranches de `debut` (inclus) à `fin` (exclu). `debut` et `fin` doivent être alignés."""
    out: list[datetime] = []
    t = debut
    while t < fin:
        out.append(t)
        t = avancer(t, pas, 1)
    return tuple(out)


def pas_pour_jours(jours: int) -> int:
    """Pas d'une plage de `jours` jours (inclus) : 60 jusqu'à 2 jours, 360 jusqu'à 14, 1440 jusqu'à 180, 10080 au-delà."""
    for limite, pas in PLAGE_JOURS_PAS:
        if jours <= limite:
            return pas
    return 10080


@dataclass(frozen=True, slots=True)
class Bornes:
    """Bornes d'une période alignées sur les tranches.

    `debut` : début de la première tranche ; `fin` : fin de la dernière. `tranches` : débuts de
    chaque tranche. `precedente` : (debut, fin) de la période précédente de même nombre de tranches,
    ou `None` pour `tout`.
    """

    code: str
    debut: datetime
    fin: datetime
    pas_min: int
    tranches: tuple[datetime, ...]
    precedente: tuple[datetime, datetime] | None


def valider_periode(code: str, plage: tuple[date, date] | None, maintenant: datetime) -> None:
    """Refuse un code inconnu, une plage inversée, une fin future ou une plage de plus de 3 ans."""
    if code == PERIODE_PERSO:
        if plage is None:
            raise PeriodeInvalide("perso : debut et fin attendus (AAAA-MM-JJ)")
        d1, d2 = plage
        if d1 > d2:
            raise PeriodeInvalide("debut après fin")
        if d2 > _local(maintenant).date():
            raise PeriodeInvalide("fin dans le futur")
        if (d2 - d1).days + 1 > PLAGE_JOURS_MAX:
            raise PeriodeInvalide(f"plage trop longue : {PLAGE_JOURS_MAX} jours au plus")
    elif code not in PERIODES or plage is not None:
        raise PeriodeInvalide("periode : 24h, 7j, 30j ou tout (ou perso avec debut et fin)")


def bornes(code: str, maintenant: datetime, premiere: datetime | None, plage: tuple[date, date] | None = None) -> Bornes:
    """Bornes de la période `code` à l'instant `maintenant`.

    `premiere` : heure de la plus ancienne fenêtre en base (sert à `tout`). `plage` : dates de Paris,
    `fin` incluse, pour `perso` (les bornes s'élargissent à la tranche).
    """
    valider_periode(code, plage, maintenant)
    maintenant = vers_utc(maintenant)
    if code in DUREE_NOMMEE:
        pas = PAS_NOMME[code]
        fin = fin_tranche(maintenant, pas)
        debut = avancer(fin, pas, -round(DUREE_NOMMEE[code] / timedelta(minutes=pas)))
    elif code == "tout":
        if premiere is None:
            pas = 1440
            debut = debut_tranche(maintenant, pas)
        else:
            premiere = min(vers_utc(premiere), maintenant)
            pas = 1440 if maintenant - premiere <= timedelta(days=PAS_TOUT_MAX_JOURS) else 10080
            debut = debut_tranche(premiere, pas)
        fin = fin_tranche(maintenant, pas)
    else:
        d1, d2 = plage  # type: ignore[misc]  (valider_periode a exigé la plage)
        pas = pas_pour_jours((d2 - d1).days + 1)
        debut = debut_tranche(minuit_paris(d1), pas)
        fin = _ceil(minuit_paris(d2 + timedelta(days=1)), pas)
    liste = tranches_entre(debut, fin, pas)
    precedente = None if code == "tout" else (avancer(debut, pas, -len(liste)), debut)
    return Bornes(code, debut, fin, pas, liste, precedente)


def _index(t: datetime, tranches: Sequence[datetime], fin: datetime) -> int | None:
    """Indice de la tranche qui contient `t`, ou `None` hors de la période."""
    i = bisect_right(tranches, vers_utc(t)) - 1
    return i if i >= 0 and vers_utc(t) < fin else None


# --- séries -----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PointIndice:
    fin: datetime  # fin de la tranche (UTC)
    pour: int
    contre: int
    indice: float | None  # None tant que le cumul reste sous le seuil

    @property
    def evalues(self) -> int:
        return self.pour + self.contre


def serie_indice_cumulee(
    lignes: Iterable[tuple[datetime, str, str, int]],
    entite: str,
    tranches: Sequence[datetime],
    fin: datetime,
    seuil: int,
) -> list[PointIndice]:
    """Indice net cumulé depuis le début de la période, masqué sous le seuil de posts évalués.

    Le dernier point égale l'indice du classement pour la même période.
    """
    seuil = max(1, int(seuil))
    tranches = tuple(tranches)
    fins = tranches[1:] + (fin,)
    pour = [0] * len(tranches)
    contre = [0] * len(tranches)
    for t, e, stance, nb in lignes:
        if e != entite or stance not in ("pour", "contre"):
            continue
        i = _index(t, tranches, fin)
        if i is not None:
            (pour if stance == "pour" else contre)[i] += int(nb)
    points: list[PointIndice] = []
    cp = cc = 0
    for i, f in enumerate(fins):
        cp += pour[i]
        cc += contre[i]
        points.append(PointIndice(f, cp, cc, indice_net(cp, cc) if cp + cc >= seuil else None))
    return points


# --- baromètre : ton, émotions, thèmes --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Ton:
    positif: int = 0
    neutre: int = 0
    negatif: int = 0
    non_evalue: int = 0

    @property
    def evalues(self) -> int:
        return self.positif + self.neutre + self.negatif

    @property
    def total(self) -> int:
        return self.evalues + self.non_evalue

    @property
    def couverture(self) -> float | None:
        return couverture(self.evalues, self.total)


_TON = {"positif": "positif", "neutre": "neutre", "negatif": "negatif"}


def repartition_ton(lignes: Iterable[tuple[datetime, str, str, int]]) -> Ton:
    """Somme `posts_fenetre` par sentiment. Une valeur inconnue compte comme non évaluée."""
    c = dict.fromkeys(("positif", "neutre", "negatif", "non_evalue"), 0)
    for _, sentiment, _, nb in lignes:
        c[_TON.get(sentiment, "non_evalue")] += int(nb)
    return Ton(**c)


def repartition_emotions(lignes: Iterable[tuple[datetime, str, str, int]]) -> tuple[dict[str, int], int]:
    """(posts par émotion reconnue, posts sans émotion reconnue). Toutes les émotions du contrat sont présentes."""
    par = dict.fromkeys(EMOTIONS, 0)
    sans = 0
    for _, _, emotion, nb in lignes:
        if emotion in par:
            par[emotion] += int(nb)
        else:
            sans += int(nb)
    return par, sans


@dataclass(frozen=True, slots=True)
class TrancheTon:
    debut: datetime
    positif: int
    neutre: int
    negatif: int

    @property
    def total(self) -> int:
        return self.positif + self.neutre + self.negatif


def serie_ton(
    lignes: Iterable[tuple[datetime, str, str, int]], tranches: Sequence[datetime], fin: datetime
) -> list[TrancheTon]:
    tranches = tuple(tranches)
    cases = [dict.fromkeys(("positif", "neutre", "negatif"), 0) for _ in tranches]
    for t, sentiment, _, nb in lignes:
        i = _index(t, tranches, fin)
        if i is not None and sentiment in cases[i]:
            cases[i][sentiment] += int(nb)
    return [TrancheTon(d, **c) for d, c in zip(tranches, cases, strict=True)]


def classer_themes(lignes: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    """Thèmes par nombre de posts décroissant ; `autre` (résiduel) toujours en dernier."""
    somme: dict[str, int] = defaultdict(int)
    for theme, nb in lignes:
        somme[theme] += int(nb)
    ordre = sorted(((t, n) for t, n in somme.items() if t != "autre"), key=lambda x: (-x[1], x[0]))
    return ordre + ([("autre", somme["autre"])] if "autre" in somme else [])


# --- tuyau : volume, latence, fraîcheur -------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Pipeline:
    nb_posts: int = 0
    somme_latence_ms: int = 0
    derniere_maj: datetime | None = None

    @property
    def latence_moyenne_s(self) -> float | None:
        """Latence moyenne = somme des latences / nombre de posts (colonnes de `pipeline_fenetre`)."""
        return self.somme_latence_ms / self.nb_posts / 1000 if self.nb_posts > 0 else None


def resume_pipeline(lignes: Iterable[tuple[datetime, int, int, datetime | None]]) -> Pipeline:
    nb = lat = 0
    maj: datetime | None = None
    for _, n, somme, derniere in lignes:
        nb += int(n)
        lat += int(somme)
        if derniere is not None and (maj is None or derniere > maj):
            maj = derniere
    return Pipeline(nb, lat, maj)


def serie_volume(
    lignes: Iterable[tuple[datetime, int, int, datetime | None]], tranches: Sequence[datetime], fin: datetime
) -> list[int]:
    tranches = tuple(tranches)
    volume = [0] * len(tranches)
    for t, n, *_ in lignes:
        i = _index(t, tranches, fin)
        if i is not None:
            volume[i] += int(n)
    return volume


@dataclass(frozen=True, slots=True)
class Fraicheur:
    etat: str  # ok | warn | critical | unknown
    age_s: int | None


def etat_fraicheur(derniere_maj: datetime | None, maintenant: datetime, ok_min: int, alerte_min: int) -> Fraicheur:
    """`ok` sous `ok_min` minutes sans mise à jour, `warn` jusqu'à `alerte_min`, `critical` au-delà."""
    if derniere_maj is None:
        return Fraicheur("unknown", None)
    age = max(0, int((maintenant - derniere_maj).total_seconds()))
    if age <= ok_min * 60:
        return Fraicheur("ok", age)
    return Fraicheur("warn" if age <= alerte_min * 60 else "critical", age)


# --- croisements : thèmes et émotions par entité (JSON `tableau`, section `croisements`) ----------
@dataclass(frozen=True, slots=True)
class Croisements:
    """Thèmes et émotions par entité, pour un seul scoreur. `scoreur` vaut `None` sans ligne dans la fenêtre."""

    scoreur: str | None = None
    themes: tuple[tuple[str, str, int], ...] = ()  # (entité, thème, posts)
    emotions: tuple[tuple[str, str, int], ...] = ()  # (entité, émotion, occurrences)


def scoreur_recent(lignes: Iterable[tuple[str, datetime]]) -> str | None:
    """Scoreur de la fenêtre la plus récente de la période.

    `lignes` : (scoreur, `max(fenetre_debut)` de ce scoreur), une ligne par scoreur. Un scoreur vide
    ne compte pas. À égalité d'horodatage, l'ordre alphabétique départage. `None` sans ligne.
    """
    retenues = [(s, vers_utc(t)) for s, t in lignes if s]
    if not retenues:
        return None
    dernier = max(t for _, t in retenues)
    return min(s for s, t in retenues if t == dernier)


def totaux_par_entite(
    lignes: Iterable[tuple[str, str, int]], ordre: Sequence[str], exclues: frozenset[str] = frozenset()
) -> tuple[tuple[str, str, int], ...]:
    """Somme de `nb_posts` par (entité, thème ou émotion), à partir de sommes `(entité, valeur, nb)` déjà agrégées.

    Exclus : entité vide ou absente de `ordre` (candidats puis partis de la réponse), valeur vide ou
    listée dans `exclues`, total nul. Ordre : position de l'entité dans `ordre`, total décroissant, puis valeur.
    Une ligne de `croisements_fenetre` vaut une occurrence (post, cible, thème). Pour les thèmes, la somme
    donne des posts. Pour les émotions, un post qui porte k thèmes compte k fois : la somme donne des
    occurrences (contrat §5).
    """
    rang = {e: i for i, e in enumerate(ordre)}
    somme: dict[tuple[str, str], int] = defaultdict(int)
    for entite, valeur, nb in lignes:
        if entite and entite in rang and valeur and valeur not in exclues:
            somme[(entite, valeur)] += int(nb)
    return tuple(sorted(((e, v, n) for (e, v), n in somme.items() if n > 0), key=lambda x: (rang[x[0]], -x[2], x[1])))


# --- séries par camp et adjectifs (tableau v4) ------------------------------------------------
CAMPS = ("gauche", "centre", "droite")
STANCES_EVALUEES = ("pour", "contre")
ADJECTIFS_PAR_GROUPE = 8  # au plus 8 adjectifs servis par (entité, stance)
ADJECTIFS_MIN_POSTS = 3  # un adjectif vu dans moins de 3 posts pour une (entité, stance) n'est pas servi


def serie_camps(
    lignes: Iterable[tuple[datetime, str, str, int]],
    camp_de: Mapping[str, str],
    tranches: Sequence[datetime],
    fin: datetime,
) -> list[dict[str, dict[str, int]]]:
    """Évaluations `pour` et `contre` par tranche et par camp.

    Mêmes candidats que la barre d'opinion (`camp_de` : candidats rattachés à un camp) ; les partis et
    les candidats sans camp n'entrent pas. Une ligne de `cibles_fenetre` vaut une évaluation : un post
    qui juge deux candidats d'un même camp compte deux fois (comme `barre.camps`).
    """
    tranches = tuple(tranches)
    cases = [{c: {"pour": 0, "contre": 0} for c in CAMPS} for _ in tranches]
    for t, entite, stance, nb in lignes:
        camp = camp_de.get(entite)
        if camp not in CAMPS or stance not in STANCES_EVALUEES:
            continue
        i = _index(t, tranches, fin)
        if i is not None:
            cases[i][camp][stance] += int(nb)
    return cases


@dataclass(frozen=True, slots=True)
class Adjectifs:
    """Adjectifs par entité et par stance, pour un seul scoreur. `None` côté vue : table absente."""

    scoreur: str | None = None
    lignes: tuple[tuple[str, str, str, int], ...] = ()  # (entité, stance, adjectif, posts)
    debut: datetime | None = None  # début de la première fenêtre comptée ; None sans adjectif
    fin: datetime | None = None  # fin de la dernière fenêtre comptée
    posts_hors: int = 0  # posts scorés de la période hors de [debut, fin[ : sans adjectifs comptés


def couverture_adjectifs(
    premiere_derniere: tuple[datetime, datetime] | None,
) -> tuple[datetime | None, datetime | None]:
    """(début, fin) couverts par les adjectifs : début de la première fenêtre, fin de la dernière."""
    if premiere_derniere is None:
        return None, None
    premiere, derniere = premiere_derniere
    return vers_utc(premiere), vers_utc(derniere) + timedelta(minutes=FENETRE_MIN)


def adjectifs_par_entite(
    lignes: Iterable[tuple[str, str, str, int]],
    ordre: Sequence[str],
    n_max: int = ADJECTIFS_PAR_GROUPE,
    minimum: int = ADJECTIFS_MIN_POSTS,
) -> tuple[tuple[str, str, str, int], ...]:
    """Les `n_max` adjectifs les plus fréquents par (entité, stance), à partir de sommes déjà agrégées.

    `lignes` : (entité, stance, adjectif, posts). Exclus : entité absente de `ordre` (candidats puis
    partis de la réponse), stance autre que `pour` ou `contre`, adjectif vide, total sous `minimum`.
    Le minimum évite qu'un mot rare, donc proche d'un post précis, arrive à l'écran.
    Ordre : entité (position dans `ordre`), stance (`pour` puis `contre`), posts décroissants, adjectif.
    """
    rang = {e: i for i, e in enumerate(ordre)}
    somme: dict[tuple[str, str, str], int] = defaultdict(int)
    for entite, stance, adjectif, nb in lignes:
        if entite in rang and stance in STANCES_EVALUEES and adjectif:
            somme[(entite, stance, adjectif)] += int(nb)
    groupes: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for (entite, stance, adjectif), n in somme.items():
        if n >= minimum:
            groupes[(entite, stance)].append((adjectif, n))
    sortie = []
    for (entite, stance), mots in sorted(groupes.items(), key=lambda g: (rang[g[0][0]], STANCES_EVALUEES.index(g[0][1]))):
        for adjectif, n in sorted(mots, key=lambda m: (-m[1], m[0]))[:n_max]:
            sortie.append((entite, stance, adjectif, n))
    return tuple(sortie)


# --- catalogue d'événements (route /api/evenements) -------------------------------------------
CATEGORIES_EVENEMENT = ("manifestation", "loi", "prix", "bourse", "greve", "autre")
EVENEMENTS_MAX = 1000


def lien_sur(lien: str | None) -> str | None:
    """Lien `http` ou `https` seulement : un autre schéma (`javascript:`…) deviendrait un lien actif dans la page."""
    if not lien:
        return None
    lien = lien.strip()
    return lien if lien.lower().startswith(("https://", "http://")) else None
