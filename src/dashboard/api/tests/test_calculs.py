from datetime import datetime, timedelta, timezone

import pytest

import calculs as k

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def lignes(**par_entite):
    """`entite=(pour, contre)` : une ligne par stance, dans la fenêtre T0."""
    out = []
    for e, (p, c) in par_entite.items():
        out += [(T0, e, "pour", p), (T0, e, "contre", c)]
    return out


def test_indice_net():
    assert k.indice_net(3, 1) == 0.5
    assert k.indice_net(0, 4) == -1.0
    assert k.indice_net(0, 0) is None


def test_couverture():
    assert k.couverture(5, 100) == 0.05
    assert k.couverture(0, 0) is None


def test_agreger_somme_et_stance_inconnue():
    c = k.agreger_cibles([(T0, "a", "pour", 2), (T0, "a", "pour", 3), (T0, "a", "bizarre", 4), (T0, "a", "contre", 1)])["a"]
    assert (c.pour, c.contre, c.non_evalue) == (5, 1, 4)
    assert c.cites == 10 and c.evalues == 6 and c.couverture == 0.6


def _position(seuil, camps, **par_entite):
    comptes = k.agreger_cibles(lignes(**par_entite))
    camp_de = {"g1": "gauche", "g2": "gauche", "d1": "droite", "c1": "centre"}
    par_camp = k.resultats_par_camp(comptes, camp_de)
    return k.position_barre(par_camp, seuil, camps)


TOUS = ("gauche", "centre", "droite")


def test_position_droite_mieux_accueillie():
    p = _position(10, TOUS, g1=(10, 30), g2=(10, 10), d1=(40, 10))
    # N gauche = (20-40)/60 ; N droite = 30/50 ; p = (0,6 + 0,3333) / 2
    assert p.etat == "ok"
    assert p.valeur == pytest.approx((0.6 + 20 / 60) / 2)
    assert p.bas < p.valeur < p.haut
    assert -1 <= p.bas and p.haut <= 1


def test_volume_ne_deplace_pas_la_barre():
    a = _position(10, TOUS, g1=(10, 10), d1=(30, 10))
    b = _position(10, TOUS, g1=(100, 100), g2=(0, 0), d1=(300, 100))
    assert a.valeur == pytest.approx(b.valeur)


def test_negativite_generale_ne_deplace_pas():
    assert _position(10, TOUS, g1=(5, 45), d1=(5, 45)).valeur == pytest.approx(0.0)


def test_centre_hors_calcul():
    sans = _position(10, TOUS, g1=(10, 10), d1=(20, 10))
    avec = _position(10, TOUS, g1=(10, 10), d1=(20, 10), c1=(0, 50))
    assert sans.valeur == avec.valeur
    assert avec.centre.contre == 50


def test_seuil_masque_la_barre_et_chiffre_le_manque():
    p = _position(20, TOUS, g1=(5, 5), d1=(30, 10))
    assert p.etat == "insuffisant" and p.valeur is None
    assert p.manquants == {"gauche": 10}


def test_seuil_exact_affiche():
    assert _position(10, TOUS, g1=(5, 5), d1=(5, 5)).etat == "ok"


def test_aucun_camp_renseigne():
    # Lexique sans rattachement (camp: null partout) : la barre ne s'affiche pas, sans erreur.
    comptes = k.agreger_cibles(lignes(x=(50, 50), y=(50, 50)))
    par_camp = k.resultats_par_camp(comptes, {})
    p = k.position_barre(par_camp, 5, set())
    assert p.etat == "aucun_camp" and p.valeur is None
    assert all(r.evalues == 0 for r in par_camp.values())


def test_marge_decroit_avec_le_volume():
    petit = _position(1, TOUS, g1=(10, 10), d1=(10, 10))
    grand = _position(1, TOUS, g1=(100, 100), d1=(100, 100))
    assert (petit.haut - petit.bas) > (grand.haut - grand.bas)
    assert k.marge_position(petit.gauche, petit.droite) == pytest.approx(1.96 * 0.5 * (2 * (4 * 0.5 * 0.5 / 22)) ** 0.5, rel=0.05)


def test_classement_seuil_et_ordre():
    comptes = k.agreger_cibles(lignes(a=(30, 10), b=(5, 0), c=(10, 30), d=(25, 5)))
    r = k.classer(comptes, 20)
    assert [l.entite for l in r if l.rang] == ["d", "a", "c"]
    assert r[-1].entite == "b" and r[-1].rang is None


