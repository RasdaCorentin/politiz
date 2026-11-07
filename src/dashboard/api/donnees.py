"""Lecture de ClickHouse (compte `dashboard`, lecture seule) : agrégats par tranche (tables ClickHouse et JSON `tableau` du contrat).

Chaque requête agrège dans ClickHouse par tranche (`toStartOfInterval`, `toStartOfDay`, `toMonday`,
fuseau `Europe/Paris`) : jamais une ligne par fenêtre de 5 minutes sur la période. Les croisements
(`croisements_fenetre`) ne sont pas découpés par tranche : un total par entité sur la période, pour
un seul scoreur ; les adjectifs (`adjectifs_fenetre`) suivent la même règle. Les tables facultatives
(`adjectifs_fenetre`, `evenements`) sont cherchées dans `system.tables` : absentes, leur section vaut
`None` au lieu de faire échouer la lecture. Les lignes sont sommées (`sum(...) GROUP BY`) : les tables sont des incréments
fusionnés par ClickHouse. Aucune colonne de texte de post n'existe dans ces tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import clickhouse_connect

from calculs import CATEGORIES_EVENEMENT, EVENEMENTS_MAX, Bornes, instant_paris, lien_sur, minuit_paris, scoreur_recent, vers_utc
from config import Config


class ErreurBase(Exception):
    """ClickHouse injoignable, refus d'accès ou requête invalide. Le message ne contient aucun secret."""


@dataclass(frozen=True, slots=True)
class EtatBase:
    """Bornes de la base entière : première fenêtre écrite et dernier micro-lot."""

    premiere: datetime | None
    derniere_maj: datetime | None


@dataclass(frozen=True)
class Brut:
    """Lignes agrégées par tranche pour une période, plus la période précédente pour la barre."""

    bornes: Bornes
    etat: EtatBase
    cibles: list[tuple[datetime, str, str, int]]  # (tranche, entité, stance, nb) ; période courante
    cibles_precedentes: list[tuple[datetime, str, str, int]]  # même forme ; période précédente
    posts: list[tuple[datetime, str, str, int]]  # (tranche, sentiment, émotion, nb)
    themes: list[tuple[str, int]]  # (thème, nb) : totaux de la période
    pipeline: list[tuple[datetime, int, int, datetime | None]]  # (tranche, nb, somme latence ms, dernière maj)
    scoreur: str | None = None  # scoreur de la fenêtre la plus récente ; None sans ligne
    croisements_themes: list[tuple[str, str, int]] = field(default_factory=list)  # (entité, thème, occurrences)
    croisements_emotions: list[tuple[str, str, int]] = field(default_factory=list)  # (entité, émotion, occurrences)
    adjectifs: list[tuple[str, str, str, int]] | None = None  # (entité, stance, adjectif, posts) ; None : table absente
    scoreur_adjectifs: str | None = None  # scoreur retenu pour les adjectifs (tableau v4)
    couverture_adjectifs: tuple[datetime, datetime] | None = None  # première et dernière fenêtre comptées
    posts_hors_adjectifs: int = 0  # posts scorés de la période hors de cette couverture


@dataclass(frozen=True, slots=True)
class Evenement:
    """Un fait daté du catalogue (`evenements`) : titre et lien publics, aucune donnée de post."""

    id: str
    date: datetime
    titre: str
    categorie: str
    source: str
    lien: str | None


TABLES_FACULTATIVES = ("adjectifs_fenetre", "evenements")


def client(cfg: Config):
    try:
        return clickhouse_connect.get_client(
            host=cfg.clickhouse_host,
            port=cfg.clickhouse_port,
            username=cfg.clickhouse_user,
            password=cfg.clickhouse_password,
            database=cfg.clickhouse_db,
            connect_timeout=3,
            send_receive_timeout=10,
            autogenerate_session_id=False,  # un profil readonly refuse les changements de réglages
        )
    except Exception as exc:  # noqa: BLE001
        raise ErreurBase(f"connexion impossible ({type(exc).__name__})") from exc


def _expression_tranche(pas: int) -> str:
    """Expression SQL qui donne le début de tranche d'une fenêtre, heure de Paris (alignement des tranches, contrat du JSON `tableau`).

    ClickHouse aligne `INTERVAL n MINUTE` sur l'UTC, même avec un fuseau : pour 6 h, l'heure murale
    de Paris (décalage lu à l'instant de la fenêtre) est alignée, puis renvoyée comme heure murale
    (fuseau UTC). `_tranche` la reconvertit en instant. Les heures pleines (60) restent sûres.
    """
    if pas == 60:
        return "toStartOfInterval(fenetre_debut, INTERVAL 60 MINUTE, 'Europe/Paris')"
    if pas == 360:
        return (
            "toStartOfInterval(fenetre_debut + toIntervalSecond(timeZoneOffset(toDateTime(fenetre_debut, 'Europe/Paris'))), "
            "INTERVAL 360 MINUTE)"
        )
    if pas == 1440:
        return "toStartOfDay(fenetre_debut, 'Europe/Paris')"
    if pas == 10080:
        return "toMonday(fenetre_debut, 'Europe/Paris')"
    raise ValueError(f"pas non géré : {pas}")


