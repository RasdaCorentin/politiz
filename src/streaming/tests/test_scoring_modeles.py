"""Scoreur avec modèles actifs. Textes inventés ; runs minuscules créés sans réseau."""
import pandas as pd
import pytest

import job
import modeles
import scoring
from outils_modeles import ETIQUETTES, creer_run

POST_CIBLE = "je voterai glucksmann au premier tour"
POST_RIEN = "zorglub rien du tout ici"
MAINTENANT_US = 1_000_000_000_000_000


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    racine = tmp_path_factory.mktemp("runs-scoring")
    return {
        "stance": str(creer_run(racine / "stance-20261019-1636", "stance")),
        "emotion": str(creer_run(racine / "emotion-20261019-1700", "emotion", normaliser=False)),
    }


@pytest.fixture
def faux_modele(monkeypatch):
    """Remplace l'inférence par une réponse fixe : permet de vérifier le remplacement exact."""
    def installer(stance=None, emotion=None):
        def predire(m, tache, textes, cibles=None):
            valeur = stance if tache == "stance" else emotion
            return [valeur] * len(textes)
        monkeypatch.setattr(modeles, "predire", predire)
    return installer


def test_libelle_scoreur():
    assert scoring.libelle_scoreur(None) == "lexique-v1"
    assert scoring.libelle_scoreur(modeles.Modeles()) == "lexique-v1"
    assert scoring.libelle_scoreur(modeles.Modeles(stance="/opt/modeles/stance-20261019-1636")) \
        == "camembert:stance-20261019-1636"
    assert scoring.libelle_scoreur(modeles.Modeles("/x/stance-a", "/x/emotion-b")) \
        == "camembert:stance-a+emotion-b"


def test_sans_modele_identique_au_scoreur_pur():
    textes = [POST_CIBLE, POST_RIEN, "bravo glucksmann"]
    sans = scoring.scorer_serie(pd.Series(textes))
    vide = scoring.scorer_serie(pd.Series(textes), modeles.Modeles())
    pur = pd.DataFrame([scoring.scorer(t) for t in textes])
    pd.testing.assert_frame_equal(sans, pur)
    pd.testing.assert_frame_equal(vide, pur)


def test_stance_remplacee_seulement_pour_les_cibles_detectees(faux_modele, runs):
    faux_modele(stance=("contre", "haute"))
    sortie = scoring.scorer_serie(pd.Series([POST_CIBLE, POST_RIEN]),
                                  modeles.Modeles(stance=runs["stance"]))
    cible, rien = sortie.iloc[0], sortie.iloc[1]
    assert [(c["entite"], c["stance"], c["confiance"]) for c in cible["cibles"]] == [
        ("glucksmann", "contre", "haute")]
    assert rien["cibles"][0]["entite"] is None
    assert rien["cibles"][0]["stance"] == "non_evalue"  # la ligne à entité nulle reste lexicale
    assert cible["sentiment"] == "negatif"  # sentiment dérivé de la stance finale


def test_emotion_remplacee_et_themes_inchanges(faux_modele, runs):
    faux_modele(emotion=("joie", "haute"))
    lexique_seul = scoring.scorer_serie(pd.Series([POST_CIBLE]))
    avec = scoring.scorer_serie(pd.Series([POST_CIBLE]), modeles.Modeles(emotion=runs["emotion"]))
    assert avec.iloc[0]["emotion"] == "joie"
    assert avec.iloc[0]["sentiment"] == "positif"
    assert list(avec.iloc[0]["themes"]) == list(lexique_seul.iloc[0]["themes"])
    assert avec.iloc[0]["cibles"] == lexique_seul.iloc[0]["cibles"]  # cibles lexicales inchangées


def test_sortie_des_vrais_petits_modeles(runs):
    actifs = modeles.Modeles(stance=runs["stance"], emotion=runs["emotion"])
    sortie = scoring.scorer_serie(pd.Series([POST_CIBLE, POST_RIEN]), actifs)
    assert len(sortie) == 2
    for _, ligne in sortie.iterrows():
        assert ligne["emotion"] in ETIQUETTES["emotion"]
        assert ligne["sentiment"] in ("positif", "negatif", "neutre", "non_evalue")
        for c in ligne["cibles"]:
            if c["entite"] is not None:
                assert c["stance"] in ETIQUETTES["stance"]
                assert c["confiance"] in ("haute", "moyenne", "aucune")


