import json

import pytest

from annotation import export
from annotation.common import load_schema
from annotation.storage import (annotations_path, clean, first_unannotated, load_annotations,
                                save_annotation, slug, validate)

SCHEMA = load_schema()
ENT = ["le pen", "gouvernement", "groupe-politique", "autre"]
OK = {"post_id": "1", "lot": "l", "annotateur": "a", "pertinent": "oui", "emotion": "colere", "ironie": "non",
      "regle_suffit": "non", "themes": ["economie"], "cibles": [{"entite": "le pen", "stance": "contre"}]}


def test_validation():
    assert validate(OK, SCHEMA, ENT) == []
    assert validate({**OK, "emotion": "rage"}, SCHEMA, ENT)
    assert validate({**OK, "cibles": [{"entite": "inconnu", "stance": "pour"}]}, SCHEMA, ENT)
    assert validate({**OK, "cibles": [{"entite": "le pen", "stance": None}]}, SCHEMA, ENT)
    assert validate({"post_id": "1"}, SCHEMA, ENT)


def test_non_vide_les_autres_champs():
    r = clean({**OK, "pertinent": "non"})
    assert r["cibles"] == [] and r["emotion"] is None and validate(r, SCHEMA, ENT) == []


def test_sauvegarde_append_et_derniere_version_gagne(tmp_path):
    p = annotations_path(tmp_path, "Léa Dupont")
    assert p.name == "lea-dupont.jsonl" or p.name == "l-a-dupont.jsonl"
    save_annotation(p, OK, SCHEMA, ENT)
    save_annotation(p, {**OK, "emotion": "peur"}, SCHEMA, ENT)
    assert len(p.read_text().splitlines()) == 2
    assert load_annotations(p)["1"]["emotion"] == "peur"
    with pytest.raises(ValueError):
        save_annotation(p, {**OK, "emotion": None}, SCHEMA, ENT)


def test_ligne_tronquee_ignoree(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps(OK) + '\n{"post_id": "2", "pert', encoding="utf-8")
    assert list(load_annotations(p)) == ["1"]


def test_reprise_premier_non_annote():
    posts = [{"post_id": str(i)} for i in range(4)]
    assert first_unannotated(posts, {"0": {}, "1": {}}) == 2
    assert first_unannotated(posts, {str(i): {} for i in range(4)}) == 4


def test_slug_vide():
    with pytest.raises(ValueError):
        slug("  ")


def test_export_reference_et_separation_eval():
    a = {"1": OK, "2": OK, "3": OK}
    b = {"1": OK, "2": {**OK, "emotion": "joie"}, "3": OK}
    cons = {"2": {**OK, "emotion": "joie"}}
    refs, conflits = export.reference_labels({"a": a, "b": b})
    assert set(refs) == {"1", "3"} and conflits == ["2"]
    refs, conflits = export.reference_labels({"a": a, "b": b, "consensus": cons})
    assert conflits == [] and refs["2"]["emotion"] == "joie"
    posts = {k: {"text": f"t{k}", "created_at": "x"} for k in "123"}
    train, ev = export.split(refs, posts, {"3"})
    assert [r["post_id"] for r in train] == ["1", "2"] and [r["post_id"] for r in ev] == ["3"]
    assert not {r["post_id"] for r in train} & {r["post_id"] for r in ev}


def test_export_fige_et_refuse_deuxieme_gel(tmp_path):
    adir = tmp_path / "annotation"
    (adir / "lots").mkdir(parents=True)
    (adir / "annotations").mkdir()
    (adir / "lots" / "lot_eval.jsonl").write_text(json.dumps({"post_id": "3", "text": "t"}) + "\n")
    (adir / "lots" / "corpus_propre.jsonl").write_text(
        json.dumps({"post_id": "1", "text": "t1"}) + "\n" + json.dumps({"post_id": "3", "text": "t"}) + "\n")
    (adir / "annotations" / "a.jsonl").write_text("".join(json.dumps({**OK, "post_id": i}) + "\n" for i in "13"))
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    with pytest.raises(SystemExit):
        export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    export.main(["--corpus-dir", str(tmp_path)])
    assert [json.loads(l)["post_id"] for l in (adir / "train.jsonl").read_text().splitlines()] == ["1"]
    assert [json.loads(l)["post_id"] for l in (adir / "eval.jsonl").read_text().splitlines()] == ["3"]
    lock = json.loads((adir / "eval_fige.json").read_text())
    lock["ids"].append("9")
    (adir / "eval_fige.json").write_text(json.dumps(lock))
    with pytest.raises(SystemExit):
        export.main(["--corpus-dir", str(tmp_path)])


