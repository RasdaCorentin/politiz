"""Métriques d'évaluation : fonctions pures sur des étiquettes (chaînes).

Toutes les fonctions reçoivent les étiquettes vraies, les étiquettes prédites et la liste ordonnée
des classes. Une classe sans exemple ni prédiction vaut 0 (pas d'erreur de division).
Aucun texte n'entre ici : seules des étiquettes et des effectifs.
"""
from __future__ import annotations

from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support,
                             recall_score)


def _verifier(vrais: list[str], predits: list[str]) -> None:
    if len(vrais) != len(predits):
        raise ValueError(f"{len(vrais)} étiquettes vraies pour {len(predits)} prédictions")
    if not vrais:
        raise ValueError("aucune étiquette à évaluer")


def accuracy(vrais: list[str], predits: list[str]) -> float:
    _verifier(vrais, predits)
    return float(accuracy_score(vrais, predits))


def f1_macro(vrais: list[str], predits: list[str], etiquettes: list[str]) -> float:
    """Moyenne non pondérée des F1 par classe. Une classe absente compte pour 0."""
    _verifier(vrais, predits)
    return float(f1_score(vrais, predits, labels=etiquettes, average="macro", zero_division=0))


def rappel_macro(vrais: list[str], predits: list[str], etiquettes: list[str]) -> float:
    """Moyenne non pondérée des rappels par classe (exactitude équilibrée si toutes les classes ont
    des exemples). Une classe qui écrase les autres ne la fait pas monter : chaque classe pèse autant."""
    _verifier(vrais, predits)
    presentes = [e for e in etiquettes if e in set(vrais)]
    return float(recall_score(vrais, predits, labels=presentes, average="macro", zero_division=0))


def par_classe(vrais: list[str], predits: list[str], etiquettes: list[str]) -> dict[str, dict]:
    """{étiquette: {precision, rappel, f1, support}}, arrondis à 4 décimales, dans l'ordre donné."""
    _verifier(vrais, predits)
    precision, rappel, f1, support = precision_recall_fscore_support(
        vrais, predits, labels=etiquettes, zero_division=0)
    return {
        e: {"precision": round(float(precision[i]), 4), "rappel": round(float(rappel[i]), 4),
            "f1": round(float(f1[i]), 4), "support": int(support[i])}
        for i, e in enumerate(etiquettes)
    }


def matrice_confusion(vrais: list[str], predits: list[str], etiquettes: list[str]) -> list[list[int]]:
    """Lignes : étiquette vraie ; colonnes : étiquette prédite ; ordre des `etiquettes`."""
    _verifier(vrais, predits)
    return confusion_matrix(vrais, predits, labels=etiquettes).tolist()


def resume(vrais: list[str], predits: list[str], etiquettes: list[str]) -> dict:
    """Le bloc de métriques de metriques.json, sans les champs de source (ajoutés par l'entraînement)."""
    return {
        "accuracy": round(accuracy(vrais, predits), 4),
        "f1_macro": round(f1_macro(vrais, predits, etiquettes), 4),
        "rappel_macro": round(rappel_macro(vrais, predits, etiquettes), 4),
        "par_classe": par_classe(vrais, predits, etiquettes),
        "matrice_confusion": matrice_confusion(vrais, predits, etiquettes),
    }
