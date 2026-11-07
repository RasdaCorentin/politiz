"""Données de l'entraînement : lecture du silver, exemples, découpe, garde-fous.

Le fichier lu est `train_silver.jsonl`, écrit par `python -m annotation.export --silver` (une
ligne par post : post_id, text, source, pertinent, cibles, emotion...). Ce module ne lit que
des fichiers de données (JSONL, JSON, YAML) et n'importe rien de `annotation/`.

Deux tâches, un même code :
- `stance`  : un exemple par couple (post, cible) ; l'entrée du modèle est la paire
              (nom de la cible, texte) ;
- `emotion` : un exemple par post ; l'entrée du modèle est le texte.

Aucun texte de post n'est affiché ni journalisé ici.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import unicodedata
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from projection_emotion import reduire_emotion, reduire_etiquettes
from projection_stance import regrouper_etiquettes, regrouper_stance

MODELE_DIR = Path(__file__).resolve().parent
TRAINING_DIR = MODELE_DIR.parent
DEPOT = TRAINING_DIR.parents[1]
SCHEMA_PATH = TRAINING_DIR / "annotation" / "schema.yaml"
ENTITES_PATH = DEPOT / "ressources" / "lexique" / "entites.yaml"

TACHES = ("stance", "emotion")
GRAINE = 2027
# `autre` est un fourre-tout sans nom : le modèle ne peut pas savoir quelle cible lui demander,
# et le job Spark ne produit jamais cette cible (scoreur décrit dans contrats-poc.md).
ENTITES_EXCLUES = ("autre",)
MENTION_SILVER = "silver : test de fumée, pas une mesure du modèle"
NOMS_SPECIAUX = {"gouvernement": "Gouvernement", "groupe-politique": "Groupe politique", "autre": "Autre"}


@dataclass(frozen=True)
class Exemple:
    post_id: str
    texte: str
    cible: str | None      # id d'entité (stance) ; None pour l'émotion
    etiquette: str


# --------------------------------------------------------------------------- fichiers
def dossier_corpus(arg: str | None = None) -> Path:
    valeur = arg or os.environ.get("SAE_CORPUS_DIR")
    if not valeur:
        raise SystemExit("Dossier du corpus inconnu : définir SAE_CORPUS_DIR ou passer --corpus-dir.")
    return Path(valeur).expanduser()


def charger_yaml(chemin: Path) -> dict:
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def lire_jsonl(chemin: Path) -> list[dict]:
    """Lit un JSONL. Une ligne illisible arrête tout : un jeu qui rétrécit en silence est pire."""
    lignes = []
    with open(chemin, encoding="utf-8") as f:
        for n, ligne in enumerate(f, 1):
            if not ligne.strip():
                continue
            try:
                lignes.append(json.loads(ligne))
            except json.JSONDecodeError as e:
                raise ValueError(f"{Path(chemin).name} ligne {n} : JSON invalide ({e.msg})") from None
    return lignes


def etiquettes(tache: str, schema: dict | None = None, regroupe: bool = False,
               emotion_reduite: bool = False) -> list[str]:
    """Étiquettes ordonnées de la tâche, lues dans schema.yaml (source unique).
    `regroupe` (stance seulement) : `mention` est fusionnée dans `neutre` (projection_stance).
    `emotion_reduite` (emotion seulement) : trois classes, joie / colere / neutre (projection_emotion)."""
    schema = schema or charger_yaml(SCHEMA_PATH)
    if tache == "stance":
        liste = list(schema["cibles"]["stance"])
        return regrouper_etiquettes(liste) if regroupe else liste
    if tache == "emotion":
        liste = list(schema["emotion"]["valeurs"])
        return reduire_etiquettes(liste) if emotion_reduite else liste
    raise ValueError(f"tâche inconnue : {tache} (attendu : {', '.join(TACHES)})")


def charger_lignes(chemin: Path, source_attendue: str | tuple[str, ...] = "silver") -> list[dict]:
    """Lignes d'un export. Toutes doivent porter `source` parmi `source_attendue` (une ou plusieurs)."""
    attendues = {source_attendue} if isinstance(source_attendue, str) else set(source_attendue)
    lignes = lire_jsonl(chemin)
    if not lignes:
        raise ValueError(f"{Path(chemin).name} est vide")
    autres = {str(ligne.get("source")) for ligne in lignes} - attendues
    if autres:
        raise ValueError(f"{Path(chemin).name} : source {sorted(autres)} au lieu de « {' ou '.join(sorted(attendues))} »")
    return lignes