def test_nouvelles_valeurs_mention_et_groupe_politique():
    assert SCHEMA["cibles"]["stance"] == ["pour", "contre", "neutre", "mention", "ambigu"]
    assert SCHEMA["cibles"]["entites_speciales"] == ["gouvernement", "groupe-politique", "autre"]
    rec = {**OK, "cibles": [{"entite": "le pen", "stance": "mention"}, {"entite": "groupe-politique", "stance": "contre"}]}
    assert validate(rec, SCHEMA, ENT) == []
    assert validate({**OK, "cibles": [{"entite": "le pen", "stance": "indifferent"}]}, SCHEMA, ENT)


def test_doute_rend_les_autres_champs_facultatifs():
    assert validate({"post_id": "1", "pertinent": "doute"}, SCHEMA, ENT) == []
    assert validate({"post_id": "1", "pertinent": "doute", "cibles": [{"entite": "le pen", "stance": None}]},
                    SCHEMA, ENT) == []
    # une chaîne vide vaut « non rempli »
    assert validate({"post_id": "1", "pertinent": "doute", "regle_suffit": "", "ironie": ""},
                    SCHEMA, ENT) == []
    assert validate({"post_id": "1", "pertinent": "oui", "regle_suffit": ""}, SCHEMA, ENT)
    # facultatif ne veut pas dire n'importe quoi : une valeur remplie doit être valide
    assert validate({"post_id": "1", "pertinent": "doute", "emotion": "rage"}, SCHEMA, ENT)
    assert validate({"post_id": "1", "pertinent": "doute", "cibles": [{"entite": "inconnu", "stance": "pour"}]},
                    SCHEMA, ENT)
    # pertinent=oui reste strict
    assert validate({"post_id": "1", "pertinent": "oui"}, SCHEMA, ENT)


def test_doute_enregistre_sans_champs(tmp_path):
    p = annotations_path(tmp_path, "a")
    save_annotation(p, {"post_id": "1", "pertinent": "doute", "commentaire": "ambigu"}, SCHEMA, ENT)
    assert load_annotations(p)["1"]["pertinent"] == "doute"


def _corpus_silver(tmp_path):
    adir = tmp_path / "annotation"
    for d in ("lots", "annotations", "silver/final"):
        (adir / d).mkdir(parents=True)
    w = lambda lot, ids: (adir / "lots" / f"{lot}.jsonl").write_text(
        "".join(json.dumps({"post_id": i, "text": f"texte {i}"}) + "\n" for i in ids))
    w("lot_00_pilote", ["p1"]); w("lot_eval", ["e1"]); w("lot_01", ["a1", "a2"])
    (adir / "lots" / "corpus_propre.jsonl").write_text(
        "".join(json.dumps({"post_id": i, "text": f"texte {i}"}) + "\n" for i in ["p1", "e1", "a1", "a2"]))
    sil = {**OK, "cibles": [{"entite": "le pen", "stance": "mention"}]}
    (adir / "silver" / "final" / "x.jsonl").write_text("".join(json.dumps({**sil, "post_id": i}) + "\n"
                                                      for i in ["p1", "e1", "a1", "a2", "inconnu"])
                                              + json.dumps({"post_id": "a3", "pertinent": "oui"}) + "\n")
    return adir


