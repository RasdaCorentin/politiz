"""Projection mention -> neutre : fonctions pures, et option --stance-regroupe-neutre de l'export.

Données inventées ; aucun texte réel.
"""
import copy
import json

from annotation import export
from projection_stance import regrouper_cibles, regrouper_etiquettes, regrouper_lignes, regrouper_stance

OK = {"pertinent": "oui", "emotion": "colere", "ironie": "non", "regle_suffit": "non", "themes": ["economie"]}


def test_mention_et_neutre_deviennent_neutre():
    assert regrouper_stance("mention") == "neutre"
    assert regrouper_stance("neutre") == "neutre"


def test_autres_classes_intactes():
    for st in ("pour", "contre", "ambigu", None):
        assert regrouper_stance(st) == st


def test_projection_des_cibles_sans_modifier_l_origine():
    cibles = [{"entite": "le pen", "stance": "mention"}, {"entite": "gouvernement", "stance": "contre"},
              {"entite": "lfi", "stance": "neutre"}]
    avant = copy.deepcopy(cibles)
    sortie = regrouper_cibles(cibles)
    assert [c["stance"] for c in sortie] == ["neutre", "contre", "neutre"]
    assert [c["entite"] for c in sortie] == ["le pen", "gouvernement", "lfi"]
    assert cibles == avant                       # l'entrée n'est pas modifiée
    assert sortie[0] is not cibles[0]            # ni ses dictionnaires


def test_projection_des_lignes_sans_modifier_l_origine():
    lignes = [{"post_id": "1", "cibles": [{"entite": "lfi", "stance": "mention"}]},
              {"post_id": "2", "cibles": None}]
    avant = copy.deepcopy(lignes)
    sortie = regrouper_lignes(lignes)
    assert sortie[0]["cibles"] == [{"entite": "lfi", "stance": "neutre"}]
    assert sortie[1]["cibles"] is None           # une ligne sans cibles reste sans cibles
    assert lignes == avant


def test_etiquettes_fusionnees_gardent_l_ordre_et_l_entree():
    liste = ["pour", "contre", "neutre", "mention", "ambigu"]
    assert regrouper_etiquettes(liste) == ["pour", "contre", "neutre", "ambigu"]
    assert liste == ["pour", "contre", "neutre", "mention", "ambigu"]


def _corpus(tmp_path):
    adir = tmp_path / "annotation"
    for d in ("lots", "annotations", "silver/final"):
        (adir / d).mkdir(parents=True)
    (adir / "lots" / "lot_eval.jsonl").write_text(json.dumps({"post_id": "e1", "text": "texte e1"}) + "\n")
    (adir / "lots" / "lot_01.jsonl").write_text(
        "".join(json.dumps({"post_id": i, "text": f"texte {i}"}) + "\n" for i in ["g1", "s1"]))
    (adir / "lots" / "corpus_propre.jsonl").write_text(
        "".join(json.dumps({"post_id": i, "text": f"texte {i}"}) + "\n" for i in ["e1", "g1", "s1"]))
    # gold : g1 en train (neutre), e1 en évaluation (mention)
    (adir / "annotations" / "a.jsonl").write_text(
        json.dumps({**OK, "post_id": "g1", "cibles": [{"entite": "le pen", "stance": "neutre"}]}) + "\n"
        + json.dumps({**OK, "post_id": "e1", "cibles": [{"entite": "le pen", "stance": "mention"}]}) + "\n")
    # silver : s1 avec une mention et un neutre
    (adir / "silver" / "final" / "x.jsonl").write_text(json.dumps(
        {**OK, "post_id": "s1", "cibles": [{"entite": "le pen", "stance": "mention"},
                                           {"entite": "gouvernement", "stance": "neutre"}]}) + "\n")
    return adir


def _lignes(chemin):
    return [json.loads(l) for l in chemin.read_text(encoding="utf-8").splitlines()]


def test_export_sans_option_garde_mention(tmp_path):
    adir = _corpus(tmp_path)
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    export.main(["--corpus-dir", str(tmp_path), "--silver"])
    silver = _lignes(adir / "train_silver.jsonl")
    assert [c["stance"] for c in silver[0]["cibles"]] == ["mention", "neutre"]
    assert [c["stance"] for c in _lignes(adir / "eval.jsonl")[0]["cibles"]] == ["mention"]


def test_export_avec_option_fusionne_dans_les_trois_sorties(tmp_path):
    adir = _corpus(tmp_path)
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    source_avant = (adir / "silver" / "final" / "x.jsonl").read_text(encoding="utf-8")
    export.main(["--corpus-dir", str(tmp_path), "--silver", "--stance-regroupe-neutre"])
    silver = _lignes(adir / "train_silver.jsonl")
    assert [c["stance"] for c in silver[0]["cibles"]] == ["neutre", "neutre"]
    assert [c["stance"] for c in _lignes(adir / "train.jsonl")[0]["cibles"]] == ["neutre"]
    assert [c["stance"] for c in _lignes(adir / "eval.jsonl")[0]["cibles"]] == ["neutre"]
    assert (adir / "silver" / "final" / "x.jsonl").read_text(encoding="utf-8") == source_avant   # étiquettes d'origine intactes