# --------------------------------------------------------------------------- garde-fous
def empreinte(ids: list[str]) -> str:
    """Même empreinte que annotation.export : SHA-256 des ids triés, un par ligne."""
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def ids_exclus(corpus: Path) -> set[str]:
    """Ids du jeu d'évaluation figé et du lot pilote : ils n'entrent jamais dans l'entraînement."""
    adir = Path(corpus) / "annotation"
    fige = adir / "eval_fige.json"
    if not fige.exists():
        raise ValueError("eval_fige.json absent : le jeu d'évaluation n'est pas figé, pas d'entraînement "
                         "(python -m annotation.export --freeze-eval).")
    data = json.loads(fige.read_text(encoding="utf-8"))
    if empreinte([str(i) for i in data["ids"]]) != data["sha256"]:
        raise ValueError("eval_fige.json a été modifié : arrêt.")
    ids = {str(i) for i in data["ids"]}
    for lot in ("lot_eval", "lot_00_pilote"):
        chemin = adir / "lots" / f"{lot}.jsonl"
        if chemin.exists():
            ids |= {str(ligne["post_id"]) for ligne in lire_jsonl(chemin)}
    return ids


def verifier_garde_fou(lignes: list[dict], corpus: Path) -> int:
    """Refuse tout post du pilote ou de l'évaluation. Retourne le nombre d'ids exclus contrôlés."""
    exclus = ids_exclus(corpus)
    fuite = {str(ligne["post_id"]) for ligne in lignes} & exclus
    if fuite:
        raise ValueError(f"{len(fuite)} post(s) du pilote ou de l'évaluation dans les données "
                         "d'entraînement : arrêt.")
    return len(exclus)


# --------------------------------------------------------------------------- noms de cibles
def nom_cible(identifiant: str, entite: dict | None = None) -> str:
    """Nom de la cible tel que le modèle le lit : `nom` de l'entité s'il existe, sinon l'id lisible.

    Les ids du lexique sont en minuscules sans accents. Les sigles d'un seul mot de 4 lettres au
    plus (lfi, npa, eelv...) passent en majuscules.
    """
    if entite and entite.get("nom"):
        return str(entite["nom"])
    if identifiant in NOMS_SPECIAUX:
        return NOMS_SPECIAUX[identifiant]
    mots = identifiant.split()
    if len(mots) == 1 and "-" not in identifiant and len(identifiant) <= 4:
        return identifiant.upper()
    return " ".join("-".join(p.capitalize() for p in mot.split("-")) for mot in mots)


def noms_cibles(entites: list[dict] | None = None) -> dict[str, str]:
    """id d'entité -> nom lu par le modèle, pour toutes les entités du lexique et les valeurs spéciales."""
    if entites is None:
        entites = charger_yaml(ENTITES_PATH)["entites"]
    noms = {e["id"]: nom_cible(e["id"], e) for e in entites}
    for ident in NOMS_SPECIAUX:
        noms.setdefault(ident, nom_cible(ident))
    return noms


