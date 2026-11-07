import math

import pytest

from annotation.agreement import agreement, cohen_kappa, disagreements, fleiss_kappa

THEMES = ["economie", "immigration"]


def test_cohen_valeur_connue():
    # exemple classique : 20 oui/oui, 5 oui/non, 10 non/oui, 15 non/non -> kappa = 0.4
    a = ["o"] * 25 + ["n"] * 25
    b = ["o"] * 20 + ["n"] * 5 + ["o"] * 10 + ["n"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)


def test_cohen_parfait_et_indefini():
    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)
    assert math.isnan(cohen_kappa(["a", "a"], ["a", "a"]))
    assert math.isnan(cohen_kappa([], []))


def test_fleiss_egal_cas_connu_et_proche_de_cohen_a_2():
    # valeurs publiées (Wikipedia, 10 items, 14 évaluateurs, 5 catégories) : kappa = 0.210
    counts = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
              [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    mat = [[c for c, n in enumerate(row) for _ in range(n)] for row in counts]
    assert fleiss_kappa(mat) == pytest.approx(0.210, abs=1e-3)
    a = ["o", "o", "n", "n", "o", "n"]
    b = ["o", "n", "n", "n", "o", "o"]
    assert fleiss_kappa([[x, y] for x, y in zip(a, b)]) == pytest.approx(cohen_kappa(a, b), abs=0.1)


def rec(pid, pert="oui", emotion="colere", cibles=(), themes=(), ironie="non", regle="non"):
    return {"post_id": pid, "pertinent": pert, "emotion": emotion, "ironie": ironie, "regle_suffit": regle,
            "cibles": [{"entite": e, "stance": s} for e, s in cibles], "themes": list(themes)}


def test_agreement_posts_communs_et_champs():
    A = {"1": rec("1", cibles=[("x", "pour")]), "2": rec("2", emotion="joie"), "3": rec("3"), "4": rec("4", pert="non")}
    B = {"1": rec("1", cibles=[("x", "contre")]), "2": rec("2", emotion="joie"), "3": rec("3", emotion="peur")}
    r = agreement({"anna": A, "ben": B}, THEMES)
    assert r["n_posts"] == 3  # le post 4 n'est pas annoté par Ben
    assert r["champs"]["pertinent"]["accord_brut"] == 1.0
    assert r["champs"]["emotion"]["accord_brut"] == pytest.approx(2 / 3)
    c = r["champs"]["cibles"]  # un seul item (post 1, x) : désaccord de stance
    assert c["n_items"] == 1 and c["accord_brut"] == 0.0


def test_agreement_cibles_absent_compte_comme_desaccord():
    A = {"1": rec("1", cibles=[("x", "pour")])}
    B = {"1": rec("1")}
    r = agreement({"a": A, "b": B}, THEMES)
    assert r["champs"]["cibles"]["accord_brut"] == 0.0


def test_agreement_trois_annotateurs_et_themes():
    d = {n: {str(i): rec(str(i), themes=["economie"] if i % 2 else []) for i in range(6)} for n in "abc"}
    r = agreement(d, THEMES)
    assert r["champs"]["themes"]["fleiss"] == pytest.approx(1.0)
    assert len(r["champs"]["emotion"]["cohen"]) == 3


def test_desaccords_listes():
    A = {"1": rec("1", emotion="joie"), "2": rec("2")}
    B = {"1": rec("1", emotion="peur"), "2": rec("2")}
    dis = disagreements({"a": A, "b": B}, {"1": {"text": "texte inventé"}}, THEMES)
    assert [d["post_id"] for d in dis] == ["1"] and dis[0]["champs"] == ["emotion"]


def test_agreement_nouvelles_valeurs_mention_et_doute():
    # mention vs neutre est un désaccord ; stance vide (doute) ne plante pas
    A = {"1": rec("1", cibles=[("x", "mention")]), "2": rec("2", pert="doute", emotion=None, cibles=[("x", None)])}
    B = {"1": rec("1", cibles=[("x", "neutre")]), "2": rec("2", pert="doute", emotion=None, cibles=[("x", None)])}
    r = agreement({"a": A, "b": B}, THEMES)
    assert r["champs"]["cibles"]["n_items"] == 2 and r["champs"]["cibles"]["accord_brut"] == 0.5
    assert r["champs"]["pertinent"]["accord_brut"] == 1.0
    assert r["champs"]["emotion"]["accord_brut"] == 1.0  # "vide" des deux côtés
