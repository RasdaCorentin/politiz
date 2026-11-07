"""Tests de la CLI d'entraînement : un run complet sur CPU, modèle minuscule, corpus inventé.

La CLI tourne dans un sous-processus (comme la machine GPU l'appelle), avec 2 threads.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from modele import donnees, entrainer
from modele.tests import outils

SRC_TRAINING = Path(__file__).resolve().parents[2]
ENV = {**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"}


def lancer(corpus: Path, sortie: Path, base: Path, tache: str, *extra: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "modele.entrainer", "--tache", tache, "--corpus", str(corpus),
           "--sortie", str(sortie), "--base", str(base), "--appareil", "cpu",
           "--longueur-max", "64", "--lot", "16", *extra]
    return subprocess.run(cmd, cwd=SRC_TRAINING, env=ENV, capture_output=True, text=True, timeout=300)


def textes_du_corpus(corpus: Path) -> list[str]:
    lignes = (corpus / "annotation" / "train_silver.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l)["text"] for l in lignes if l.strip()]


def test_run_stance_de_bout_en_bout(corpus, modele_minuscule, tmp_path):
    sortie = tmp_path / "runs"
    # Taux d'apprentissage relevé : sur un modèle minuscule, le lr par défaut n'apprend rien en 3 époques.
    res = lancer(corpus, sortie, modele_minuscule, "stance", "--epoques", "3", "--lr", "3e-3")
    assert res.returncode == 0, res.stderr[-2000:]

    # Dernière ligne de stdout : chemin absolu du run, dans <sortie>/stance-AAAAMMJJ-HHMM/.
    lignes = res.stdout.strip().splitlines()
    run = Path(lignes[-1])
    assert run.is_absolute() and run.is_dir()
    assert run.parent == sortie.resolve()
    assert re.fullmatch(r"stance-\d{8}-\d{4}", run.name)

    # Dossier du run.
    assert (run / "model" / "config.json").is_file()
    assert (run / "model" / "tokenizer.json").is_file()
    assert any((run / "model").glob("*.safetensors"))
    for nom in ("modele.json", "metriques.json", "config_entrainement.json"):
        assert (run / nom).is_file()

    # modele.json : étiquettes dans l'ordre du schéma, gabarit d'entrée, noms de cibles.
    meta = json.loads((run / "modele.json").read_text(encoding="utf-8"))
    assert meta["tache"] == "stance"
    assert meta["etiquettes"] == ["pour", "contre", "neutre", "mention", "ambigu"]
    assert meta["entree"] == {"longueur_max": 64, "normaliser": True, "nettoyer": True}
    assert meta["noms_cibles"] == donnees.noms_cibles()           # nom du lexique, tel quel

    # metriques.json : champs du contrat, source silver, mention.
    met = json.loads((run / "metriques.json").read_text(encoding="utf-8"))
    for champ in ("accuracy", "f1_macro", "par_classe", "matrice_confusion", "effectifs", "duree_s", "materiel"):
        assert champ in met
    assert met["source"] == "silver" and "test de fumée" in met["mention"]
    assert set(met["par_classe"]) == set(meta["etiquettes"])
    assert set(met["par_classe"]["pour"]) == {"precision", "rappel", "f1", "support"}
    assert len(met["matrice_confusion"]) == 5 and all(len(r) == 5 for r in met["matrice_confusion"])
    assert 0.0 <= met["accuracy"] <= 1.0 and 0.0 <= met["f1_macro"] <= 1.0
    assert met["epoque_retenue"] in (1, 2, 3)
    # La boucle apprend : la perte d'entraînement baisse entre la première et la dernière époque.
    perte = [h["perte_entrainement"] for h in met["historique"]]
    assert len(perte) == 3 and perte[-1] < perte[0]

    # config_entrainement.json : hyperparamètres, graine, versions.
    conf = json.loads((run / "config_entrainement.json").read_text(encoding="utf-8"))
    assert conf["graine"] == 2027 and conf["epoques"] == 3 and conf["lot"] == 16
    assert conf["longueur_max"] == 64 and conf["versions"]["torch"]

    # Aucun texte du corpus dans les JSON, ni dans stderr, ni dans stdout.
    sorties = [(run / n).read_text(encoding="utf-8") for n in
               ("modele.json", "metriques.json", "config_entrainement.json")]
    sorties += [res.stderr, res.stdout]
    for texte in textes_du_corpus(corpus):
        for s in sorties:
            assert texte not in s
    assert outils.SENTINELLE not in "".join(sorties)
    assert "[entrainement]" in res.stderr                       # la progression existe


def test_run_emotion_et_refus_du_garde_fou(corpus, modele_minuscule, tmp_path):
    res = lancer(corpus, tmp_path / "runs", modele_minuscule, "emotion", "--epoques", "1")
    assert res.returncode == 0, res.stderr[-2000:]
    run = Path(res.stdout.strip().splitlines()[-1])
    meta = json.loads((run / "modele.json").read_text(encoding="utf-8"))
    assert meta["etiquettes"] == ["joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre"]
    assert meta["noms_cibles"] == {}
    assert json.loads((run / "metriques.json").read_text(encoding="utf-8"))["source"] == "silver"


def test_echec_sans_fichier_fige_code_non_nul_et_pas_de_run(corpus, modele_minuscule, tmp_path):
    (corpus / "annotation" / "eval_fige.json").unlink()
    sortie = tmp_path / "runs"
    res = lancer(corpus, sortie, modele_minuscule, "stance", "--epoques", "1")
    assert res.returncode != 0
    assert "eval_fige" in res.stderr
    assert res.stdout.strip() == ""
    assert not sortie.exists() or not any(sortie.iterdir())


def test_echec_tache_inconnue(corpus, modele_minuscule, tmp_path):
    res = lancer(corpus, tmp_path / "runs", modele_minuscule, "sentiment")
    assert res.returncode != 0


def test_option_regroupement_reservee_a_la_stance():
    base = ["--corpus", "c", "--sortie", "s"]
    assert entrainer.analyser_arguments(["--tache", "stance", *base, "--stance-regroupe-neutre"]).stance_regroupe_neutre
    assert not entrainer.analyser_arguments(["--tache", "stance", *base]).stance_regroupe_neutre
    with pytest.raises(SystemExit):
        entrainer.analyser_arguments(["--tache", "emotion", *base, "--stance-regroupe-neutre"])


def test_preparer_donnees_regroupe_sans_entrainer(corpus):
    train, val = entrainer.preparer_donnees(corpus, "stance", 2027, regroupe=True)
    assert {e.etiquette for e in train + val} <= {"pour", "contre", "neutre", "ambigu"}
    train0, val0 = entrainer.preparer_donnees(corpus, "stance", 2027)
    assert "mention" in {e.etiquette for e in train0 + val0}


def test_option_trois_classes_reservee_a_l_emotion():
    base = ["--corpus", "c", "--sortie", "s"]
    assert entrainer.analyser_arguments(["--tache", "emotion", *base, "--emotion-3-classes"]).emotion_3_classes
    assert not entrainer.analyser_arguments(["--tache", "emotion", *base]).emotion_3_classes
    with pytest.raises(SystemExit):
        entrainer.analyser_arguments(["--tache", "stance", *base, "--emotion-3-classes"])


def test_run_emotion_trois_classes_de_bout_en_bout(corpus, modele_minuscule, tmp_path):
    res = lancer(corpus, tmp_path / "runs", modele_minuscule, "emotion", "--epoques", "1", "--emotion-3-classes")
    assert res.returncode == 0, res.stderr[-2000:]
    run = Path(res.stdout.strip().splitlines()[-1])
    meta = json.loads((run / "modele.json").read_text(encoding="utf-8"))
    assert meta["etiquettes"] == ["joie", "colere", "neutre"]
    met = json.loads((run / "metriques.json").read_text(encoding="utf-8"))
    assert set(met["par_classe"]) == {"joie", "colere", "neutre"}
    conf = json.loads((run / "config_entrainement.json").read_text(encoding="utf-8"))
    assert conf["emotion_3_classes"] is True


def test_critere_et_alpha_poids_valides_et_ecrits(tmp_path):
    from modele.entrainer import analyser_arguments
    base = ["--tache", "emotion", "--corpus", str(tmp_path), "--sortie", str(tmp_path)]
    a = analyser_arguments(base)
    assert a.critere == "f1_macro" and a.alpha_poids == 0.5
    a = analyser_arguments([*base, "--critere", "rappel_macro", "--alpha-poids", "1"])
    assert a.critere == "rappel_macro" and a.alpha_poids == 1.0
    for mauvais in (["--critere", "accuracy"], ["--alpha-poids", "-1"], ["--alpha-poids", "3"]):
        with pytest.raises(SystemExit):
            analyser_arguments([*base, *mauvais])


def test_avec_gold_accepte_le_gold_sans_option_le_refuse(tmp_path):
    from modele.entrainer import preparer_donnees
    corpus = outils.creer_corpus(tmp_path / "c")
    lignes = outils.lignes_factices(40, "s") + outils.lignes_factices(20, "g", source="gold")
    outils.ecrire_jsonl(corpus / "annotation" / "train_silver.jsonl", lignes)
    with pytest.raises(ValueError, match="source"):
        preparer_donnees(corpus, "emotion", 2027)
    train, val = preparer_donnees(corpus, "emotion", 2027, avec_gold=True)
    assert {e.post_id[0] for e in train + val} == {"s", "g"}
