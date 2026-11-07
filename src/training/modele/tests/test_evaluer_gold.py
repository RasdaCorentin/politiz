"""Évaluation d'un run sur le gold : modèle minuscule, gold inventé."""
import json

import pytest
import torch

from modele import evaluer_gold
from modele.entrainer import analyser_arguments, executer
from modele.tests import outils


@pytest.fixture(scope="module")
def runs_gold(modele_minuscule, tmp_path_factory):
    """Runs stance, émotion à 7 classes et émotion à 3 classes, une époque chacun, et un gold inventé."""
    torch.set_num_threads(2)
    racine = tmp_path_factory.mktemp("runs-gold")
    corpus = outils.creer_corpus(racine / "corpus")
    sorties = {}
    for nom, extra in (("stance", ["--tache", "stance"]), ("emotion", ["--tache", "emotion"]),
                       ("emotion3", ["--tache", "emotion", "--emotion-3-classes"])):
        args = analyser_arguments([*extra, "--corpus", str(corpus), "--sortie", str(racine / nom),
                                   "--base", str(modele_minuscule), "--appareil", "cpu",
                                   "--longueur-max", "64", "--epoques", "1", "--lr", "3e-3"])
        sorties[nom] = executer(args)
    gold = racine / "gold.jsonl"
    outils.ecrire_jsonl(gold, outils.lignes_factices(40, prefixe="g", source="gold"))
    return sorties, gold


def _lancer(run, gold, *extra):
    return evaluer_gold.main(["--run", str(run), "--gold", str(gold), *extra])


def test_wilson():
    assert evaluer_gold.wilson(0, 0) == [0.0, 0.0]
    bas, haut = evaluer_gold.wilson(13, 26)
    assert bas == pytest.approx(0.321, abs=1e-3) and haut == pytest.approx(0.679, abs=1e-3)


def test_stance_et_emotion_ecrivent_des_agregats(runs_gold, tmp_path, capsys):
    sorties, gold = runs_gold
    for nom in ("stance", "emotion"):
        sortie = tmp_path / f"{nom}.json"
        assert _lancer(sorties[nom], gold, "--sortie", str(sortie)) == 0
        r = json.loads(sortie.read_text())
        assert r["tache"] == nom.rstrip("3") and r["n"] > 0
        assert 0 <= r["accuracy"] <= 1 and len(r["accuracy_ic95"]) == 2
        assert sum(r["effectifs_gold"].values()) == r["n"]
        assert 0 <= r["rappel_macro"] <= 1 and set(r["rappel_ic95"]) == set(r["effectifs_gold"])
    sortie_ecran = capsys.readouterr().out
    assert outils.SENTINELLE not in sortie_ecran and "g00" not in sortie_ecran


def test_run_a_3_emotions_projette_le_gold(runs_gold, tmp_path):
    sorties, gold = runs_gold
    sortie = tmp_path / "e3.json"
    assert _lancer(sorties["emotion3"], gold, "--sortie", str(sortie)) == 0
    r = json.loads(sortie.read_text())
    assert set(r["effectifs_gold"]) <= {"joie", "colere", "neutre"}
    assert r["etiquettes"] == ["joie", "colere", "neutre"] and not r["projection_3_classes"]


def test_projection_d_un_run_a_7_emotions(runs_gold, tmp_path):
    sorties, gold = runs_gold
    sortie = tmp_path / "e7p.json"
    assert _lancer(sorties["emotion"], gold, "--emotion-3-classes", "--sortie", str(sortie)) == 0
    r = json.loads(sortie.read_text())
    assert r["projection_3_classes"] and r["etiquettes"] == ["joie", "colere", "neutre"]
    assert set(r["effectifs_gold"]) <= {"joie", "colere", "neutre"}


def test_erreurs(runs_gold, tmp_path, capsys):
    sorties, gold = runs_gold
    assert _lancer(sorties["stance"], gold, "--emotion-3-classes") == 1
    vide = tmp_path / "vide.jsonl"
    vide.write_text("")
    assert _lancer(sorties["emotion"], vide) == 1
    silver = tmp_path / "silver.jsonl"
    outils.ecrire_jsonl(silver, outils.lignes_factices(5))
    assert _lancer(sorties["emotion"], silver) == 1
    assert "erreur" in capsys.readouterr().err


def test_reference_silver(runs_gold, tmp_path):
    sorties, _ = runs_gold
    silver = tmp_path / "silver.jsonl"
    outils.ecrire_jsonl(silver, outils.lignes_factices(30))
    sortie = tmp_path / "s.json"
    assert _lancer(sorties["emotion"], silver, "--reference", "silver", "--sortie", str(sortie)) == 0
    r = json.loads(sortie.read_text())
    assert r["reference"] == "silver" and "LLM" in r["mention"]
