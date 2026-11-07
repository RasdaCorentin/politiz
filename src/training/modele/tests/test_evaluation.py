"""Tests de evaluation.py sur des valeurs calculées à la main (étiquettes inventées)."""
import pytest

from modele import evaluation

ETIQ = ["a", "b", "c"]
VRAIS = ["a", "a", "b", "b", "c"]
PREDITS = ["a", "b", "b", "b", "a"]


def test_accuracy():
    assert evaluation.accuracy(VRAIS, PREDITS) == pytest.approx(0.6)


def test_f1_macro_moyenne_des_classes():
    # F1 : a = 0,5 ; b = 0,8 ; c = 0 (classe jamais prédite) -> moyenne 0,4333
    assert evaluation.f1_macro(VRAIS, PREDITS, ETIQ) == pytest.approx((0.5 + 0.8 + 0.0) / 3)


def test_par_classe_precision_rappel_f1_support():
    pc = evaluation.par_classe(VRAIS, PREDITS, ETIQ)
    assert list(pc) == ETIQ
    assert pc["a"] == {"precision": 0.5, "rappel": 0.5, "f1": 0.5, "support": 2}
    assert pc["b"] == {"precision": 0.6667, "rappel": 1.0, "f1": 0.8, "support": 2}
    assert pc["c"] == {"precision": 0.0, "rappel": 0.0, "f1": 0.0, "support": 1}


def test_matrice_de_confusion_lignes_vraies_colonnes_predites():
    assert evaluation.matrice_confusion(VRAIS, PREDITS, ETIQ) == [[1, 1, 0], [0, 2, 0], [1, 0, 0]]


def test_classe_absente_ne_plante_pas():
    # « d » n'apparaît nulle part : précision, rappel et F1 à 0, support à 0, pas d'erreur.
    pc = evaluation.par_classe(VRAIS, PREDITS, ETIQ + ["d"])
    assert pc["d"] == {"precision": 0.0, "rappel": 0.0, "f1": 0.0, "support": 0}


def test_resume_contient_les_quatre_blocs():
    r = evaluation.resume(VRAIS, PREDITS, ETIQ)
    assert set(r) == {"accuracy", "f1_macro", "rappel_macro", "par_classe", "matrice_confusion"}
    assert r["accuracy"] == 0.6


def test_entrees_incoherentes_refusees():
    with pytest.raises(ValueError, match="prédictions"):
        evaluation.accuracy(["a"], ["a", "b"])
    with pytest.raises(ValueError, match="aucune"):
        evaluation.f1_macro([], [], ETIQ)


def test_rappel_macro_ignore_les_classes_sans_exemple_et_penalise_la_majoritaire():
    # tout prédire « a » : rappel 1 sur a, 0 sur b -> 0,5 ; la classe c, absente du vrai, ne compte pas
    assert evaluation.rappel_macro(["a", "a", "a", "b"], ["a", "a", "a", "a"], ["a", "b", "c"]) == pytest.approx(0.5)
    assert evaluation.rappel_macro(VRAIS, PREDITS, ETIQ) == pytest.approx((0.5 + 1.0 + 0.0) / 3)
