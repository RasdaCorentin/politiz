"""Logique pure de la saisie d'un lot gold : lecture du lot, valeurs initiales, enregistrement.

Sans Streamlit : testable avec des posts fabriqués. Le texte des posts n'est jamais imprimé.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from annotation.storage import read_jsonl

# Champs que chaque post d'un lot gold doit porter.
CHAMPS_OBLIGATOIRES = ("post_id", "lot", "texte")

# Valeurs proposées au départ. L'émotion n'a pas de défaut : un choix explicite est demandé,
# sinon une validation sans clic produirait « neutre » (biais d'ancrage).
DEFAUTS = {"pertinent": "oui", "cibles": [], "themes": [], "emotion": None,
           "ironie": "non", "regle_suffit": "non", "indice": "", "commentaire": ""}


def lire_lot(path: Path) -> list[dict]:
    """Posts d'un lot gold, dans l'ordre du fichier. Erreur explicite si le format n'est pas bon."""
    posts = read_jsonl(Path(path))
    if not posts:
        raise ValueError(f"lot vide ou introuvable : {Path(path).name}")
    vus: set[str] = set()
    for i, post in enumerate(posts, 1):
        manquants = [c for c in CHAMPS_OBLIGATOIRES if not post.get(c)]
        if manquants:
            raise ValueError(f"ligne {i} : champ(s) manquant(s) : {', '.join(manquants)}")
        if str(post["post_id"]) in vus:
            raise ValueError(f"ligne {i} : post_id en double")
        vus.add(str(post["post_id"]))
    return posts


def valeurs_initiales(existing: dict | None, entites: list[str]) -> dict:
    """Valeurs affichées pour un post : sa dernière annotation, sinon les valeurs par défaut.

    Les cibles dont l'entité n'est plus dans entites.yaml sont écartées (sinon le formulaire
    refuserait de s'afficher).
    """
    if existing is None:
        return copy.deepcopy(DEFAUTS)
    v = {k: copy.deepcopy(existing.get(k, d)) for k, d in DEFAUTS.items()}
    v["cibles"] = [c for c in v["cibles"] if c.get("entite") in entites]
    return v


def contexte(post: dict) -> tuple[str, str] | None:
    """(libellé, texte) du post parent ou cité, ou None si le post n'a pas de contexte."""
    texte = post.get("contexte_texte")
    if not texte:
        return None
    libelle = {"reponse": "Post parent", "citation": "Post cité"}.get(post.get("contexte_type"), "Contexte")
    return libelle, texte


def enregistrement(post: dict, annotateur: str, choix: dict) -> dict:
    """Ligne d'annotation au format existant (mêmes champs, lot = lot du post)."""
    return {
        "post_id": post["post_id"],
        "lot": post["lot"],
        "annotateur": annotateur.strip(),
        "pertinent": choix.get("pertinent"),
        "cibles": choix.get("cibles", []),
        "themes": choix.get("themes", []),
        "emotion": choix.get("emotion"),
        "ironie": choix.get("ironie"),
        "regle_suffit": choix.get("regle_suffit"),
        "indice": choix.get("indice", ""),
        "commentaire": choix.get("commentaire", ""),
    }


def config(argv: list[str], environ: dict) -> tuple[Path | None, str | None, str | None]:
    """(lot, annotateur, dossier du corpus) : arguments de ligne de commande, sinon variables SAE_*."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--lot")
    p.add_argument("--annotateur")
    p.add_argument("--corpus-dir")
    ns, _ = p.parse_known_args(argv)
    lot = ns.lot or environ.get("SAE_LOT")
    nom = ns.annotateur or environ.get("SAE_ANNOTATEUR")
    corpus = ns.corpus_dir or None
    return (Path(lot).expanduser() if lot else None), (nom or None), corpus