def test_export_silver_exclut_pilote_et_eval(tmp_path):
    adir = _corpus_silver(tmp_path)
    # a1 est annoté à la main (gold) : il sort aussi de train_silver, seul a2 reste.
    (adir / "annotations" / "a.jsonl").write_text(json.dumps({**OK, "post_id": "a1"}) + "\n")
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    export.main(["--corpus-dir", str(tmp_path), "--silver"])
    rows = [json.loads(l) for l in (adir / "train_silver.jsonl").read_text().splitlines()]
    assert [r["post_id"] for r in rows] == ["a2"]
    assert {r["source"] for r in rows} == {"silver"}
    gold = [json.loads(l) for l in (adir / "train.jsonl").read_text().splitlines()]
    assert {r["source"] for r in gold} == {"gold"} and all(r["post_id"] not in ("p1", "e1") for r in gold)
    assert not any("silver" in l and "gold" in l for l in (adir / "eval.jsonl").read_text().splitlines())


def test_silver_n_entre_pas_dans_train_ni_sans_option(tmp_path):
    adir = _corpus_silver(tmp_path)
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    export.main(["--corpus-dir", str(tmp_path)])
    assert not (adir / "train_silver.jsonl").exists()
    assert (adir / "train.jsonl").read_text() == ""


def test_silver_stats_invalides_et_exclus():
    posts = {"1": {"text": "t"}, "2": {"text": "t"}}
    silver = {"1": OK, "2": {"post_id": "2", "pertinent": "oui"}, "3": OK, "4": OK}
    rows, st = export.silver_train(silver, posts, {"4"}, SCHEMA, ENT, gold=set())
    assert [r["post_id"] for r in rows] == ["1"]
    assert st == {"exclus_pilote_eval": 1, "exclus_gold": 0, "invalides": 1, "sans_texte": 1}


def test_silver_train_exclut_le_gold():
    posts = {"1": {"text": "t"}, "2": {"text": "t"}, "3": {"text": "t"}}
    silver = {"1": OK, "2": OK, "3": OK}
    rows, st = export.silver_train(silver, posts, set(), SCHEMA, ENT, gold={"2"})
    assert [r["post_id"] for r in rows] == ["1", "3"]
    assert st == {"exclus_pilote_eval": 0, "exclus_gold": 1, "invalides": 0, "sans_texte": 0}


def test_export_silver_exclut_les_posts_gold(tmp_path):
    adir = _corpus_silver(tmp_path)
    with open(adir / "lots" / "corpus_propre.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"post_id": "g1", "text": "texte g1"}) + "\n")
    with open(adir / "silver" / "final" / "x.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({**OK, "post_id": "g1"}) + "\n")
    # a1 et g1 sont annotés à la main ; a2 n'a que son étiquette silver et doit rester.
    (adir / "annotations" / "a.jsonl").write_text(
        "".join(json.dumps({**OK, "post_id": i}) + "\n" for i in ["a1", "g1"]))
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    export.main(["--corpus-dir", str(tmp_path), "--silver"])
    ids = [json.loads(l)["post_id"] for l in (adir / "train_silver.jsonl").read_text().splitlines()]
    assert ids == ["a2"]
    assert not {"a1", "g1"} & set(ids)


def test_garde_fou_gold_refuse_la_sortie():
    export.verifier_hors_gold([{"post_id": "1"}], {"2"})          # rien à signaler
    with pytest.raises(SystemExit):
        export.verifier_hors_gold([{"post_id": "1"}, {"post_id": "2"}], {"2"})


def test_export_silver_echoue_si_un_gold_passe_le_filtre(tmp_path, monkeypatch):
    adir = _corpus_silver(tmp_path)
    (adir / "annotations" / "a.jsonl").write_text(json.dumps({**OK, "post_id": "a1"}) + "\n")
    export.main(["--corpus-dir", str(tmp_path), "--freeze-eval"])
    # simule un défaut du filtre : le garde-fou doit arrêter l'export avant écriture
    monkeypatch.setattr(export, "silver_train", lambda *a, **k: ([{"post_id": "a1", "source": "silver"}], {}))
    with pytest.raises(SystemExit):
        export.main(["--corpus-dir", str(tmp_path), "--silver"])
    assert not (adir / "train_silver.jsonl").exists()