def _tranche(valeur, pas: int) -> datetime:
    """Valeur de tranche renvoyée par ClickHouse vers un instant UTC.

    360 : heure murale de Paris (voir `_expression_tranche`). `toMonday` renvoie une date (minuit de Paris).
    """
    if pas == 360:
        return instant_paris(valeur.replace(tzinfo=None))
    if isinstance(valeur, datetime):
        return vers_utc(valeur)
    if isinstance(valeur, date):
        return minuit_paris(valeur)
    raise ValueError(f"tranche inattendue : {valeur!r}")


def _naif(t: datetime) -> datetime:
    """UTC sans fuseau : clickhouse-connect lie les datetime sans fuseau comme des UTC (colonnes UTC)."""
    return vers_utc(t).replace(tzinfo=None)


def _date_utc(valeur) -> datetime | None:
    """Date de la base en UTC ; `None` pour une table vide (ClickHouse renvoie l'époque)."""
    if valeur is None or valeur.year <= 1970:
        return None
    return vers_utc(valeur)


def etat_base(cfg: Config) -> EtatBase:
    """Première fenêtre et dernier micro-lot de toute la base (`pipeline_fenetre`)."""
    try:
        c = client(cfg)
        premiere, maj = c.query("SELECT min(fenetre_debut), max(derniere_maj) FROM pipeline_fenetre").result_rows[0]
    except ErreurBase:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurBase(f"lecture impossible ({type(exc).__name__})") from exc
    return EtatBase(premiere=_date_utc(premiere), derniere_maj=_date_utc(maj))


def _tables_presentes(c) -> set[str]:
    """Tables facultatives présentes dans la base courante (`system.tables`, lisible en lecture seule)."""
    lignes = c.query(
        "SELECT name FROM system.tables WHERE database = currentDatabase() AND name IN %(noms)s",
        parameters={"noms": TABLES_FACULTATIVES},
    ).result_rows
    return {n for (n,) in lignes}


