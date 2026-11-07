#!/usr/bin/env python3
"""Compare le scoreur à règles `lexique-v1` et CamemBERT sur les mêmes exemples de validation.

    python scripts/comparer_regex_modele.py --corpus <dossier> \\
        --run-stance <run> --run-emotion <run> --sortie <fichier.json>

Deux tâches : `stance` (un exemple par couple post, cible) et `emotion` (un exemple par post).
La découpe, les effectifs et les étiquettes viennent du code d'entraînement (`modele.entrainer`,
`modele.donnees`) : le script refuse un run dont les effectifs de validation diffèrent de
`metriques.json`.

Entrée des deux scoreurs : le texte nettoyé comme le job Spark (copie de `pii.nettoyer_texte`,
recopiée ici pour ne pas importer pyspark). Le scoreur à règles est `scoring.scorer` ; CamemBERT
passe par `Predicteur` sur CPU, 4 threads au plus.

Sortie : un JSON d'agrégats (comptes, métriques, matrices). Aucun texte de post, aucun identifiant
de post, ni sur la sortie standard ni dans le JSON. Les erreurs ne citent que des noms de champs
et des effectifs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "streaming"))
sys.path.insert(0, str(REPO / "src" / "training"))

import scoring  # noqa: E402  (src/streaming/scoring.py : lexique-v1)
from modele import donnees, entrainer, evaluation  # noqa: E402
from modele.predict import Predicteur  # noqa: E402

TACHES = ("stance", "emotion")
NON_EVALUE = "non_evalue"
THREADS = 4
TAILLE_LOT = 16
LEXIQUE = REPO / "ressources" / "lexique"

# Copie de src/streaming/pii.py (étape 2 du job Spark), sans l'import de pyspark.
_URL = re.compile(r"https?://\S+|\bwww\.\S+")
_HANDLE = re.compile(r"@[a-z0-9][a-z0-9._\-]*")
_DID = re.compile(r"\bdid:[a-z0-9]+:[a-z0-9._:%\-]*")
_ESPACES = re.compile(r"\s+")


def normaliser(texte: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def nettoyer_comme_job(texte: str | None) -> str:
    if not texte:
        return ""
    t = _URL.sub(" ", normaliser(texte))
    t = _DID.sub(" ", t)
    t = _HANDLE.sub(" ", t)
    return _ESPACES.sub(" ", t).strip()


# --------------------------------------------------------------------------- runs
def resoudre_run(arg: str, corpus: Path) -> Path:
    """Un chemin de run, ou un nom de run sous `<corpus>/modeles/`."""
    chemin = Path(arg).expanduser()
    if not chemin.is_dir():
        chemin = corpus / "modeles" / arg
    if not (chemin / "metriques.json").is_file():
        raise ValueError(f"run introuvable ou incomplet : {arg}")
    return chemin.resolve()


def lire_json(chemin: Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def exemples_validation(corpus: Path, run: Path, tache: str):
    """Exemples de validation du run, par la même découpe que l'entraînement.

    Retourne (exemples, modele.json, metriques.json). Refuse si la découpe ne correspond pas.
    """
    meta = lire_json(run / "modele.json")
    if meta["tache"] != tache:
        raise ValueError(f"le run {run.name} est une tâche {meta['tache']}, pas {tache}")
    config = lire_json(run / "config_entrainement.json")
    if config["part_validation"] != entrainer.PART_VALIDATION:
        raise ValueError("part de validation du run différente de celle de entrainer.py")
    metriques = lire_json(run / "metriques.json")
    _, val = entrainer.preparer_donnees(corpus, tache, config["graine"])
    if donnees.effectifs(val) != metriques["effectifs"]["validation"]:
        raise ValueError(f"effectifs de validation ({tache}) différents de metriques.json : arrêt")
    return val, meta, metriques


# --------------------------------------------------------------------------- prédictions
class ScoreurRegex:
    def __init__(self):
        self.lex = scoring.charger_lexique(str(LEXIQUE))

    def stance(self, texte: str, cible: str) -> str:
        for c in scoring.scorer(texte, self.lex)["cibles"]:
            if c["entite"] == cible:
                return c["stance"]
        return NON_EVALUE

    def emotion(self, texte: str) -> str:
        return scoring.scorer(texte, self.lex)["emotion"]


def predire_regex(exemples, tache: str, scoreur: ScoreurRegex) -> list[str]:
    if tache == "stance":
        return [scoreur.stance(nettoyer_comme_job(e.texte), e.cible) for e in exemples]
    return [scoreur.emotion(nettoyer_comme_job(e.texte)) for e in exemples]


def predire_camembert(predicteur: Predicteur, exemples, tache: str) -> list[str]:
    textes = [nettoyer_comme_job(e.texte) for e in exemples]
    cibles = [e.cible for e in exemples] if tache == "stance" else None
    proba = predicteur.probabilites(textes, cibles, taille_lot=TAILLE_LOT)
    return [predicteur.etiquettes[int(k)] for k in proba.argmax(axis=1)]


# --------------------------------------------------------------------------- métriques
def metriques(vrais: list[str], predits: list[str], etiquettes: list[str]) -> dict:
    """Métriques d'un scoreur sur des exemples. `non_evalue` compte comme erreur (pas de classe).

    `sur_couvert` : mêmes métriques sur les seuls exemples où le scoreur tranche.
    """
    n = len(vrais)
    couvert = [p != NON_EVALUE for p in predits]
    n_couvert = sum(couvert)
    classes_predites = etiquettes + [NON_EVALUE]
    sortie = {
        "n": n,
        "accuracy": round(evaluation.accuracy(vrais, predits), 4),
        "f1_macro": round(evaluation.f1_macro(vrais, predits, etiquettes), 4),
        "par_classe": evaluation.par_classe(vrais, predits, etiquettes),
        "matrice_confusion": {"lignes_vrai": etiquettes, "colonnes_predit": classes_predites,
                              "valeurs": evaluation.matrice_confusion(vrais, predits, classes_predites)},
        "couverture": round(n_couvert / n, 4),
    }
    if n_couvert:
        sv = [v for v, c in zip(vrais, couvert) if c]
        sp = [p for p, c in zip(predits, couvert) if c]
        classes = [e for e in etiquettes if e in set(sv) | set(sp)]
        sortie["sur_couvert"] = {"n": n_couvert,
                                 "accuracy": round(evaluation.accuracy(sv, sp), 4),
                                 "f1_macro": round(evaluation.f1_macro(sv, sp, classes), 4)}
    else:
        sortie["sur_couvert"] = {"n": 0, "accuracy": None, "f1_macro": None}
    return sortie


def verifier_etiquettes(predits: list[str], etiquettes: list[str], nom: str) -> None:
    hors = sorted(set(predits) - set(etiquettes) - {NON_EVALUE})
    if hors:
        raise ValueError(f"{nom} : étiquettes hors schéma {hors}")


def metriques_regex_silver(corpus: Path, tache: str, scoreur: ScoreurRegex) -> dict:
    """Regex seul sur tout le silver (aucun entraînement : pas de fuite possible)."""
    lignes = donnees.charger_lignes(corpus / "annotation" / "train_silver.jsonl", entrainer.SOURCE)
    donnees.verifier_garde_fou(lignes, corpus)
    exemples = donnees.construire_exemples(lignes, tache)
    etiquettes = donnees.etiquettes(tache)
    predits = predire_regex(exemples, tache, scoreur)
    verifier_etiquettes(predits, etiquettes, f"regex silver {tache}")
    return metriques([e.etiquette for e in exemples], predits, etiquettes)


def evaluer_tache(corpus: Path, run: Path, tache: str, scoreur: ScoreurRegex, predicteur: Predicteur) -> dict:
    val, meta, metriques_run = exemples_validation(corpus, run, tache)
    etiquettes = donnees.etiquettes(tache)
    if meta["etiquettes"] != etiquettes:
        raise ValueError(f"étiquettes du run {run.name} différentes du schéma")
    vrais = [e.etiquette for e in val]

    predits_regex = predire_regex(val, tache, scoreur)
    verifier_etiquettes(predits_regex, etiquettes, f"regex {tache}")
    predits_camembert = predire_camembert(predicteur, val, tache)

    resultat = {
        "effectifs_validation": donnees.effectifs(val),
        "exemples_texte_modifie_par_nettoyage": sum(
            nettoyer_comme_job(e.texte) != normaliser(e.texte) for e in val),
        "regex": metriques(vrais, predits_regex, etiquettes),
        "camembert": {
            **metriques(vrais, predits_camembert, etiquettes),
            "reference_metriques_json": {"accuracy": metriques_run["accuracy"],
                                         "f1_macro": metriques_run["f1_macro"]},
        },
        "regex_silver_complet": metriques_regex_silver(corpus, tache, scoreur),
    }
    if tache == "stance":
        resultat["cible_hors_lexique"] = sum(e.cible not in scoreur.lex.ids for e in val)
    return resultat


# --------------------------------------------------------------------------- CLI
def analyser_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="scripts/comparer_regex_modele.py", description=__doc__.split("\n")[0])
    p.add_argument("--corpus", required=True, help="dossier contenant annotation/ (et modeles/ si run par nom)")
    p.add_argument("--run-stance", required=True, help="dossier du run stance, ou son nom sous modeles/")
    p.add_argument("--run-emotion", required=True, help="dossier du run emotion, ou son nom sous modeles/")
    p.add_argument("--sortie", required=True, help="fichier JSON d'agrégats (hors dépôt)")
    return p.parse_args(argv)


def executer(args: argparse.Namespace) -> dict:
    debut = time.monotonic()
    corpus = Path(args.corpus).expanduser()
    runs = {"stance": resoudre_run(args.run_stance, corpus), "emotion": resoudre_run(args.run_emotion, corpus)}
    scoreur = ScoreurRegex()
    taches = {}
    for tache in TACHES:
        predicteur = Predicteur(runs[tache], threads=THREADS, appareil="cpu")
        taches[tache] = evaluer_tache(corpus, runs[tache], tache, scoreur, predicteur)
        del predicteur
    return {
        "genere_le": datetime.now().isoformat(timespec="minutes"),
        "scoreur": scoring.SCOREUR,
        "modeles": {t: runs[t].name for t in TACHES},
        "protocole": {"part_validation": entrainer.PART_VALIDATION, "entree": "texte nettoyé comme le job Spark",
                      "threads": THREADS, "appareil": "cpu"},
        "taches": taches,
        "duree_s": round(time.monotonic() - debut, 1),
    }


def resumer(sortie: dict) -> None:
    print(f"{'tache':<8} {'scoreur':<10} {'n':>5} {'accuracy':>9} {'F1 macro':>9} {'couverture':>11} "
          f"{'F1 couvert':>11}")
    for tache, bloc in sortie["taches"].items():
        for nom in ("regex", "camembert", "regex_silver_complet"):
            m = bloc[nom]
            f1c = m["sur_couvert"]["f1_macro"]
            print(f"{tache:<8} {nom:<10} {m['n']:>5} {m['accuracy']:>9.4f} {m['f1_macro']:>9.4f} "
                  f"{m['couverture']:>11.4f} {('-' if f1c is None else f'{f1c:.4f}'):>11}")


def main(argv: list[str] | None = None) -> int:
    args = analyser_arguments(argv)
    try:
        sortie = executer(args)
    except Exception as e:  # message seulement : jamais de trace, qui peut contenir des valeurs
        print(f"échec : {type(e).__name__} : {e}", file=sys.stderr)
        return 1
    chemin = Path(args.sortie).expanduser()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resumer(sortie)
    print(f"durée {sortie['duree_s']} s, agrégats écrits dans {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