def test_classement_filtre_ids():
    comptes = k.agreger_cibles(lignes(a=(30, 10), p=(30, 0)))
    assert [l.entite for l in k.classer(comptes, 1, ids=["a"])] == ["a"]


def test_serie_cumulee_dernier_point_egale_indice_et_masque_sous_seuil():
    tranches = k.tranches_entre(T0, T0 + timedelta(hours=3), 60)
    rows = [(T0, "a", "pour", 6), (T0 + timedelta(minutes=10), "a", "contre", 2), (T0 + timedelta(hours=1, minutes=10), "a", "pour", 4)]
    pts = k.serie_indice_cumulee(rows, "a", tranches, T0 + timedelta(hours=3), seuil=10)
    assert len(pts) == 3 and pts[-1].fin == T0 + timedelta(hours=3)
    assert pts[0].indice is None  # 8 évalués < 10
    assert pts[1].indice == k.indice_net(10, 2)
    assert pts[-1].indice == k.agreger_cibles(rows)["a"].indice


def test_ton_et_emotions():
    ton = k.repartition_ton([(T0, "positif", "joie", 3), (T0, "negatif", "colere", 5), (T0, "non_evalue", "non_evalue", 2)])
    assert (ton.positif, ton.negatif, ton.evalues, ton.total) == (3, 5, 8, 10) and ton.couverture == 0.8
    par, sans = k.repartition_emotions([(T0, "x", "joie", 3), (T0, "x", "non_evalue", 2), (T0, "x", "inconnue", 1)])
    assert par["joie"] == 3 and sans == 3


def test_themes_autre_en_dernier():
    assert k.classer_themes([("autre", 99), ("a", 3), ("b", 5), ("a", 4)]) == [("a", 7), ("b", 5), ("autre", 99)]


def test_fraicheur():
    now = T0
    assert k.etat_fraicheur(None, now, 5, 30).etat == "unknown"
    assert k.etat_fraicheur(now - timedelta(minutes=4), now, 5, 30).etat == "ok"
    assert k.etat_fraicheur(now - timedelta(minutes=20), now, 5, 30).etat == "warn"
    assert k.etat_fraicheur(now - timedelta(minutes=45), now, 5, 30).etat == "critical"


def test_latence_moyenne():
    p = k.resume_pipeline([(T0, 10, 25_000, T0), (T0, 10, 35_000, T0 + timedelta(minutes=1))])
    assert p.latence_moyenne_s == 3.0 and p.derniere_maj == T0 + timedelta(minutes=1)
    assert k.Pipeline().latence_moyenne_s is None


# --- croisements (tableau v3) : entités fictives ----------------------------------------------------
ORDRE = ["alice-fictive", "beta-fictif", "parti-fictif-b"]  # candidats puis partis de la réponse


def test_scoreur_le_plus_recent_l_emporte():
    assert k.scoreur_recent([("lexique-v1", T0), ("modele-fictif", T0 + timedelta(minutes=5))]) == "modele-fictif"


def test_scoreur_egalite_alphabetique_et_scoreur_vide_ignore():
    assert k.scoreur_recent([("zeta-fictif", T0), ("alpha-fictif", T0)]) == "alpha-fictif"
    assert k.scoreur_recent([("", T0 + timedelta(hours=1)), ("lexique-v1", T0)]) == "lexique-v1"


def test_scoreur_sans_ligne_donne_none():
    assert k.scoreur_recent([]) is None
    assert k.scoreur_recent([("", T0)]) is None


def test_totaux_par_entite_somme_par_entite_et_valeur():
    lignes = [("alice-fictive", "economie", 2), ("alice-fictive", "economie", 3), ("alice-fictive", "securite", 1)]
    assert k.totaux_par_entite(lignes, ORDRE) == (("alice-fictive", "economie", 5), ("alice-fictive", "securite", 1))


def test_totaux_par_entite_exclut_entite_vide_hors_reponse_et_valeur_vide():
    lignes = [
        ("", "economie", 9), ("inconnu-fictif", "economie", 9), ("beta-fictif", "", 9),
        ("beta-fictif", "securite", 0), ("beta-fictif", "securite", 4),
    ]
    assert k.totaux_par_entite(lignes, ORDRE) == (("beta-fictif", "securite", 4),)


