import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

import pii
import scoring

LEX = scoring.lexique()
REGLES = yaml.safe_load(
    (Path(os.environ["LEXIQUE_DIR"]) / "stance.yaml").read_text(encoding="utf-8"))["regles"]


def ids_declenchees(texte):
    return {h["regle"] for h in scoring.declenchements(LEX, pii.nettoyer_texte(texte))}


def score(texte):
    return scoring.scorer(pii.nettoyer_texte(texte))


def cible(res, entite):
    return next(c for c in res["cibles"] if c["entite"] == entite)


# --- chaque règle sur ses propres exemples --------------------------------------
CAS_POSITIFS = [(r["id"], ex) for r in REGLES for ex in r["exemples"]["positifs"]]
CAS_NEGATIFS = [(r["id"], ex) for r in REGLES for ex in r["exemples"].get("negatifs") or []]


@pytest.mark.parametrize("regle,exemple", CAS_POSITIFS)
def test_exemple_positif_declenche_sa_regle(regle, exemple):
    assert regle in ids_declenchees(exemple)


@pytest.mark.parametrize("regle,exemple", CAS_NEGATIFS)
def test_exemple_negatif_ne_declenche_pas_sa_regle(regle, exemple):
    assert regle not in ids_declenchees(exemple)


def test_toutes_les_regles_sont_couvertes():
    assert {r for r, _ in CAS_POSITIFS} == {r["id"] for r in REGLES}


# --- domaines de valeurs ----------------------------------------------------------
STANCES = {"pour", "contre", "neutre", "mention", "ambigu", "non_evalue"}
SENTIMENTS = {"positif", "negatif", "neutre", "non_evalue"}
EMOTIONS = {"joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre", "non_evalue"}
THEMES = {"economie", "social-retraites", "immigration", "securite", "ecologie",
          "europe-international", "institutions", "sante-education", "campagne-sondages",
          "autre"}


@pytest.mark.parametrize("regle,exemple", CAS_POSITIFS)
def test_domaines_de_valeurs(regle, exemple):
    r = score(exemple)
    assert r["sentiment"] in SENTIMENTS and r["emotion"] in EMOTIONS
    assert set(r["themes"]) <= THEMES and r["themes"]
    assert r["cibles"]
    for c in r["cibles"]:
        assert c["stance"] in STANCES and c["confiance"] in {"haute", "moyenne", "aucune"}
        assert (c["confiance"] == "aucune") == (c["stance"] == "non_evalue")


# --- cas inventés -----------------------------------------------------------------
def test_stance_pour_et_sentiment_positif():
    r = score("Je voterai Glucksmann au premier tour")
    c = cible(r, "glucksmann")
    assert (c["stance"], c["confiance"]) == ("pour", "haute")
    assert r["sentiment"] == "positif"
    assert "campagne-sondages" in r["themes"]


def test_stance_contre_et_sentiment_negatif():
    r = score("Je ne voterai jamais Mélenchon")
    assert cible(r, "melenchon")["stance"] == "contre"
    assert r["sentiment"] == "negatif"


def test_cite_sans_regle_est_non_evalue():
    r = score("Glucksmann était à Lyon hier soir")
    c = cible(r, "glucksmann")
    assert (c["stance"], c["confiance"]) == ("non_evalue", "aucune")
    assert r["sentiment"] == "non_evalue"


def test_handle_ne_cite_pas_l_entite():
    r = score("@attal.bsky.social merci pour le fil")
    assert r["cibles"] == [{"entite": None, "stance": "non_evalue", "confiance": "aucune"}]


def test_alias_ambigu_seul_ne_donne_pas_de_cible():
    ambigus = [f for f, v in LEX.alias.items() if v["ambigu"]]
    assert ambigus
    for forme in ambigus:
        assert not scoring.entites_citees(LEX, f"un texte avec {forme} dedans"), forme


def test_alias_ambigu_capture_par_une_regle_vise_son_entite():
    r = score("Je ne vote plus PS")
    assert cible(r, "parti socialiste")["stance"] == "contre"
    assert score("le ps a tenu une conference")["cibles"] == [
        {"entite": None, "stance": "non_evalue", "confiance": "aucune"}]


def test_deux_candidats_deux_cibles():
    r = score("Votez Glucksmann, jamais Bardella")
    assert {c["entite"] for c in r["cibles"]} >= {"glucksmann", "bardella"}


def test_cible_a_id_fixe_sans_alias_dans_le_texte():
    fixes = [x for x in REGLES if x["cible"] in LEX.ids]
    assert fixes
    for regle in fixes:
        r = score(regle["exemples"]["positifs"][0])
        assert cible(r, regle["cible"])["stance"] == regle["stance"] or regle["confiance"] == "basse"


