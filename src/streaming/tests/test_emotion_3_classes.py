"""Run d'émotion à trois classes (joie, colere, neutre) : le streaming l'accepte sans changement.

Le run porte `"nettoyer": true` dans `modele.json["entree"]` : clé que le streaming ignore, son
texte étant déjà nettoyé par `pii.py`. Textes inventés ; run minuscule créé sans réseau ; pas de Spark.
"""
import pandas as pd
import pytest

import modeles
import scoring
from outils_modeles import creer_run

ETIQUETTES_3 = ["joie", "colere", "neutre"]
POST_RIEN = "zorglub rien du tout ici"
TEXTES = [POST_RIEN, "zib zob bravo", "alpha lfi mardi", "youpi zob joie", "rage zib colere"]
CONFIANCES = ("haute", "moyenne", "aucune")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    racine = tmp_path_factory.mktemp("runs-emotion-3")
    return str(creer_run(racine / "emotion-20261031-1200", "emotion", normaliser=False,
                         etiquettes=ETIQUETTES_3, entree_extra={"nettoyer": True}))


@pytest.fixture
def faux_emotion(monkeypatch):
    """Remplace l'inférence par une émotion fixe, sans modèle."""
    def installer(etiquette):
        def predire(m, tache, textes, cibles=None):
            return [(etiquette, "haute")] * len(textes)
        monkeypatch.setattr(modeles, "predire", predire)
    return installer


def test_emotion_a_trois_classes_se_charge(run):
    modeles.Modeles(emotion=run).verifier()  # métadonnées valides, sous-dossiers présents
    predicteur = modeles.charger(run, "emotion")
    assert predicteur.etiquettes == ETIQUETTES_3
    assert predicteur.tache == "emotion"


def test_cle_nettoyer_ignoree_sans_erreur(run):
    """`nettoyer` n'est pas lu par le streaming : la normalisation reste celle du run (ici False)."""
    predicteur = modeles.charger(run, "emotion")
    assert predicteur.normaliser is False


def test_predictions_limitees_aux_trois_classes(run):
    res = modeles.predire(modeles.Modeles(emotion=run), "emotion", TEXTES)
    assert len(res) == len(TEXTES)
    for etiquette, confiance in res:
        assert etiquette in ETIQUETTES_3
        assert confiance in CONFIANCES


def test_etiquettes_du_run_incluses_dans_l_enum_du_contrat():
    """Les trois étiquettes figurent dans l'enum `emotion` du contrat (contrats-poc.md) : ClickHouse ne change pas."""
    enum_contrat = {"joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre", "non_evalue"}
    assert set(ETIQUETTES_3) <= enum_contrat


def test_colonne_emotion_limitee_aux_trois_classes(run):
    sortie = scoring.scorer_serie(pd.Series(TEXTES), modeles.Modeles(emotion=run))
    assert set(sortie["emotion"]) <= set(ETIQUETTES_3)
    assert "non_evalue" not in set(sortie["emotion"])  # le modèle étiquette chaque post


@pytest.mark.parametrize("etiquette, sentiment_attendu", [("joie", "positif"), ("colere", "negatif")])
def test_sentiment_derive_de_l_emotion_du_modele(faux_emotion, run, etiquette, sentiment_attendu):
    """Sans règle de stance, l'émotion du modèle fixe le sentiment (libellés de `deriver_sentiment`)."""
    faux_emotion(etiquette)
    ligne = scoring.scorer_serie(pd.Series([POST_RIEN]), modeles.Modeles(emotion=run)).iloc[0]
    assert ligne["emotion"] == etiquette
    assert ligne["sentiment"] == sentiment_attendu


def test_neutre_sans_stance_donne_non_evalue(faux_emotion, run):
    """`neutre` ne porte pas de tonalité : sans règle de stance, le sentiment reste `non_evalue`."""
    faux_emotion("neutre")
    ligne = scoring.scorer_serie(pd.Series([POST_RIEN]), modeles.Modeles(emotion=run)).iloc[0]
    assert ligne["emotion"] == "neutre"
    assert ligne["sentiment"] == "non_evalue"