# --------------------------------------------------------------------------- exemples
def construire_exemples(lignes: list[dict], tache: str, exclues: tuple[str, ...] = ENTITES_EXCLUES,
                        schema: dict | None = None, regroupe: bool = False,
                        emotion_reduite: bool = False) -> list[Exemple]:
    """Exemples d'une tâche. Seuls les posts `pertinent = oui` servent : `doute` est un avis sans
    garantie, `non` n'a ni cible ni émotion. Une cible en double dans un post compte une fois.
    `regroupe` (stance seulement) : `mention` devient `neutre` avant le filtrage des étiquettes.
    `emotion_reduite` (emotion seulement) : l'émotion passe par reduire_emotion ; None (ex. surprise)
    écarte l'exemple."""
    valides = set(etiquettes(tache, schema, regroupe, emotion_reduite))
    sortie: list[Exemple] = []
    for ligne in lignes:
        texte = preparer_texte(ligne.get("text"))
        if ligne.get("pertinent") != "oui" or not texte:
            continue
        pid = str(ligne["post_id"])
        if tache == "stance":
            vues: set[str] = set()
            for c in ligne.get("cibles") or []:
                entite, stance = c.get("entite"), c.get("stance")
                if regroupe:
                    stance = regrouper_stance(stance)
                if not entite or entite in exclues or entite in vues or stance not in valides:
                    continue
                vues.add(entite)
                sortie.append(Exemple(pid, texte, entite, stance))
        else:
            emotion = ligne.get("emotion")
            if emotion_reduite:
                emotion = reduire_emotion(emotion)
            if emotion in valides:
                sortie.append(Exemple(pid, texte, None, emotion))
    return sortie


def decouper(exemples: list[Exemple], part_validation: float = 0.12,
             graine: int = GRAINE) -> tuple[list[Exemple], list[Exemple]]:
    """Découpe train / validation. Par post (un post n'est jamais des deux côtés : ses couples
    partagent le même texte) et stratifiée sur l'étiquette. Graine fixe : même découpe à chaque appel."""
    from sklearn.model_selection import StratifiedGroupKFold
    if not 0 < part_validation < 0.5:
        raise ValueError("part_validation doit être dans ]0 ; 0,5[")
    plis = max(2, round(1 / part_validation))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")      # classes rares : sklearn avertit, la découpe reste valide
        cv = StratifiedGroupKFold(n_splits=plis, shuffle=True, random_state=graine)
        i_train, i_val = next(iter(cv.split([0] * len(exemples), [e.etiquette for e in exemples],
                                            [e.post_id for e in exemples])))
    return [exemples[i] for i in sorted(i_train)], [exemples[i] for i in sorted(i_val)]


def effectifs(exemples: list[Exemple]) -> dict[str, int]:
    return dict(sorted(Counter(e.etiquette for e in exemples).items()))


# --------------------------------------------------------------------------- déséquilibre
def echantillon_epoque(exemples: list[Exemple], plafond: int | None, rng: random.Random) -> list[Exemple]:
    """Sous-échantillonne les classes au-dessus de `plafond` exemples, avec un tirage neuf à chaque
    époque : la classe majoritaire est vue en entier au fil des époques, les rares à chaque époque."""
    if not plafond:
        return list(exemples)
    par_classe: dict[str, list[Exemple]] = defaultdict(list)
    for e in exemples:
        par_classe[e.etiquette].append(e)
    sortie: list[Exemple] = []
    for classe in sorted(par_classe):
        liste = par_classe[classe]
        sortie.extend(rng.sample(liste, plafond) if len(liste) > plafond else liste)
    return sortie


def poids_classes(indices: list[int], n_classes: int, alpha: float) -> list[float]:
    """Poids de perte par classe : (n / (K * n_c)) ** alpha, ramenés à une moyenne de 1 sur les exemples.

    alpha = 0 : aucun poids. alpha = 1 : poids « équilibrés » (inverse de la fréquence). Entre les deux,
    les classes très rares pèsent moins fort, ce qui évite qu'une poignée d'exemples dicte la perte.
    """
    comptes = Counter(indices)
    n = len(indices)
    brut = [(n / (n_classes * max(comptes.get(c, 0), 1))) ** alpha for c in range(n_classes)]
    moyenne = sum(brut[c] * comptes.get(c, 0) for c in range(n_classes)) / n
    return [w / moyenne for w in brut]