def test_totaux_par_entite_ordre_entite_puis_posts_puis_valeur():
    lignes = [
        ("parti-fictif-b", "joie", 50), ("beta-fictif", "zeta", 3), ("beta-fictif", "alpha", 3),
        ("alice-fictive", "colere", 1), ("beta-fictif", "joie", 7),
    ]
    assert k.totaux_par_entite(lignes, ORDRE) == (
        ("alice-fictive", "colere", 1),
        ("beta-fictif", "joie", 7),
        ("beta-fictif", "alpha", 3),
        ("beta-fictif", "zeta", 3),
        ("parti-fictif-b", "joie", 50),
    )


def test_totaux_par_entite_un_post_a_deux_themes_compte_dans_les_deux():
    lignes = [("alice-fictive", "economie", 1), ("alice-fictive", "securite", 1)]  # un post, deux thèmes
    assert sum(n for _, _, n in k.totaux_par_entite(lignes, ORDRE)) == 2


def test_totaux_par_entite_exclut_les_valeurs_indiquees():
    lignes = [("alice-fictive", "non_evalue", 9), ("alice-fictive", "colere", 2)]  # non_evalue : pas une émotion
    assert k.totaux_par_entite(lignes, ORDRE, exclues=frozenset({k.EMOTION_NON_DETECTEE})) == (("alice-fictive", "colere", 2),)


def test_fenetre_vide_donne_listes_vides():
    assert k.totaux_par_entite([], ORDRE) == ()
    assert k.Croisements().scoreur is None and k.Croisements().themes == () and k.Croisements().emotions == ()


# --- tableau v4 : séries par camp, adjectifs, liens du catalogue ---------------------------------
def test_serie_camps_somme_par_camp_et_ignore_partis_sans_camp_et_stances_non_evaluees():
    t0 = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    tranches = (t0, t0 + timedelta(hours=6))
    fin = t0 + timedelta(hours=12)
    lignes = [
        (t0, "a", "pour", 2), (t0, "a", "contre", 1), (t0, "b", "contre", 4),
        (t0 + timedelta(hours=7), "d", "contre", 9), (t0, "p", "contre", 50), (t0, "a", "mention", 7),
        (fin, "d", "contre", 100),  # hors période
    ]
    serie = k.serie_camps(lignes, {"a": "gauche", "b": "gauche", "d": "droite"}, tranches, fin)
    assert serie[0]["gauche"] == {"pour": 2, "contre": 5} and serie[0]["droite"] == {"pour": 0, "contre": 0}
    assert serie[1]["droite"] == {"pour": 0, "contre": 9} and serie[1]["centre"] == {"pour": 0, "contre": 0}


def test_adjectifs_minimum_maximum_et_ordre():
    lignes = [("b", "contre", "flou", 5), ("a", "contre", "dur", 4), ("a", "pour", "clair", 3), ("a", "pour", "net", 3),
              ("a", "pour", "vif", 2), ("a", "neutre", "calme", 9), ("x", "pour", "hors", 9), ("a", "pour", "", 9),
              ("a", "pour", "clair", 2)]
    assert k.adjectifs_par_entite(lignes, ["a", "b"]) == (
        ("a", "pour", "clair", 5), ("a", "pour", "net", 3), ("a", "contre", "dur", 4), ("b", "contre", "flou", 5),
    )
    assert k.adjectifs_par_entite(lignes, ["a", "b"], n_max=1) == (
        ("a", "pour", "clair", 5), ("a", "contre", "dur", 4), ("b", "contre", "flou", 5),
    )


def test_lien_sur_garde_http_et_https_seulement():
    assert k.lien_sur("https://example.org/a") == "https://example.org/a"
    assert k.lien_sur(" http://example.org ") == "http://example.org"
    assert k.lien_sur("javascript:alert(1)") is None and k.lien_sur("") is None and k.lien_sur(None) is None


def test_couverture_adjectifs_va_jusqu_a_la_fin_de_la_derniere_fenetre():
    premiere = datetime(2026, 10, 12, 4, 50, tzinfo=timezone.utc)
    derniere = datetime(2026, 10, 19, 16, 20, tzinfo=timezone.utc)
    assert k.couverture_adjectifs((premiere, derniere)) == (premiere, datetime(2026, 10, 19, 16, 25, tzinfo=timezone.utc))
    assert k.couverture_adjectifs(None) == (None, None)
