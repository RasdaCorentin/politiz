"""Interface de saisie gold (Streamlit AppTest) : défauts, enregistrement, reprise, correction.

Lots fabriqués : aucun texte réel. Les variables SAE_* pilotent le lancement, comme en production.
"""
import json

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from annotation.common import HERE  # noqa: E402
from annotation.storage import load_annotations  # noqa: E402

APP = str(HERE / "app.py")


def lot_synthetique(dossier, n=3):
    posts = [{"post_id": f"s{i}", "lot": "lot_gold_test", "source": "synthetique",
              "created_at": "2026-10-01T08:00:00Z", "texte": f"texte inventé numéro {i}",
              "contexte_type": "reponse" if i == 1 else None,
              "contexte_texte": "parent inventé" if i == 1 else None} for i in range(n)]
    chemin = dossier / "lot_gold_test.jsonl"
    chemin.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in posts), encoding="utf-8")
    return chemin


@pytest.fixture
def cadre(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    lots = corpus / "annotation" / "lots_gold"
    lots.mkdir(parents=True)
    lot = lot_synthetique(lots)
    monkeypatch.setenv("SAE_CORPUS_DIR", str(corpus))
    monkeypatch.setenv("SAE_LOT", str(lot))
    monkeypatch.setenv("SAE_ANNOTATEUR", "Test")
    return corpus / "annotation" / "annotations" / "test.jsonl"


def lancer():
    return AppTest.from_file(APP, default_timeout=20).run()


def bouton(at, debut):
    return [b for b in at.button if b.label.startswith(debut)][0]


def cle(champ, pid="s0"):
    """Clé de session d'un champ du post pid (préfixe lot:annotateur:post_id:, cf. app.py)."""
    return f"lot_gold_test:test:{pid}:{champ}"


def test_defauts_puis_enregistrement_au_format_existant(cadre):
    at = lancer()
    assert not at.exception and not at.error
    assert any(c.value == "Post 1 / 3" for c in at.caption)
    bouton(at, "Enregistrer").click().run()
    assert at.error and not cadre.exists()  # pas d'émotion par défaut : refus à l'enregistrement
    bouton(at, "neutre").click().run()  # bouton de l'émotion (libellé en minuscules, cf. AFFICHAGE)
    bouton(at, "Enregistrer").click().run()
    assert not at.exception
    lignes = cadre.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 1
    rec = json.loads(lignes[0])
    assert rec["post_id"] == "s0" and rec["lot"] == "lot_gold_test" and rec["annotateur"] == "Test"
    assert rec["pertinent"] == "oui" and rec["emotion"] == "neutre"
    assert rec["ironie"] == "non" and rec["regle_suffit"] == "non"
    assert rec["horodatage"].endswith("+00:00")
    assert any(c.value == "Post 2 / 3" for c in at.caption)


def test_reprise_au_premier_post_non_annote(cadre):
    lancer().run()
    cadre.parent.mkdir(parents=True, exist_ok=True)
    cadre.write_text(json.dumps({"post_id": "s0", "lot": "lot_gold_test", "annotateur": "Test",
                                 "pertinent": "oui", "cibles": [], "themes": [], "emotion": "neutre",
                                 "ironie": "non", "regle_suffit": "non", "indice": "", "commentaire": "",
                                 "horodatage": "2026-10-01T08:00:00+00:00"}) + "\n", encoding="utf-8")
    at = lancer()
    assert any(c.value == "Post 2 / 3" for c in at.caption)
    assert any("1 / 3 annotés" in p.proto.text for p in at.get("progress"))


def test_correction_ajoute_une_ligne_et_la_derniere_fait_foi(cadre):
    at = lancer()
    at.session_state[cle("emotion")] = "neutre"
    bouton(at, "Enregistrer").click().run()          # s0 : oui
    bouton(at, "Précédent").click().run()            # retour sur s0 (pré-rempli depuis le fichier)
    at.session_state[cle("pertinent")] = "non"
    bouton(at, "Enregistrer").click().run()          # correction : une seconde ligne
    lignes = cadre.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2
    assert json.loads(lignes[0])["pertinent"] == "oui"   # la première ligne n'est jamais réécrite
    assert load_annotations(cadre)["s0"]["pertinent"] == "non"


def test_non_enregistre_sans_stance_pour_une_cible(cadre):
    at = lancer()
    at.session_state[cle("cibles")] = ["le pen"]
    at.run()
    bouton(at, "Enregistrer").click().run()
    assert any("Non enregistré" in e.value for e in at.error)
    assert not cadre.exists()


def test_cible_avec_stance_s_enregistre(cadre):
    at = lancer()
    at.session_state[cle("cibles")] = ["le pen"]
    at.session_state[cle("stance:le pen")] = "contre"
    at.session_state[cle("themes")] = ["immigration"]
    at.session_state[cle("emotion")] = "neutre"
    at.run()
    bouton(at, "Enregistrer").click().run()
    assert not at.error
    rec = load_annotations(cadre)["s0"]
    assert rec["cibles"] == [{"entite": "le pen", "stance": "contre"}]
    assert rec["themes"] == ["immigration"]


def test_lot_illisible_affiche_une_erreur_sans_plantage(cadre, monkeypatch, tmp_path):
    mauvais = tmp_path / "mauvais.jsonl"
    mauvais.write_text(json.dumps({"post_id": "x", "lot": "l"}) + "\n", encoding="utf-8")
    monkeypatch.setenv("SAE_LOT", str(mauvais))
    at = lancer()
    assert not at.exception
    assert any("texte" in e.value for e in at.error)


def test_sans_annotateur_le_lancement_est_refuse(cadre, monkeypatch):
    monkeypatch.delenv("SAE_ANNOTATEUR")
    at = lancer()
    assert not at.exception and at.error


def test_silver_jamais_affiche_ni_charge():
    src = (HERE / "app.py").read_text(encoding="utf-8").lower()
    assert "silver" not in src  # l'outil ne lit ni n'affiche jamais de silver (biais d'ancrage)
