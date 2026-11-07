import pytest

import modeles
from outils_modeles import ETIQUETTES, creer_run

SENTINELLE = "zorglubmodele"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    racine = tmp_path_factory.mktemp("runs")
    return {
        "stance": creer_run(racine / "stance-20261019-1636", "stance"),
        "emotion": creer_run(racine / "emotion-20261019-1700", "emotion", normaliser=False),
    }


def test_niveau_confiance_seuils():
    assert modeles.niveau_confiance(0.8) == "haute"
    assert modeles.niveau_confiance(0.99) == "haute"
    assert modeles.niveau_confiance(0.79) == "moyenne"
    assert modeles.niveau_confiance(0.5) == "moyenne"
    assert modeles.niveau_confiance(0.49) == "aucune"


def test_predire_stance_forme_et_valeurs(runs):
    textes = ["zib zob alpha soutien bravo", "mais equilibre lfi"]
    res = modeles.predire(modeles.Modeles(stance=str(runs["stance"])), "stance", textes, ["alpha", "lfi"])
    assert len(res) == 2
    for etiquette, confiance in res:
        assert etiquette in ETIQUETTES["stance"]
        assert confiance in ("haute", "moyenne", "aucune")


def test_predire_emotion_sans_cible(runs):
    res = modeles.predire(modeles.Modeles(emotion=str(runs["emotion"])), "emotion",
                          ["youpi zob joie", "rage zib colere", "factuel"])
    assert len(res) == 3
    assert all(e in ETIQUETTES["emotion"] for e, _ in res)


def test_predire_lots_restituent_l_ordre(runs):
    """Un lot de 1 et un lot de 16 donnent les mêmes étiquettes, dans l'ordre d'entrée."""
    textes = [f"zib zob alpha {i} bravo" for i in range(20)]
    cibles = ["alpha" if i % 2 else "lfi" for i in range(20)]
    par_lot = modeles.charger(str(runs["stance"]), "stance")
    unitaire = par_lot.predire(textes, cibles, taille_lot=1)
    lot = par_lot.predire(textes, cibles, taille_lot=16)
    assert [e for e, _ in unitaire] == [e for e, _ in lot]


def test_stance_exige_une_cible_par_texte(runs):
    with pytest.raises(ValueError, match="cible"):
        modeles.charger(str(runs["stance"]), "stance").predire(["texte", "autre"], ["lfi"])


def test_charger_une_fois_par_processus(runs):
    a = modeles.charger(str(runs["stance"]), "stance")
    assert modeles.charger(str(runs["stance"]), "stance") is a


def test_run_absent_erreur_claire(tmp_path):
    with pytest.raises(modeles.ModeleError, match="absent"):
        modeles.Modeles(stance=str(tmp_path / "rien")).verifier()


def test_modele_json_manquant_ou_casse(tmp_path):
    casse = creer_run(tmp_path / "casse", "stance")
    (casse / "modele.json").write_text("{pas du json", encoding="utf-8")
    with pytest.raises(modeles.ModeleError, match="modele.json"):
        modeles.Modeles(stance=str(casse)).verifier()


def test_mauvaise_tache_refusee(runs):
    with pytest.raises(modeles.ModeleError, match="tâche attendue"):
        modeles.Modeles(stance=str(runs["emotion"])).verifier()


def test_poids_illisibles_erreur_au_chargement(tmp_path):
    casse = creer_run(tmp_path / "poids", "emotion")
    (casse / "model" / "model.safetensors").write_bytes(b"pas des poids")
    with pytest.raises(modeles.ModeleError, match="illisible"):
        modeles.charger(str(casse), "emotion")


def test_erreur_sans_texte_recu(tmp_path):
    casse = tmp_path / "absent"
    try:
        modeles.Modeles(emotion=str(casse)).verifier()
    except modeles.ModeleError as e:
        assert SENTINELLE not in str(e)


def test_depuis_env(tmp_path):
    vide = modeles.Modeles.depuis_env({"MODELE_STANCE_DIR": "", "MODELE_EMOTION_DIR": "  "})
    assert vide == modeles.Modeles(None, None) and not vide.actifs
    actif = modeles.Modeles.depuis_env({"MODELE_STANCE_DIR": "/opt/modeles/stance-x",
                                        "MODELE_EMOTION_DIR": ""})
    assert actif.stance == "/opt/modeles/stance-x" and actif.emotion is None
    assert actif.noms() == ["stance-x"]


def test_predire_sans_run_actif_erreur():
    with pytest.raises(ValueError, match="aucun run"):
        modeles.predire(modeles.Modeles(), "stance", ["texte"], ["lfi"])

