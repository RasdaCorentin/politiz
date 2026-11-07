"""Comptage des adjectifs par cible politique et par stance (étiquettes silver).

Logique pure : aucun accès au disque ni à spaCy ici. Le tagueur est injecté : c'est une fonction
qui reçoit une liste de textes et renvoie, pour chaque texte, la liste des couples
`(forme, lemme)` des adjectifs trouvés. Les tests injectent un tagueur factice.

Bibliothèque standard et PyYAML seulement.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ENTITES_PATH = HERE.parents[2] / "ressources" / "lexique" / "entites.yaml"

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
MENTION_RE = re.compile(r"(?<!\w)@[\w.\-]+")
MIN_CARACTERES = 3
SEUIL_VUE = 3
# Tagués ADJ par spaCy mais ni qualificatifs ni adjectifs de sens : déterminants,
# indéfinis, sigles de partis. Liste fermée, décidée après relecture des premiers rangs.
EXCLUS = frozenset({
    "tout", "toute", "tous", "toutes", "autre", "autres", "même", "mêmes",
    "seul", "seule", "seuls", "seules", "premier", "première", "premiers", "premières",
    "tel", "telle", "tels", "telles", "chaque", "quel", "quelle", "quels", "quelles",
    "certain", "certaine", "certains", "certaines", "plusieurs", "aucun", "aucune",
    "nul", "nulle", "quelque", "quelques",
    "lfi", "rn", "lr", "ps", "pcf", "eelv", "udr", "lrem", "modem", "npa", "udi", "lo",
})

EN_TETE = '"adjectif","parti","représentant",stance,occurrences'


def normaliser(lemme: str) -> str:
    """Clé de normalisation d'un lemme : minuscules, sans accents, sans marque de pluriel.

    Décomposition Unicode NFD puis retrait des marques combinantes. Un `s` ou un `x` final est
    retiré si le mot fait au moins 5 lettres (« politiques » -> « politique », « grands » ->
    « grand », mais « gros » reste « gros »).
    """
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", lemme.lower())
        if unicodedata.category(c) != "Mn"
    )
    if len(sans_accents) >= 5 and sans_accents[-1] in "sx":
        return sans_accents[:-1]
    return sans_accents


# Exclusion testée sur la clé normalisée : « meme » et « seules » sont exclus comme « même » et « seul ».
EXCLUS_NORMALISEES = frozenset(normaliser(e) for e in EXCLUS)

# (forme, lemme) des adjectifs d'un texte, pour une liste de textes.
Tagueur = Callable[[list[str]], list[list[tuple[str, str]]]]
# Une ligne du comptage : adjectif, parti, représentant, stance, nombre de posts distincts.
Ligne = tuple[str, str, str, str, int]


def masquer(texte: str) -> str:
    """Remplace les URL par `<url>` et les @mentions par `@utilisateur`. La casse est conservée."""
    t = URL_RE.sub("<url>", texte)
    return MENTION_RE.sub("@utilisateur", t)


def charger_entites(chemin: Path = ENTITES_PATH) -> dict[str, dict]:
    """id -> entité de `entites.yaml`. Lu comme une donnée, pas importé."""
    donnees = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    return {e["id"]: e for e in donnees["entites"]}


def cibles_du_post(post: dict, entites: dict[str, dict]) -> set[tuple[str, str, str]]:
    """Couples `(parti, représentant, stance)` distincts d'un post.

    Une cible absente de `entites.yaml` (groupe-politique, gouvernement, autre) est ignorée.
    Pour un parti : `parti` = son nom, `représentant` vide. Pour un candidat : `représentant` = son
    nom ; `parti` = le nom du parti désigné par le champ optionnel `parti` de l'entité (id d'une
    autre entrée de `entites.yaml`), vide sinon. La stance est reprise telle quelle.
    """
    sortie: set[tuple[str, str, str]] = set()
    for cible in post.get("cibles") or []:
        entite = entites.get(cible.get("entite"))
        stance = cible.get("stance")
        if entite is None or not isinstance(stance, str):
            continue
        if entite["type"] == "parti":
            sortie.add((entite["nom"], "", stance))
        else:
            parti = entites.get(entite.get("parti"), {}).get("nom", "")
            sortie.add((parti, entite["nom"], stance))
    return sortie


def adjectifs_du_texte(couples: Iterable[tuple[str, str]]) -> set[str]:
    """Lemmes d'adjectifs distincts, en minuscules (accents conservés).

    Un token de moins de 3 caractères est ignoré. Un lemme exclu, ou dont la clé normalisée est
    exclue, est ignoré.
    """
    sortie = set()
    for forme, lemme in couples:
        lemme = lemme.lower()
        if lemme in EXCLUS or normaliser(lemme) in EXCLUS_NORMALISEES:
            continue
        if len(forme) >= MIN_CARACTERES and len(lemme) >= MIN_CARACTERES:
            sortie.add(lemme)
    return sortie


def distance_levenshtein(a: str, b: str) -> int:
    """Distance d'édition (insertion, suppression, substitution), programmation dynamique ligne à ligne."""
    if len(a) < len(b):
        a, b = b, a
    precedente = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        courante = [i]
        for j, cb in enumerate(b, 1):
            courante.append(min(precedente[j] + 1, courante[j - 1] + 1,
                                precedente[j - 1] + (ca != cb)))
        precedente = courante
    return precedente[-1]


