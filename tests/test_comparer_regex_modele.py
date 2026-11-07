"""Tests de scripts/comparer_regex_modele.py sur un corpus et des runs inventés.

Lancer : uv run --python 3.12 --no-project --extra-index-url https://download.pytorch.org/whl/cpu \
    --with-requirements src/training/requirements-train.txt --with pandas \
    python -m pytest -q tests/test_comparer_regex_modele.py

Tous les textes sont inventés (mots-marqueurs de modele.tests.outils). Le modèle est minuscule
et construit hors dépôt. Les runs sont produits par la vraie CLI d'entraînement.
"""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("comparer_regex_modele", REPO / "scripts" / "comparer_regex_modele.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)  # ajoute src/streaming et src/training à sys.path

from modele import donnees, entrainer  # noqa: E402
from modele.tests import outils  # noqa: E402

NE = C.NON_EVALUE
ETIQ_STANCE = ["pour", "contre", "neutre", "mention", "ambigu"]


@pytest.fixture(scope="module")
def monde(tmp_path_factory):
    """Corpus factice, un run stance et un run emotion (une époque, CPU) dans corpus/modeles."""
    torch.set_num_threads(2)
    racine = tmp_path_factory.mktemp("comparaison")
    corpus = outils.creer_corpus(racine / "corpus")
    base = outils.creer_modele_minuscule(racine / "tiny")
    for tache in ("stance", "emotion"):
        args = entrainer.analyser_arguments(
            ["--tache", tache, "--corpus", str(corpus), "--sortie", str(corpus / "modeles"),
             "--base", str(base), "--appareil", "cpu", "--longueur-max", "64",
             "--epoques", "1", "--lr", "3e-3"])
        entrainer.executer(args)
    return corpus


def run_de(corpus: Path, tache: str) -> Path:
    return next((corpus / "modeles").glob(f"{tache}-*"))


# --- nettoyage : copie de pii.nettoyer_texte ----------------------------------------
def test_nettoyage_comme_le_job():
    brut = "Bravo À Toi @alice.bsky https://ex.fr/a?b=1 fin did:plc:abc123"
    assert C.nettoyer_comme_job(brut) == "bravo a toi fin"
    assert C.nettoyer_comme_job(None) == ""


# --- découpe : même fonction que l'entraînement -----------------------------------------
def test_decoupe_identique_a_l_entrainement(monde):
    run = run_de(monde, "stance")
    val, meta, metriques = C.exemples_validation(monde, run, "stance")
    _, val_entrainement = entrainer.preparer_donnees(monde, "stance", 2027)
    assert [(e.post_id, e.cible, e.etiquette) for e in val] == \
        [(e.post_id, e.cible, e.etiquette) for e in val_entrainement]
    assert donnees.effectifs(val) == metriques["effectifs"]["validation"]
    assert meta["tache"] == "stance"


def test_aucun_post_des_deux_cotes_de_la_decoupe(monde):
    lignes = donnees.charger_lignes(monde / "annotation" / "train_silver.jsonl")
    exemples = donnees.construire_exemples(lignes, "stance")
    train, val = donnees.decouper(exemples, entrainer.PART_VALIDATION, 2027)
    assert not {e.post_id for e in train} & {e.post_id for e in val}


def test_refus_si_effectifs_diffèrent(monde, tmp_path):
    copie = tmp_path / "stance-copie"
    shutil.copytree(run_de(monde, "stance"), copie)
    chemin = copie / "metriques.json"
    data = json.loads(chemin.read_text(encoding="utf-8"))
    data["effectifs"]["validation"]["contre"] += 1
    chemin.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="effectifs"):
        C.exemples_validation(monde, copie, "stance")


def test_refus_si_tache_du_run_differe(monde):
    with pytest.raises(ValueError, match="tâche"):
        C.exemples_validation(monde, run_de(monde, "stance"), "emotion")


# --- alignement et abstention ------------------------------------------------------------
def test_alignement_et_non_evalue(monkeypatch):
    def faux_scorer(texte, lex=None):
        cibles = [{"entite": "melenchon", "stance": "pour", "confiance": "haute"}] if "alpha" in texte else []
        return {"cibles": cibles, "sentiment": "neutre", "emotion": "joie", "themes": ["autre"]}

    monkeypatch.setattr(C.scoring, "scorer", faux_scorer)
    scoreur = C.ScoreurRegex()
    exemples = [
        donnees.Exemple("p1", "alpha x", "melenchon", "pour"),   # cible détectée
        donnees.Exemple("p2", "alpha y", "lfi", "contre"),       # texte déclencheur, autre cible : abstention
        donnees.Exemple("p3", "beta z", "melenchon", "neutre"),  # rien détecté : abstention
    ]
    assert C.predire_regex(exemples, "stance", scoreur) == ["pour", NE, NE]


def test_metriques_non_evalue_compte_comme_erreur():
    vrais = ["pour", "pour", "contre"]
    predits = ["pour", NE, "contre"]
    m = C.metriques(vrais, predits, ["pour", "contre", "neutre"])
    assert m["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["couverture"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["par_classe"]["pour"]["rappel"] == 0.5
    assert m["sur_couvert"] == {"n": 2, "accuracy": 1.0, "f1_macro": 1.0}
    assert m["matrice_confusion"]["colonnes_predit"][-1] == NE


def test_aucune_couverture_pas_de_division():
    m = C.metriques(["pour"], [NE], ["pour", "contre"])
    assert m["couverture"] == 0.0
    assert m["sur_couvert"] == {"n": 0, "accuracy": None, "f1_macro": None}


def test_etiquette_hors_schema_refusee():
    with pytest.raises(ValueError, match="hors schéma"):
        C.verifier_etiquettes(["pour", "inventee"], ETIQ_STANCE, "test")


# --- bout en bout : aucune donnée de post dans la sortie -----------------------------------
def test_sortie_sans_texte_ni_identifiant(monde, tmp_path, capsys):
    sortie = tmp_path / "agregats.json"
    code = C.main(["--corpus", str(monde), "--run-stance", run_de(monde, "stance").name,
                   "--run-emotion", run_de(monde, "emotion").name, "--sortie", str(sortie)])
    assert code == 0
    texte_json = sortie.read_text(encoding="utf-8")
    affiche = capsys.readouterr().out
    donnees_brutes = donnees.charger_lignes(monde / "annotation" / "train_silver.jsonl")
    for ligne in donnees_brutes:
        assert ligne["text"] not in texte_json
        assert ligne["text"] not in affiche
        assert str(ligne["post_id"]) not in texte_json
    assert outils.SENTINELLE not in texte_json
    assert outils.SENTINELLE not in affiche

    data = json.loads(texte_json)
    for tache in ("stance", "emotion"):
        bloc = data["taches"][tache]
        assert bloc["regex"]["n"] == bloc["camembert"]["n"] == sum(bloc["effectifs_validation"].values())
        assert bloc["regex_silver_complet"]["n"] > 0
    assert "cible_hors_lexique" in data["taches"]["stance"]
