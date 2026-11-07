"""CLI : `python -m adjectifs --corpus <dossier du corpus>`.

Lit les étiquettes silver et les textes, compte les adjectifs (spaCy) et écrit les CSV sous
`<corpus>/adjectifs/`. N'affiche que des compteurs : aucun texte de post.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comptage import charger_entites, compter, controle_gold, ecrire_csv, lignes, masquer, vue

SILVER = Path("annotation/silver/final/silver_v1.jsonl")
TEXTES = Path("annotation/lots/corpus_propre.jsonl")
GOLD = Path("annotation/annotations/corentin.jsonl")
SORTIE = "adjectifs"

SPACY_VERSION = "3.8.7"
MODELE_SPACY = "fr_core_news_sm"
MODELE_VERSION = "3.8.0"
MODELE_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    f"{MODELE_SPACY}-{MODELE_VERSION}/{MODELE_SPACY}-{MODELE_VERSION}-py3-none-any.whl"
)


def _lire_jsonl(chemin: Path) -> list[dict]:
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


def charger_silver(chemin: Path) -> dict[str, dict]:
    """post_id -> étiquette silver (une seule par post)."""
    return {str(r["post_id"]): r for r in _lire_jsonl(chemin) if "post_id" in r}


def charger_textes(chemin: Path) -> dict[str, str]:
    return {str(r["post_id"]): r["text"] for r in _lire_jsonl(chemin)}


def charger_spacy():
    """Tagueur spaCy : renvoie une fonction `textes -> [[(forme, lemme), ...], ...]` (ADJ)."""
    try:
        import spacy
    except ImportError:
        sys.exit("spaCy absent. Lancer avec : uv run --with spacy==" + SPACY_VERSION
                 + " --with " + MODELE_URL + " python -m adjectifs --corpus <dossier>")
    try:
        nlp = spacy.load(MODELE_SPACY)
    except OSError:
        sys.exit(f"modèle {MODELE_SPACY} absent. Installer {MODELE_URL}")
    if spacy.__version__ != SPACY_VERSION:
        print(f"avertissement : spaCy {spacy.__version__} au lieu de {SPACY_VERSION}", file=sys.stderr)

    def tagueur(textes: list[str]) -> list[list[tuple[str, str]]]:
        return [[(t.text, t.lemma_) for t in doc if t.pos_ == "ADJ"]
                for doc in nlp.pipe(textes, batch_size=64)]

    return tagueur


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compte les adjectifs par cible et par stance.")
    parser.add_argument("--corpus", required=True, help="dossier du corpus (hors dépôt)")
    args = parser.parse_args(argv)
    corpus = Path(args.corpus).expanduser()

    silver = charger_silver(corpus / SILVER)
    textes = charger_textes(corpus / TEXTES)
    entites = charger_entites()
    posts = [{"post_id": pid, "text": masquer(textes[pid]), "cibles": r.get("cibles")}
             for pid, r in silver.items() if pid in textes]
    sans_texte = len(silver) - len(posts)

    gold = _lire_jsonl(corpus / GOLD) if (corpus / GOLD).exists() else []
    ctrl = controle_gold(gold, silver, entites)

    compte, stats = compter(posts, entites, charger_spacy())
    lg = lignes(compte)
    dest = corpus / SORTIE
    dest.mkdir(parents=True, exist_ok=True)
    ecrire_csv(dest / "adjectifs.csv", lg)
    ecrire_csv(dest / "popularite.csv", vue(lg, "pour"))
    ecrire_csv(dest / "depopularite.csv", vue(lg, "contre"))

    print(f"posts silver : {len(silver)} (sans texte : {sans_texte})")
    print(f"posts avec cible retenue : {stats['posts_avec_cible']} / {stats['posts']}")
    print(f"lemmes distincts : {stats['lemmes_distincts']} ; adjectifs après normalisation : "
          f"{stats['adjectifs_distincts']}")
    print(f"lignes : {len(lg)} ; adjectifs distincts : {len({l[0] for l in lg})}")
    print(f"contrôle gold : {ctrl}")


if __name__ == "__main__":
    main()