def fautes_proches(a: str, b: str) -> bool:
    """Deux clés normalisées sont une même faute d'orthographe.

    Même initiale, les deux clés de 4 lettres au moins, distance d'édition admise : 2 si la
    plus courte fait 6 lettres ou plus, 1 si elle fait 4 ou 5 lettres.
    """
    if a[0] != b[0]:
        return False
    court = min(len(a), len(b))
    if court < 4:
        return False
    seuil = 2 if court >= 6 else 1
    if abs(len(a) - len(b)) > seuil:
        return False
    return distance_levenshtein(a, b) <= seuil


def rattacher_fautes(frequences: dict[str, int]) -> dict[str, str]:
    """Clé -> clé représentante. Une clé rare est rattachée à la plus fréquente qui lui est proche.

    Ordre de rang : fréquence décroissante, puis alphabétique. Pour chaque clé, le candidat retenu
    est le mieux classé parmi les clés proches. Un rattachement pointe toujours vers une clé mieux
    classée : la chaîne se termine donc, et la représentante est atteinte en suivant les liens.
    """
    rang = sorted(frequences, key=lambda c: (-frequences[c], c))
    rattachement: dict[str, str] = {}
    for i, cle in enumerate(rang):
        for plus_frequente in rang[:i]:
            if fautes_proches(cle, plus_frequente):
                rattachement[cle] = plus_frequente
                break

    def representante(cle: str) -> str:
        while cle in rattachement:
            cle = rattachement[cle]
        return cle

    return {cle: representante(cle) for cle in rang}


def regrouper(pids_par_lemme: dict[str, set[str]]) -> dict[str, str]:
    """Lemme -> forme affichée.

    1. Les lemmes de même clé normalisée forment une clé.
    2. Les clés proches (fautes d'orthographe, voir `fautes_proches`) se rattachent à la plus
       fréquente. La fréquence d'une clé est son nombre de posts distincts.
    3. La forme affichée d'un groupe est le lemme apparu dans le plus de posts ; à égalité,
       l'ordre alphabétique.
    Le résultat ne dépend pas de l'ordre du dictionnaire d'entrée.
    """
    par_cle: dict[str, list[str]] = defaultdict(list)
    pids_par_cle: dict[str, set[str]] = defaultdict(set)
    for lemme, pids in pids_par_lemme.items():
        cle = normaliser(lemme)
        par_cle[cle].append(lemme)
        pids_par_cle[cle] |= pids

    representante = rattacher_fautes({cle: len(p) for cle, p in pids_par_cle.items()})
    par_groupe: dict[str, list[str]] = defaultdict(list)
    for cle, membres in par_cle.items():
        par_groupe[representante[cle]].extend(membres)

    sortie = {}
    for membres in par_groupe.values():
        affichee = min(membres, key=lambda l: (-len(pids_par_lemme[l]), l))
        for lemme in membres:
            sortie[lemme] = affichee
    return sortie


