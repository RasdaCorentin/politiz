"""Tests de donnees.py sur un corpus inventé."""
import copy
import json
import random

import pytest

from modele import donnees
from modele.tests import outils


@pytest.fixture
def lignes():
    return outils.lignes_factices(96)


def test_etiquettes_lues_dans_le_schema():
    assert donnees.etiquettes("stance") == ["pour", "contre", "neutre", "mention", "ambigu"]
    assert donnees.etiquettes("emotion") == ["joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre"]
    with pytest.raises(ValueError):
        donnees.etiquettes("sentiment")


def test_regroupement_ne_change_que_la_stance():
    assert donnees.etiquettes("stance", regroupe=True) == ["pour", "contre", "neutre", "ambigu"]
    assert donnees.etiquettes("stance") == ["pour", "contre", "neutre", "mention", "ambigu"]   # schéma intact
    assert donnees.etiquettes("emotion", regroupe=True) == donnees.etiquettes("emotion")


def test_regroupement_exemples_fusionne_et_compte_une_fois():
    ligne = {"post_id": "x", "text": "texte inventé", "pertinent": "oui", "emotion": "neutre",
             "cibles": [{"entite": "lfi", "stance": "mention"}, {"entite": "npa", "stance": "neutre"},
                        {"entite": "lfi", "stance": "neutre"}, {"entite": "eelv", "stance": "pour"}]}
    origine = copy.deepcopy(ligne)
    sans = donnees.construire_exemples([ligne], "stance")
    assert [(e.cible, e.etiquette) for e in sans] == [("lfi", "mention"), ("npa", "neutre"), ("eelv", "pour")]
    avec = donnees.construire_exemples([ligne], "stance", regroupe=True)
    assert [(e.cible, e.etiquette) for e in avec] == [("lfi", "neutre"), ("npa", "neutre"), ("eelv", "pour")]
    assert ligne == origine                                             # la ligne d'origine n'est pas modifiée


def test_regroupement_aucune_mention_dans_les_exemples(lignes):
    ex = donnees.construire_exemples(lignes, "stance", regroupe=True)
    assert ex and {e.etiquette for e in ex} <= {"pour", "contre", "neutre", "ambigu"}


def test_exemples_stance_un_par_couple_post_cible(lignes):
    ex = donnees.construire_exemples(lignes, "stance")
    attendu = 0
    for l in lignes:
        if l["pertinent"] == "oui":
            attendu += len([c for c in l["cibles"] if c["entite"] != "autre"])
    assert len(ex) == attendu > 0
    assert all(e.cible and e.cible != "autre" for e in ex)
    # `non` et `doute` n'entrent jamais
    ids_exclus = {l["post_id"] for l in lignes if l["pertinent"] != "oui"}
    assert ids_exclus and not ids_exclus & {e.post_id for e in ex}


def test_exemples_emotion_un_par_post(lignes):
    ex = donnees.construire_exemples(lignes, "emotion")
    assert len(ex) == sum(1 for l in lignes if l["pertinent"] == "oui")
    assert len({e.post_id for e in ex}) == len(ex)
    assert all(e.cible is None for e in ex)


def test_cible_en_double_comptee_une_fois():
    ligne = {"post_id": "x", "text": "texte inventé", "pertinent": "oui", "emotion": "neutre",
             "cibles": [{"entite": "lfi", "stance": "pour"}, {"entite": "lfi", "stance": "contre"}]}
    ex = donnees.construire_exemples([ligne], "stance")
    assert [(e.cible, e.etiquette) for e in ex] == [("lfi", "pour")]


def test_decoupe_reproductible_disjointe_par_post(lignes):
    ex = donnees.construire_exemples(lignes, "stance")
    a_train, a_val = donnees.decouper(ex, 0.2, graine=7)
    b_train, b_val = donnees.decouper(ex, 0.2, graine=7)
    assert a_train == b_train and a_val == b_val                       # graine fixe
    assert {e.post_id for e in a_train}.isdisjoint({e.post_id for e in a_val})   # jamais un post des deux côtés
    assert len(a_train) + len(a_val) == len(ex)
    assert 0.1 < len(a_val) / len(ex) < 0.35
    _, autre_val = donnees.decouper(ex, 0.2, graine=8)
    assert autre_val != a_val                                          # la graine compte


def test_decoupe_stratifiee_garde_les_classes_dans_les_deux_cotes(lignes):
    ex = donnees.construire_exemples(lignes, "stance")
    train, val = donnees.decouper(ex, 0.2)
    assert set(donnees.effectifs(train)) == set(donnees.effectifs(val)) == set(donnees.etiquettes("stance"))


