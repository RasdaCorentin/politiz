"""Module d'essai de `distant/` : imite le contrat de `modele.entrainer` (contrat du modèle dans contrats-poc.md).

Tout est factice : il ne charge aucun modèle et n'entraîne rien. Il vérifie que torch voit CUDA,
vérifie la présence des deux fichiers du corpus, écrit un run conforme au contrat (JSON factices,
pas de poids), puis imprime le chemin du run en dernière ligne de la sortie standard.
Lancé par `distant.lancer entrainer --module distant.tests.factice_entrainer`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

FICHIERS_CORPUS = ("annotation/train_silver.jsonl", "annotation/eval_fige.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Entraînement factice (essai de distant/).")
    p.add_argument("--tache", required=True, choices=["stance", "emotion"])
    p.add_argument("--corpus", required=True, type=Path)
    p.add_argument("--sortie", required=True, type=Path)
    p.add_argument("--epoques", type=int, default=3)
    args, _ = p.parse_known_args(argv)

    import torch

    if not torch.cuda.is_available():
        print("CUDA indisponible", file=sys.stderr)
        return 1
    for rel in FICHIERS_CORPUS:
        if not (args.corpus / rel).is_file():
            print(f"fichier absent : {rel}", file=sys.stderr)
            return 2
    with open(args.corpus / "annotation" / "train_silver.jsonl", encoding="utf-8") as f:
        n_train = sum(1 for ligne in f if ligne.strip())

    run = args.sortie / f"{args.tache}-{dt.datetime.now():%Y%m%d-%H%M}"
    (run / "model").mkdir(parents=True, exist_ok=True)
    for epoque in range(1, args.epoques + 1):
        time.sleep(4)
        print(f"epoque {epoque}/{args.epoques} (factice)", file=sys.stderr, flush=True)

    (run / "model" / "config.json").write_text(json.dumps({"factice": True}), encoding="utf-8")
    (run / "modele.json").write_text(json.dumps({
        "tache": args.tache, "etiquettes": ["factice"], "base": "factice",
        "entree": {"longueur_max": 8, "normaliser": False}, "noms_cibles": {}, "factice": True,
    }), encoding="utf-8")
    (run / "metriques.json").write_text(json.dumps({
        "accuracy": 0.0, "f1_macro": 0.0, "par_classe": {}, "matrice_confusion": [],
        "effectifs": {"train": n_train}, "source": "silver", "factice": True,
        "duree_s": 4 * args.epoques, "materiel": torch.cuda.get_device_name(0),
    }), encoding="utf-8")
    (run / "config_entrainement.json").write_text(json.dumps({
        "graine": 2027, "epoques": args.epoques, "factice": True,
        "versions": {"torch": torch.__version__},
    }), encoding="utf-8")
    print(run.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