# --------------------------------------------------------------------------- nettoyage
# Recopie de `normaliser` et `nettoyer_texte` de src/streaming/pii.py (étapes 1 et 2 du job Spark) :
# mêmes regex, même ordre. Recopie et non import : src/training/ n'importe pas src/streaming/.
# tests/test_entree_modele_identique.py compare les deux sur des textes inventés.
_URL_SPARK = re.compile(r"https?://\S+|\bwww\.\S+")
_HANDLE_SPARK = re.compile(r"@[a-z0-9][a-z0-9._\-]*")
_DID_SPARK = re.compile(r"\bdid:[a-z0-9]+:[a-z0-9._:%\-]*")
_ESPACES_SPARK = re.compile(r"\s+")
# Marqueurs posés par les lots d'annotation et le silver : Spark ne les produit jamais.
_MARQUEURS_LOTS = re.compile(r"\[(?:url|mention)\]", re.IGNORECASE)


def nettoyer_comme_spark(texte: str | None) -> str:
    """Minuscules, sans accents, URL / `did:` / `@handles` remplacés par un espace, espaces réduits.
    Vide si le texte est vide ou None."""
    if not texte:
        return ""
    nfkd = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    t = _URL_SPARK.sub(" ", t)
    t = _DID_SPARK.sub(" ", t)
    t = _HANDLE_SPARK.sub(" ", t)
    return _ESPACES_SPARK.sub(" ", t).strip()


def retirer_marqueurs_lots(texte: str | None) -> str:
    """Remplace `[url]` et `[mention]` (insensible à la casse) par un espace."""
    return _MARQUEURS_LOTS.sub(" ", texte or "")


def preparer_texte(texte: str | None) -> str:
    """Texte d'entrée du modèle : marqueurs des lots retirés, puis nettoyage du job Spark.
    Idempotente sur les textes courants (testée dans modele/tests/test_donnees.py)."""
    return nettoyer_comme_spark(retirer_marqueurs_lots(texte))


# --------------------------------------------------------------------------- entrée du modèle
def normaliser_contrat(texte: str) -> str:
    """Normalisation de l'étape de nettoyage du job Spark : minuscules, sans accents."""
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def jetons(tokenizer, textes: list[str], cibles: list[str] | None, tache: str, noms: dict[str, str],
            longueur_max: int, normaliser: bool = False) -> list[list[int]]:
    """Identifiants de jetons, sans remplissage, pour l'entraînement et la prédiction.

    stance : paire (nom de la cible, texte), seul le texte est tronqué ; émotion : texte seul.
    """
    if tache not in TACHES:
        raise ValueError(f"tâche inconnue : {tache}")
    if tache == "stance":
        if cibles is None or len(cibles) != len(textes):
            raise ValueError("la stance demande une cible par texte")
        entrees = [entree_modele(t, c, noms, normaliser) for t, c in zip(textes, cibles)]
        enc = tokenizer([a for a, _ in entrees], [b for _, b in entrees],
                        truncation="only_second", max_length=longueur_max)
    else:
        entrees = [entree_modele(t, None, noms, normaliser) for t in textes]
        enc = tokenizer([a for a, _ in entrees], truncation=True, max_length=longueur_max)
    return enc["input_ids"]


def entree_modele(texte: str, cible: str | None, noms: dict[str, str],
                  normaliser: bool = False) -> tuple[str, str | None]:
    """(premier segment, second segment) donnés au tokenizer.

    stance : (nom de la cible, texte) ; émotion : (texte, None). `normaliser` rejoue la normalisation
    du job Spark, pour tester le modèle sur le texte qu'il recevra si le contrat n'est pas changé.
    """
    if normaliser:
        texte = normaliser_contrat(texte)
    if cible is None:
        return texte, None
    nom = noms.get(cible) or nom_cible(cible)
    return (normaliser_contrat(nom) if normaliser else nom), texte
