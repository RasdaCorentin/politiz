"""Silver du nouveau corpus : conversion et passage dans l'export. Données inventées."""
import json

import pytest

from annotation import export, silver_nouveau
from annotation.tests.test_storage_export import OK, _corpus_silver


def _ecrire(adir, etiquettes, echantillon):
    src = adir / "silver" / "nouveau"
    src.mkdir(parents=True, exist_ok=True)
    (src / "final-contexte.jsonl").write_text("".join(json.dumps(r) + "\n" for r in etiquettes))
    (src / "echantillon-800.json").write_text(json.dumps(echantillon))


def test_identifiant():
    assert silver_nouveau.identifiant("d42") == "nouveau:42"
    for mauvais in ("42", "x42", "d", "d4a"):
        with pytest.raises(ValueError):
            silver_nouveau.identifiant(mauvais)


def test_convertir_ecarte_les_posts_sans_texte():
    labels, posts, st = silver_nouveau.convertir(
        [{**OK, "post_id": "d1"}, {**OK, "post_id": "d2"}], [[1, "texte inventé un"]])
    assert [r["post_id"] for r in labels] == ["nouveau:1"]
    assert posts == [{"post_id": "nouveau:1", "text": "texte inventé un"}]
    assert st == {"etiquettes": 2, "sans_texte": 1, "ecrits": 1}


def test_main_refuse_d_ecraser(tmp_path):
    adir = _corpus_silver(tmp_path)
    _ecrire(adir, [{**OK, "post_id": "d1"}], [[1, "texte inventé"]])
    silver_nouveau.main(["--corpus-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        silver_nouveau.main(["--corpus-dir", str(tmp_path)])


def test_export_avec_textes_ajoute_le_nouveau_et_exclut_son_gold(tmp_path):
    adir = _corpus_silver(tmp_path)
    _ecrire(adir, [{**OK, "post_id": "d1"}, {**OK, "post_id": "d2"}], [[1, "texte un"], [2, "texte deux"]])
    silver_nouveau.main(["--corpus-dir", str(tmp_path)])
    # nouveau:2 est annoté à la main : il reste hors de train_silver
    (adir / "annotations" / "a.jsonl").write_text(json.dumps({**OK, "post_id": "nouveau:2"}) + "\n")
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    export.main(["--corpus-dir", str(tmp_path), "--silver"])
    sans = [json.loads(l)["post_id"] for l in (adir / "train_silver.jsonl").read_text().splitlines()]
    assert "nouveau:1" not in sans
    export.main(["--corpus-dir", str(tmp_path), "--silver",
                 "--textes", str(adir / "lots" / "textes_nouveau.jsonl")])
    rows = [json.loads(l) for l in (adir / "train_silver.jsonl").read_text().splitlines()]
    ids = [r["post_id"] for r in rows]
    assert "nouveau:1" in ids and "nouveau:2" not in ids
    assert next(r["text"] for r in rows if r["post_id"] == "nouveau:1") == "texte un"


def test_export_textes_absent_refuse_et_doublon_garde_le_premier(tmp_path):
    adir = _corpus_silver(tmp_path)
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    with pytest.raises(SystemExit):
        export.main(["--corpus-dir", str(tmp_path), "--silver", "--textes", str(tmp_path / "absent.jsonl")])
    double = tmp_path / "double.jsonl"
    double.write_text(json.dumps({"post_id": "a2", "texte": "autre"}) + "\n"
                      + json.dumps({"post_id": "n9", "texte": "neuf"}) + "\n")
    (adir / "silver" / "final" / "n.jsonl").write_text(json.dumps({**OK, "post_id": "n9"}) + "\n")
    export.main(["--corpus-dir", str(tmp_path), "--silver", "--textes", str(double)])
    rows = {json.loads(l)["post_id"]: json.loads(l) for l in (adir / "train_silver.jsonl").read_text().splitlines()}
    assert rows["a2"]["text"] == "texte a2" and rows["n9"]["text"] == "neuf"