def compter(posts: list[dict], entites: dict[str, dict], tagueur: Tagueur) -> tuple[dict, dict]:
    """Compte les posts distincts par (adjectif, parti, représentant, stance).

    `posts` : dictionnaires `post_id`, `text` (déjà masqué), `cibles` (étiquettes silver).
    Renvoie `(compte, stats)`. Un post sans cible retenue n'est pas envoyé au tagueur.
    L'adjectif est la forme affichée de son groupe (voir `regrouper`).
    """
    avec_cible = []
    for post in posts:
        cibles = cibles_du_post(post, entites)
        if cibles:
            avec_cible.append((str(post["post_id"]), post["text"], cibles))

    tags = tagueur([texte for _, texte, _ in avec_cible]) if avec_cible else []
    if len(tags) != len(avec_cible):
        raise ValueError("le tagueur doit renvoyer une liste par texte")

    lemmes_par_post = [(pid, cibles, adjectifs_du_texte(couples))
                       for (pid, _, cibles), couples in zip(avec_cible, tags)]
    pids_par_lemme: dict[str, set[str]] = defaultdict(set)
    for pid, _, lemmes in lemmes_par_post:
        for lemme in lemmes:
            pids_par_lemme[lemme].add(pid)
    affichee = regrouper(pids_par_lemme)

    compte: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for pid, cibles, lemmes in lemmes_par_post:
        for adjectif in {affichee[lemme] for lemme in lemmes}:
            for parti, rep, stance in cibles:
                compte[(adjectif, parti, rep, stance)].add(pid)

    stats = {"posts": len(posts), "posts_avec_cible": len(avec_cible),
             "lemmes_distincts": len(pids_par_lemme),
             "adjectifs_distincts": len(set(affichee.values()))}
    return {cle: len(pids) for cle, pids in compte.items()}, stats


def lignes(compte: dict) -> list[Ligne]:
    """Toutes les lignes, triées par adjectif puis cible puis stance."""
    return sorted((a, p, r, s, n) for (a, p, r, s), n in compte.items())


def controle_gold(gold: list[dict], silver: dict[str, dict], entites: dict[str, dict]) -> dict:
    """Accord silver/gold sur les cibles (contrôle de cohérence, pas de comptage).

    Compare, post par post : l'ensemble des entités (`entites_identiques`) et l'ensemble des
    couples (entité, stance) (`cibles_identiques`). Ne compte que des nombres.
    """
    sortie = {"posts_gold": len(gold), "absents_silver": 0, "cibles_hors_lexique": 0,
              "entites_identiques": 0, "cibles_identiques": 0}
    for g in gold:
        pid = str(g["post_id"])
        cibles_g = {(c.get("entite"), c.get("stance")) for c in g.get("cibles") or []}
        sortie["cibles_hors_lexique"] += sum(1 for e, _ in cibles_g if e not in entites)
        if pid not in silver:
            sortie["absents_silver"] += 1
            continue
        cibles_s = {(c.get("entite"), c.get("stance")) for c in silver[pid].get("cibles") or []}
        sortie["entites_identiques"] += {e for e, _ in cibles_g} == {e for e, _ in cibles_s}
        sortie["cibles_identiques"] += cibles_g == cibles_s
    return sortie


def vue(lignes_: list[Ligne], stance: str, seuil: int = SEUIL_VUE) -> list[Ligne]:
    """Filtre une stance (`pour` ou `contre`), retire les lignes sous le seuil, classe par
    occurrences décroissantes. Le fichier complet garde toutes les lignes."""
    retenues = [l for l in lignes_ if l[3] == stance and l[4] >= seuil]
    return sorted(retenues, key=lambda l: (-l[4], l[0], l[1], l[2]))


def _quote(texte: str) -> str:
    return '"' + texte.replace('"', '""') + '"'


def ecrire_csv(chemin: Path, lignes_: list[Ligne]) -> None:
    """Écrit le CSV au format `EN_TETE`. Stance et occurrences ne sont pas entre guillemets."""
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        f.write(EN_TETE + "\n")
        for adjectif, parti, rep, stance, n in lignes_:
            if any(c in stance for c in ',"\n'):
                raise ValueError(f"stance non sûre pour le CSV : {stance!r}")
            f.write(f"{_quote(adjectif)},{_quote(parti)},{_quote(rep)},{stance},{n}\n")