def lire(cfg: Config, bornes: Bornes, etat: EtatBase) -> Brut:
    """Lit les tables agrégées par tranche sur la période, la période précédente pour la barre, et les croisements."""
    pas = bornes.pas_min
    tranche = _expression_tranche(pas)
    p = {"debut": _naif(bornes.debut), "fin": _naif(bornes.fin)}
    fenetre = "fenetre_debut >= %(debut)s AND fenetre_debut < %(fin)s"
    try:
        c = client(cfg)
        cibles = c.query(
            f"SELECT {tranche} AS tranche, entite, stance, sum(nb_posts) FROM cibles_fenetre "
            f"WHERE {fenetre} GROUP BY tranche, entite, stance",
            parameters=p,
        ).result_rows
        if bornes.precedente is not None:
            prec = {"debut": p["debut"], "prec": _naif(bornes.precedente[0])}
            cibles_prec = c.query(
                f"SELECT {tranche} AS tranche, entite, stance, sum(nb_posts) FROM cibles_fenetre "
                "WHERE fenetre_debut >= %(prec)s AND fenetre_debut < %(debut)s GROUP BY tranche, entite, stance",
                parameters=prec,
            ).result_rows
        else:
            cibles_prec = []
        posts = c.query(
            f"SELECT {tranche} AS tranche, sentiment, emotion, sum(nb_posts) FROM posts_fenetre "
            f"WHERE {fenetre} GROUP BY tranche, sentiment, emotion",
            parameters=p,
        ).result_rows
        themes = c.query(
            f"SELECT theme, sum(nb_posts) FROM themes_fenetre WHERE {fenetre} GROUP BY theme",
            parameters=p,
        ).result_rows
        pipeline = c.query(
            f"SELECT {tranche} AS tranche, sum(nb_posts), sum(somme_latence_ms), max(derniere_maj) "
            f"FROM pipeline_fenetre WHERE {fenetre} GROUP BY tranche",
            parameters=p,
        ).result_rows
        # Croisements : un seul scoreur par réponse (celui de la fenêtre la plus récente), sans mélange
        # avec un autre scoreur (rupture de série, contrat §5). Totaux sur la période, pas par tranche.
        scoreurs = c.query(
            "SELECT scoreur, max(fenetre_debut) FROM croisements_fenetre "
            f"WHERE {fenetre} AND scoreur != '' GROUP BY scoreur",
            parameters=p,
        ).result_rows
        scoreur = scoreur_recent((s, t) for s, t in scoreurs)
        themes_croises, emotions_croisees = [], []
        if scoreur is not None:
            p_scoreur = {**p, "scoreur": scoreur}
            themes_croises = c.query(
                "SELECT entite, theme, sum(nb_posts) FROM croisements_fenetre "
                f"WHERE {fenetre} AND scoreur = %(scoreur)s GROUP BY entite, theme",
                parameters=p_scoreur,
            ).result_rows
            emotions_croisees = c.query(
                "SELECT entite, emotion, sum(nb_posts) FROM croisements_fenetre "
                f"WHERE {fenetre} AND scoreur = %(scoreur)s GROUP BY entite, emotion",
                parameters=p_scoreur,
            ).result_rows
        # Adjectifs : table facultative (base créée avant elle) ; même règle d'un seul scoreur.
        # Couverture : première et dernière fenêtre comptées ; les posts scorés hors d'elle n'ont pas
        # d'adjectifs (job antérieur au comptage). Un trou entre les deux n'est pas détecté.
        adjectifs, scoreur_adj, couverture, hors = None, None, None, 0
        if "adjectifs_fenetre" in _tables_presentes(c):
            scoreurs_adj = c.query(
                "SELECT scoreur, max(fenetre_debut), min(fenetre_debut) FROM adjectifs_fenetre "
                f"WHERE {fenetre} AND scoreur != '' GROUP BY scoreur",
                parameters=p,
            ).result_rows
            scoreur_adj = scoreur_recent((s, t) for s, t, _ in scoreurs_adj)
            adjectifs = []
            if scoreur_adj is not None:
                _, fin_adj, debut_adj = next(l for l in scoreurs_adj if l[0] == scoreur_adj)
                couverture = (vers_utc(debut_adj), vers_utc(fin_adj))
                hors = c.query(
                    f"SELECT sum(nb_posts) FROM pipeline_fenetre WHERE {fenetre} "
                    "AND (fenetre_debut < %(adj_debut)s OR fenetre_debut > %(adj_fin)s)",
                    parameters={**p, "adj_debut": _naif(debut_adj), "adj_fin": _naif(fin_adj)},
                ).result_rows[0][0]
                adjectifs = c.query(
                    "SELECT entite, stance, adjectif, sum(nb_posts) FROM adjectifs_fenetre "
                    f"WHERE {fenetre} AND scoreur = %(scoreur)s AND stance IN ('pour', 'contre') "
                    "GROUP BY entite, stance, adjectif",
                    parameters={**p, "scoreur": scoreur_adj},
                ).result_rows
    except ErreurBase:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurBase(f"lecture impossible ({type(exc).__name__})") from exc
    return Brut(
        bornes=bornes,
        etat=etat,
        cibles=[(_tranche(t, pas), e, s, int(n)) for t, e, s, n in cibles],
        cibles_precedentes=[(_tranche(t, pas), e, s, int(n)) for t, e, s, n in cibles_prec],
        posts=[(_tranche(t, pas), s, em, int(n)) for t, s, em, n in posts],
        themes=[(t, int(n)) for t, n in themes],
        pipeline=[(_tranche(t, pas), int(n), int(lat), _date_utc(d)) for t, n, lat, d in pipeline],
        scoreur=scoreur,
        croisements_themes=[(e, t, int(n)) for e, t, n in themes_croises],
        croisements_emotions=[(e, m, int(n)) for e, m, n in emotions_croisees],
        adjectifs=None if adjectifs is None else [(e, st, a, int(n)) for e, st, a, n in adjectifs],
        scoreur_adjectifs=scoreur_adj,
        couverture_adjectifs=couverture,
        posts_hors_adjectifs=int(hors or 0),
    )


def evenements(cfg: Config) -> tuple[bool, list[Evenement]]:
    """Catalogue des événements datés, du plus récent au plus ancien.

    Renvoie `(disponible, liste)` : `disponible` vaut faux quand la table `evenements` n'existe pas
    (collecte non installée). Au plus `EVENEMENTS_MAX` lignes ; `FINAL` dédoublonne un même lien
    collecté deux fois (`ReplacingMergeTree`). Une catégorie hors de `CATEGORIES_EVENEMENT` devient
    `autre` ; un lien autre que `http(s)` devient `None` (`calculs.lien_sur`).
    """
    try:
        c = client(cfg)
        if "evenements" not in _tables_presentes(c):
            return False, []
        lignes = c.query(
            "SELECT id, date_publication, titre, categorie, source, lien FROM evenements FINAL "
            "ORDER BY date_publication DESC, id LIMIT %(n)s",
            parameters={"n": EVENEMENTS_MAX},
        ).result_rows
    except ErreurBase:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurBase(f"lecture impossible ({type(exc).__name__})") from exc
    return True, [
        Evenement(
            id=str(i), date=vers_utc(d), titre=str(t), source=str(src), lien=lien_sur(l),
            categorie=cat if cat in CATEGORIES_EVENEMENT else "autre",
        )
        for i, d, t, cat, src, l in lignes
    ]


def ping(cfg: Config) -> None:
    """Vérifie que ClickHouse répond (`SELECT 1`). Lève `ErreurBase` sinon."""
    try:
        c = client(cfg)
        c.query("SELECT 1")
    except ErreurBase:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErreurBase(f"ping impossible ({type(exc).__name__})") from exc