def test_inference_par_lot_equivaut_au_texte_seul(runs):
    """Le lot donne la même étiquette qu'un appel texte par texte."""
    textes = [POST_CIBLE, POST_RIEN, "bravo glucksmann ici"]
    par_lot = scoring.scorer_serie(pd.Series(textes), modeles.Modeles(emotion=runs["emotion"]))
    un_a_un = [scoring.scorer_serie(pd.Series([t]), modeles.Modeles(emotion=runs["emotion"])).iloc[0]["emotion"]
               for t in textes]
    assert list(par_lot["emotion"]) == un_a_un


def test_spark_scoreur_et_filtre_fin(spark, runs):
    """Le job écrit le libellé `camembert:` ; le filtre fin écarte un post sans rien de reconnu."""
    df = spark.createDataFrame([(MAINTENANT_US - 61_000_000, POST_CIBLE),
                                (MAINTENANT_US - 62_000_000, POST_RIEN)], ["time_us", "texte"])
    actifs = modeles.Modeles(stance=runs["stance"])
    lot = job.traiter_micro_lot(df, spark, 5, MAINTENANT_US, modeles=actifs)
    posts = lot.posts.collect()
    assert {r.scoreur for r in posts} == {"camembert:stance-20261019-1636"}
    assert {r.entite for r in posts} == {"glucksmann"}
    pipeline = lot.pipeline_fenetre.collect()[0]
    assert pipeline.nb_posts == 2  # le pipeline compte tous les posts du lot
    croisements = lot.croisements_fenetre.collect()
    assert {r.scoreur for r in croisements} == {"camembert:stance-20261019-1636"}
    lot.liberer()


def test_spark_sans_modele_garde_lexique(spark):
    df = spark.createDataFrame([(MAINTENANT_US - 61_000_000, POST_CIBLE)], ["time_us", "texte"])
    lot = job.traiter_micro_lot(df, spark, 5, MAINTENANT_US)
    assert {r.scoreur for r in lot.posts.collect()} == {"lexique-v1"}
    lot.liberer()


def test_filtre_fin_fixe_par_le_lexique_quand_le_modele_d_emotion_est_actif(faux_modele, runs):
    """Le modèle donne une émotion à tout post ; le filtre suit le lexique seul."""
    faux_modele(emotion=("joie", "haute"))
    actifs = modeles.Modeles(emotion=runs["emotion"])
    sortie = scoring.scorer_serie(pd.Series([POST_CIBLE, POST_RIEN]), actifs)
    cible, rien = sortie.iloc[0], sortie.iloc[1]
    assert rien["emotion"] == "joie" and not rien["retenu"]  # retiré malgré l'émotion du modèle
    assert cible["emotion"] == "joie" and cible["retenu"]  # retenu : garde l'émotion du modèle


def test_retenu_sans_modele_suit_le_lexique(runs):
    sans = scoring.scorer_serie(pd.Series([POST_CIBLE, POST_RIEN]))
    assert list(sans["retenu"]) == [True, False]
    assert list(sans["retenu"]) == [scoring.scorer(t)["retenu"] for t in (POST_CIBLE, POST_RIEN)]


def test_spark_modele_emotion_retire_post_sans_reconnaissance_lexicale(spark, runs):
    """Avec le run d'émotion actif, le post sans rien de reconnu ne sort dans aucune table."""
    df = spark.createDataFrame([(MAINTENANT_US - 61_000_000, POST_CIBLE),
                                (MAINTENANT_US - 62_000_000, POST_RIEN)], ["time_us", "texte"])
    actifs = modeles.Modeles(emotion=runs["emotion"])
    lot = job.traiter_micro_lot(df, spark, 5, MAINTENANT_US, modeles=actifs)
    assert {r.entite for r in lot.posts.collect()} == {"glucksmann"}
    assert all(r.emotion in ETIQUETTES["emotion"] for r in lot.posts.collect())
    assert lot.pipeline_fenetre.collect()[0].nb_posts == 2  # le pipeline compte tous les posts
    assert sum(r.nb_posts for r in lot.posts_fenetre.collect()) == 1
    assert "retenu" not in lot.posts.columns
    lot.liberer()
