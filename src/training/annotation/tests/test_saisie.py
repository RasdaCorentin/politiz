"""Logique pure de la saisie gold : lecture d'un lot, valeurs initiales, cibles, contexte, arguments.

Posts fabriqués : aucun contenu réel.
"""
import json

import pytest

from annotation.common import entity_choices, load_entites, load_schema
from annotation.saisie import config, contexte, enregistrement, lire_lot, valeurs_initiales
from annotation.storage import save_annotation

SCHEMA = load_schema()
ENTITES = entity_choices(SCHEMA, load_entites())


def post(i, **extra):
    base = {"post_id": f"p{i}", "lot": "lot_gold_01", "source": "synthetique",
            "created_at": "2026-10-01T08:00:00Z", "texte": f"texte inventé [mention] numéro {i}",
            "contexte_type": None, "contexte_texte": None}
    base.update(extra)
    return base


def ecrire_lot(path, posts):
    path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in posts), encoding="utf-8")
    return path


def test_lire_lot_rend_les_posts_dans_l_ordre(tmp_path):
    lot = ecrire_lot(tmp_path / "lot_gold_01.jsonl", [post(1), post(2), post(3)])
    assert [p["post_id"] for p in lire_lot(lot)] == ["p1", "p2", "p3"]


@pytest.mark.parametrize("manque", ["post_id", "lot", "texte"])
def test_lire_lot_refuse_un_champ_obligatoire_absent(tmp_path, manque):
    p = post(1)
    del p[manque]
    lot = ecrire_lot(tmp_path / "l.jsonl", [post(0), p])
    with pytest.raises(ValueError, match=manque):
        lire_lot(lot)


def test_lire_lot_refuse_un_post_id_en_double(tmp_path):
    lot = ecrire_lot(tmp_path / "l.jsonl", [post(1), post(1)])
    with pytest.raises(ValueError, match="en double"):
        lire_lot(lot)


def test_lire_lot_refuse_un_lot_vide_ou_absent(tmp_path):
    with pytest.raises(ValueError):
        lire_lot(tmp_path / "absent.jsonl")


def test_valeurs_par_defaut_pour_un_post_non_annote():
    v = valeurs_initiales(None, ENTITES)
    assert v["pertinent"] == "oui"
    assert v["emotion"] is None
    assert v["ironie"] == "non"
    assert v["regle_suffit"] == "non"
    assert v["cibles"] == [] and v["themes"] == []


def test_valeurs_par_defaut_ne_partagent_pas_de_liste_entre_appels():
    v = valeurs_initiales(None, ENTITES)
    v["cibles"].append({"entite": "x", "stance": "pour"})
    assert valeurs_initiales(None, ENTITES)["cibles"] == []


def test_valeurs_d_une_annotation_existante_priment_sur_les_defauts():
    existant = {"pertinent": "non", "cibles": [], "themes": [], "emotion": None, "ironie": None,
                "regle_suffit": None, "indice": "", "commentaire": "langue"}
    v = valeurs_initiales(existant, ENTITES)
    assert v["pertinent"] == "non" and v["emotion"] is None and v["commentaire"] == "langue"


def test_cible_absente_de_entites_yaml_n_est_pas_reprise():
    existant = {"pertinent": "oui", "cibles": [{"entite": "fantome", "stance": "pour"}],
                "themes": [], "emotion": "neutre", "ironie": "non", "regle_suffit": "non"}
    assert valeurs_initiales(existant, ENTITES)["cibles"] == []


def test_validation_des_cibles_contre_entites_yaml(tmp_path):
    assert "le pen" in ENTITES and "groupe-politique" in ENTITES
    rec = enregistrement(post(1), "Test", {"pertinent": "oui", "cibles": [{"entite": "fantome", "stance": "pour"}],
                                           "emotion": "neutre", "ironie": "non", "regle_suffit": "non"})
    with pytest.raises(ValueError, match="entité inconnue"):
        save_annotation(tmp_path / "t.jsonl", rec, SCHEMA, ENTITES)
    rec["cibles"] = [{"entite": "le pen", "stance": "contre"}]
    save_annotation(tmp_path / "t.jsonl", rec, SCHEMA, ENTITES)


def test_contexte_parent_ou_cite_ou_rien():
    assert contexte(post(1)) is None
    assert contexte(post(1, contexte_type="reponse", contexte_texte="parent")) == ("Post parent", "parent")
    assert contexte(post(1, contexte_type="citation", contexte_texte="cité")) == ("Post cité", "cité")


def test_enregistrement_garde_les_champs_du_format_existant():
    rec = enregistrement(post(7), "  Corentin ", {"pertinent": "oui", "cibles": [], "themes": ["economie"],
                                                  "emotion": "joie", "ironie": "non", "regle_suffit": "non",
                                                  "indice": "", "commentaire": ""})
    assert list(rec) == ["post_id", "lot", "annotateur", "pertinent", "cibles", "themes", "emotion",
                         "ironie", "regle_suffit", "indice", "commentaire"]
    assert rec["lot"] == "lot_gold_01" and rec["annotateur"] == "Corentin"


def test_config_lit_les_arguments_puis_les_variables(tmp_path):
    lot, nom, corpus = config(["--lot", str(tmp_path / "a.jsonl"), "--annotateur", "Corentin"], {})
    assert lot == tmp_path / "a.jsonl" and nom == "Corentin" and corpus is None
    lot, nom, _ = config([], {"SAE_LOT": "/x/l.jsonl", "SAE_ANNOTATEUR": "Ana"})
    assert str(lot) == "/x/l.jsonl" and nom == "Ana"
    # les arguments priment sur les variables
    lot, nom, _ = config(["--annotateur", "Bob"], {"SAE_ANNOTATEUR": "Ana"})
    assert nom == "Bob"
    assert config([], {}) == (None, None, None)


def test_config_accepte_le_dossier_du_corpus_en_argument():
    _, _, corpus = config(["--lot", "l.jsonl", "--annotateur", "Ana", "--corpus-dir", "/x/corpus"], {})
    assert corpus == "/x/corpus"