@pytest.mark.parametrize("texte,theme", [
    ("la dette et le budget explosent", "economie"),
    ("reforme des retraites encore repoussee", "social-retraites"),
    ("la guerre en ukraine continue", "europe-international"),
    ("le second tour approche", "campagne-sondages"),
])
def test_themes(texte, theme):
    assert theme in score(texte)["themes"]


def test_theme_autre_si_rien():
    assert score("il fait beau aujourd'hui")["themes"] == ["autre"]


@pytest.mark.parametrize("texte,emotion,sentiment", [
    ("quelle horreur 🤮", "degout", "negatif"),
    ("encore ca 🤬", "colere", "negatif"),
    ("on a gagne 🥳", "joie", "positif"),
    ("rien de special", "non_evalue", "non_evalue"),
])
def test_emotions_et_sentiment_derive(texte, emotion, sentiment):
    r = score(texte)
    assert (r["emotion"], r["sentiment"]) == (emotion, sentiment)


def test_emotion_basse_confiance_ignoree():
    assert score("mdr 🤡")["emotion"] == "non_evalue"


def test_sondage_est_une_mention_et_sentiment_neutre():
    mentions = [r for r in REGLES if r["stance"] == "mention" and r["confiance"] == "haute"]
    assert mentions
    r = score(mentions[0]["exemples"]["positifs"][0])
    assert r["sentiment"] == "neutre"
    assert any(c["stance"] == "mention" for c in r["cibles"])


def test_deriver_sentiment_egalite_et_majorite():
    pour = {"stance": "pour"}
    contre = {"stance": "contre"}
    assert scoring.deriver_sentiment([pour, contre], "colere") == "neutre"
    assert scoring.deriver_sentiment([pour, pour, contre], "colere") == "positif"
    assert scoring.deriver_sentiment([contre], "joie") == "negatif"
    assert scoring.deriver_sentiment([{"stance": "ambigu"}], "joie") == "positif"
    assert scoring.deriver_sentiment([{"stance": "ambigu"}], "non_evalue") == "neutre"
    assert scoring.deriver_sentiment([], "surprise") == "non_evalue"


def test_conflit_pour_contre_sur_une_cible_est_ambigu():
    assert scoring._trancher([("pour", "haute"), ("contre", "moyenne")]) == ("ambigu", "haute")
    assert scoring._trancher([]) == ("non_evalue", "aucune")


def test_version_vectorisee_equivaut_a_la_fonction_pure():
    textes = ["votez glucksmann", "rien", "quelle horreur 🤮", ""]
    df = scoring.scorer_serie(pd.Series(textes))
    assert df.to_dict("records") == [scoring.scorer(t) for t in textes]


def test_lexique_charge_une_fois():
    assert scoring.lexique() is scoring.lexique()


# --- adjectifs (lexique fermé) ------------------------------------------------------
def adjectifs(texte):
    return scoring.adjectifs_du_texte(LEX, pii.nettoyer_texte(texte))


def test_adjectif_flechi_rendu_sous_sa_forme_affichee():
    assert adjectifs("Une candidate Dangereuse et très sérieuse") == ["dangereux", "sérieux"]


def test_adjectif_compte_une_fois_par_post_et_trie():
    assert adjectifs("dangereux, dangereux, crédibles et dangereuses") == ["crédible", "dangereux"]


def test_adjectif_ambigu_jamais_compte():
    assert adjectifs("c'est juste ça") == []
    assert "juste" not in LEX.adjectifs


def test_participe_masculin_singulier_absent_du_lexique():
    """« compliqué » au masculin singulier est aussi un participe (« il a compliqué ») : seules ses
    autres formes comptent."""
    assert adjectifs("il a compliqué le débat") == []
    assert adjectifs("une réforme compliquée") == ["compliqué"]


def test_adjectif_en_mot_entier_hors_handles():
    assert adjectifs("@dangereux.bsky.social parle d'incredibles") == []


def test_forme_en_double_refusee(tmp_path):
    for nom in ("entites", "stance", "themes", "emotions"):
        (tmp_path / f"{nom}.yaml").write_text(
            (Path(os.environ["LEXIQUE_DIR"]) / f"{nom}.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "adjectifs.yaml").write_text(
        "adjectifs:\n  - {adjectif: a, formes: [x]}\n  - {adjectif: b, formes: [x]}\n", encoding="utf-8")
    with pytest.raises(scoring.LexiqueError, match="forme 'x'"):
        scoring.charger_lexique(str(tmp_path))


def test_sortie_porte_les_adjectifs():
    assert score("Je voterai Glucksmann, un candidat crédible")["adjectifs"] == ["crédible"]
    assert score("rien")["adjectifs"] == []