def test_echantillon_epoque_plafonne_les_classes_et_change_a_chaque_tirage(lignes):
    ex = donnees.construire_exemples(lignes, "stance")
    rng = random.Random(0)
    e1 = donnees.echantillon_epoque(ex, 5, rng)
    e2 = donnees.echantillon_epoque(ex, 5, rng)
    assert max(donnees.effectifs(e1).values()) <= 5
    assert set(donnees.effectifs(e1)) == set(donnees.effectifs(ex))     # aucune classe disparaît
    assert e1 != e2                                                     # tirage neuf à chaque époque
    assert donnees.echantillon_epoque(ex, None, rng) == ex              # pas de plafond : tout


def test_poids_classes():
    indices = [0] * 80 + [1] * 15 + [2] * 5
    assert donnees.poids_classes(indices, 3, 0) == [1.0, 1.0, 1.0]
    w = donnees.poids_classes(indices, 3, 1.0)
    assert w[0] < w[1] < w[2]
    assert w[2] / w[0] == pytest.approx(16.0)                           # rapport des effectifs
    moyenne = sum(w[c] * n for c, n in ((0, 80), (1, 15), (2, 5))) / 100
    assert moyenne == pytest.approx(1.0)                                # l'échelle de la perte ne change pas
    doux = donnees.poids_classes(indices, 3, 0.5)
    assert doux[2] / doux[0] == pytest.approx(4.0)                      # racine carrée du rapport


def test_nom_cible():
    assert donnees.nom_cible("le pen") == "Le Pen"
    assert donnees.nom_cible("lfi") == "LFI"
    assert donnees.nom_cible("eelv") == "EELV"
    assert donnees.nom_cible("dupont-aignan") == "Dupont-Aignan"
    assert donnees.nom_cible("groupe-politique") == "Groupe politique"
    assert donnees.nom_cible("modem") == "Modem"
    assert donnees.nom_cible("melenchon", {"id": "melenchon", "nom": "Mélenchon"}) == "Mélenchon"
    noms = donnees.noms_cibles()
    # Le champ `nom` du lexique fait foi (ici avec la casse de la donnée, pas celle de l'id).
    assert noms["rassemblement national"] == "Rassemblement national"
    assert noms["gouvernement"] == "Gouvernement"
    # Une entité sans champ `nom` retombe sur le nom lisible dérivé de son id.
    assert donnees.noms_cibles([{"id": "modem"}])["modem"] == "Modem"
    assert donnees.noms_cibles([{"id": "x-y", "nom": "Ça Compte"}])["x-y"] == "Ça Compte"


def test_entree_modele_et_normalisation_du_contrat():
    noms = {"melenchon": "Mélenchon"}
    assert donnees.entree_modele("Élection à Lyon", "melenchon", noms) == ("Mélenchon", "Élection à Lyon")
    assert donnees.entree_modele("Élection à Lyon", None, noms) == ("Élection à Lyon", None)
    assert donnees.entree_modele("Élection à Lyon", "melenchon", noms, normaliser=True) == \
        ("melenchon", "election a lyon")
    assert donnees.normaliser_contrat("ÇA Été") == "ca ete"


def test_charger_lignes_exige_la_source(tmp_path):
    chemin = tmp_path / "x.jsonl"
    outils.ecrire_jsonl(chemin, outils.lignes_factices(5, source="gold"))
    with pytest.raises(ValueError, match="source"):
        donnees.charger_lignes(chemin, "silver")
    assert len(donnees.charger_lignes(chemin, "gold")) == 5


