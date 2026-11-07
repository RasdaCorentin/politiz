"""Évaluer un run sur le gold (annotation humaine).

    python -m modele.evaluer_gold --run <dossier du run> [--corpus <dossier>] [--gold F.jsonl ...]
                                  [--emotion-3-classes] [--sortie F.json]

Le gold est lu dans les exports `annotation/train.jsonl` et `annotation/eval.jsonl` du corpus
(`source: gold`, écrits par `python -m annotation.export`), sauf si `--gold` en donne d'autres.
Le texte passe par le nettoyage du job Spark (`donnees.preparer_texte`) : c'est l'entrée de la
production, quel que soit le run.

Les classes suivent le run : un run à 3 émotions projette le gold sur 3 classes, un run à stance
regroupée fusionne `mention` dans `neutre`. `--emotion-3-classes` projette aussi un run à 7 émotions
(gold et prédictions) : deux runs se comparent alors sur la même échelle.

`--reference silver` lit des lignes `source: silver` (posts tenus hors de l'entraînement) : la
mesure dit alors l'accord avec le LLM, pas la qualité.

Sortie : agrégats seulement (effectifs, métriques, rappel macro, intervalle de Wilson de
l'accuracy et du rappel de chaque classe, classe majoritaire).
Aucun texte ni identifiant de post.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

from projection_emotion import reduire_emotion

from . import donnees, evaluation

FICHIERS_GOLD = ("train.jsonl", "eval.jsonl")
ETIQUETTES_3 = ["joie", "colere", "neutre"]
MENTIONS = {"gold": "gold : annotation humaine, peu d'exemples ; lire l'intervalle",
            "silver": "silver : accord avec le LLM, pas une mesure de qualité"}


def wilson(succes: int, n: int, z: float = 1.96) -> list[float]:
    """Intervalle de Wilson à 95 % d'une proportion."""
    if n == 0:
        return [0.0, 0.0]
    p = succes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    marge = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - marge), 4), round(min(1.0, centre + marge), 4)]


def charger_gold(fichiers: list[Path], source: str = "gold") -> list[dict]:
    lignes: list[dict] = []
    for f in fichiers:
        if f.is_file() and f.stat().st_size:
            lignes += donnees.charger_lignes(f, source_attendue=source)
    if not lignes:
        raise ValueError(f"aucune ligne {source} : lancer d'abord python -m annotation.export")
    return lignes


def options_du_run(meta: dict) -> tuple[bool, bool]:
    """(stance regroupée, émotion réduite), lues dans les étiquettes du run."""
    etiq = set(meta["etiquettes"])
    return (meta["tache"] == "stance" and "mention" not in etiq,
            meta["tache"] == "emotion" and etiq == set(ETIQUETTES_3))


def mesurer(vrais: list[str], predits: list[str], etiquettes: list[str]) -> dict:
    justes = sum(v == p for v, p in zip(vrais, predits))
    majo, n_majo = Counter(vrais).most_common(1)[0] if vrais else (None, 0)
    resume = evaluation.resume(vrais, predits, etiquettes)
    rappels = {e: wilson(sum(v == p == e for v, p in zip(vrais, predits)), c["support"])
               for e, c in resume["par_classe"].items() if c["support"]}
    return {
        "n": len(vrais),
        **resume,
        "rappel_ic95": rappels,
        "etiquettes": etiquettes,
        "accuracy_ic95": wilson(justes, len(vrais)),
        "classe_majoritaire": {"classe": majo, "accuracy": round(n_majo / len(vrais), 4) if vrais else 0.0},
        "effectifs_gold": dict(Counter(vrais)),
    }


def evaluer(predicteur, lignes: list[dict], projeter_3: bool = False, source: str = "gold") -> dict:
    meta = predicteur.meta
    regroupe, reduite = options_du_run(meta)
    exemples = donnees.construire_exemples(lignes, meta["tache"], regroupe=regroupe,
                                           emotion_reduite=reduite or projeter_3)
    if not exemples:
        raise ValueError("aucun exemple gold pour cette tâche")
    cibles = [e.cible for e in exemples] if meta["tache"] == "stance" else None
    predits = [p["etiquette"] for p in predicteur.predire([e.texte for e in exemples], cibles)]
    etiquettes = list(predicteur.etiquettes)
    if projeter_3 and not reduite:
        predits = [reduire_emotion(p) or "non_evalue" for p in predits]
        etiquettes = ETIQUETTES_3
    vrais = [e.etiquette for e in exemples]
    return {
        "run": predicteur.dossier.name,
        "tache": meta["tache"],
        "projection_3_classes": bool(projeter_3 and not reduite),
        "posts_gold": len({e.post_id for e in exemples}),
        **mesurer(vrais, predits, etiquettes),
        "reference": source,
        "mention": MENTIONS[source],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--corpus")
    ap.add_argument("--gold", action="append", default=[], metavar="FICHIER")
    ap.add_argument("--emotion-3-classes", action="store_true",
                    help="projette un run à 7 émotions sur joie, colere, neutre (gold et prédictions)")
    ap.add_argument("--reference", choices=tuple(MENTIONS), default="gold",
                    help="source attendue des lignes de --gold : silver mesure l'accord avec le LLM "
                         "(posts tenus hors de l'entraînement, ex. pilote et évaluation figée)")
    ap.add_argument("--sortie")
    a = ap.parse_args(argv)
    try:
        from .predict import Predicteur
        predicteur = Predicteur(a.run)
        if a.emotion_3_classes and predicteur.tache != "emotion":
            raise ValueError("--emotion-3-classes ne vaut que pour un run d'émotion")
        fichiers = [Path(f) for f in a.gold] or [donnees.dossier_corpus(a.corpus) / "annotation" / f
                                                 for f in FICHIERS_GOLD]
        resultat = evaluer(predicteur, charger_gold(fichiers, a.reference), a.emotion_3_classes, a.reference)
    except (ValueError, OSError, KeyError) as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    texte = json.dumps(resultat, ensure_ascii=False, indent=1)
    if a.sortie:
        Path(a.sortie).write_text(texte + "\n", encoding="utf-8")
    print(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