def test_lire_jsonl_refuse_une_ligne_corrompue(tmp_path):
    chemin = tmp_path / "x.jsonl"
    chemin.write_text('{"post_id": "a"}\n{pas du json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="ligne 2"):
        donnees.lire_jsonl(chemin)


# ------------------------------------------------------------------ garde-fou
def test_garde_fou_accepte_un_silver_propre(corpus):
    lignes = donnees.charger_lignes(corpus / "annotation" / "train_silver.jsonl")
    assert donnees.verifier_garde_fou(lignes, corpus) == 18             # 8 du pilote + 10 de l'évaluation


@pytest.mark.parametrize("intrus", ["ev3", "pil2"])
def test_garde_fou_refuse_un_post_du_pilote_ou_de_l_evaluation(corpus, intrus):
    lignes = outils.lignes_factices(10)
    lignes[0]["post_id"] = intrus
    with pytest.raises(ValueError, match="pilote ou de l'évaluation"):
        donnees.verifier_garde_fou(lignes, corpus)


def test_garde_fou_refuse_un_jeu_fige_modifie(corpus):
    chemin = corpus / "annotation" / "eval_fige.json"
    fige = json.loads(chemin.read_text(encoding="utf-8"))
    fige["ids"].append("ev99")                                          # l'empreinte ne correspond plus
    chemin.write_text(json.dumps(fige), encoding="utf-8")
    with pytest.raises(ValueError, match="modifié"):
        donnees.verifier_garde_fou([], corpus)


def test_garde_fou_refuse_un_jeu_non_fige(corpus):
    (corpus / "annotation" / "eval_fige.json").unlink()
    with pytest.raises(ValueError, match="pas figé"):
        donnees.verifier_garde_fou([], corpus)


def test_emotion_trois_classes_schema_intact():
    assert donnees.etiquettes("emotion", emotion_reduite=True) == ["joie", "colere", "neutre"]
    assert donnees.etiquettes("emotion") == ["joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre"]


def test_emotion_trois_classes_ne_change_pas_la_stance():
    assert donnees.etiquettes("stance", emotion_reduite=True) == donnees.etiquettes("stance")


def _ligne_emotion(post_id, emotion, pertinent="oui"):
    return {"post_id": post_id, "text": f"texte inventé {post_id}", "pertinent": pertinent,
            "emotion": emotion, "cibles": []}


def test_emotion_reduite_projette_et_ecarte_surprise():
    lignes = [_ligne_emotion(f"p{i}", e) for i, e in enumerate(
        ["joie", "colere", "degout", "peur", "tristesse", "surprise", "neutre"])]
    origine = copy.deepcopy(lignes)
    ex = donnees.construire_exemples(lignes, "emotion", emotion_reduite=True)
    assert [e.etiquette for e in ex] == ["joie", "colere", "colere", "colere", "colere", "neutre"]
    assert {e.post_id for e in ex}.isdisjoint({"p5"})                  # surprise exclue
    assert lignes == origine                                           # données d'origine intactes
    assert len(donnees.construire_exemples(lignes, "emotion")) == 7    # sans l'option : rien ne change


def test_emotion_reduite_ecarte_absence_d_emotion():
    lignes = [_ligne_emotion("a", None), _ligne_emotion("b", "inconnue"), _ligne_emotion("c", "joie")]
    ex = donnees.construire_exemples(lignes, "emotion", emotion_reduite=True)
    assert [e.post_id for e in ex] == ["c"]


def test_emotion_reduite_sur_le_corpus_factice(lignes):
    ex = donnees.construire_exemples(lignes, "emotion", emotion_reduite=True)
    assert {e.etiquette for e in ex} <= {"joie", "colere", "neutre"}
    attendu = sum(1 for l in lignes if l["pertinent"] == "oui" and l["emotion"] != "surprise")
    assert len(ex) == attendu > 0


def test_emotion_reduite_option_sans_effet_sur_la_stance(lignes):
    assert donnees.construire_exemples(lignes, "stance", emotion_reduite=True) == \
        donnees.construire_exemples(lignes, "stance")


def test_marqueurs_des_lots_retires_insensible_a_la_casse():
    assert donnees.retirer_marqueurs_lots("voir [url] puis [MENTION] et [Url]") == "voir   puis   et  "
    assert donnees.retirer_marqueurs_lots("[urlx] [mentions]") == "[urlx] [mentions]"   # motif exact seulement


def test_preparer_texte_retire_marqueurs_puis_nettoie():
    brut = "Voir https://exemple.org/a [url] @alice.bsky.social [mention] did:plc:abc123 Élève  ÉTÉ"
    assert donnees.preparer_texte(brut) == "voir eleve ete"
    assert donnees.preparer_texte(None) == "" and donnees.preparer_texte("  [url]  ") == ""


def test_preparer_texte_idempotente():
    textes = ["Bravo ! https://x.y/z @bob.test", "Noël  [mention] à Lyon [URL]", "www.exemple.fr did:plc:q1",
              "Déjà propre.", "", "[url] [mention]", "Très   bien\tmerci"]
    for t in textes:
        une_fois = donnees.preparer_texte(t)
        assert donnees.preparer_texte(une_fois) == une_fois


def test_exemples_recoivent_le_texte_prepare_et_ecartent_le_vide():
    lignes = [
        {"post_id": "a", "text": "Oui [url] Lyon", "pertinent": "oui", "emotion": "joie",
         "cibles": [{"entite": "lfi", "stance": "pour"}]},
        {"post_id": "b", "text": "[url] @carol.test", "pertinent": "oui", "emotion": "joie",
         "cibles": [{"entite": "lfi", "stance": "pour"}]},
    ]
    ex = donnees.construire_exemples(lignes, "stance")
    assert [(e.post_id, e.texte, e.cible) for e in ex] == [("a", "oui lyon", "lfi")]
    ex_e = donnees.construire_exemples(lignes, "emotion")
    assert [e.texte for e in ex_e] == ["oui lyon"]
