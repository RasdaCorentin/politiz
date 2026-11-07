"""Forme du JSON `tableau` v4 : identique à celle des exemples du contrat, vue normale et vue vide.

Aucun ClickHouse : les lignes sont fictives et écrites ici.
"""

import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import calculs as k
from camps import charger_lexique
from config import depuis_env
from donnees import Brut, EtatBase
from modele import construire
from serialisation import iso, serialiser

MAINTENANT = datetime(2026, 10, 19, 10, 2, 30, tzinfo=timezone.utc)
PREMIERE = datetime(2026, 10, 5, 10, 5, tzinfo=timezone.utc)
CONTRAT = Path(__file__).resolve().parents[2] / "contrat"
LEXIQUE = """
entites:
  - {id: alice-fictive, nom: "Alice Fictive", type: candidat, camp: gauche}
  - {id: beta-fictif, type: candidat, camp: droite}
  - {id: gamma-fictif, type: candidat, camp: null}
  - {id: delta-fictif, nom: "Delta Fictif", type: candidat, camp: centre}
  - {id: parti-fictif, type: parti, camp: gauche}
"""
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
# Dictionnaires dont les clés viennent des données (candidats), non du contrat.
DYNAMIQUE = {("series",), ("barre", "manquants")}


def _type(x):
    if isinstance(x, bool):
        return "booleen"
    if isinstance(x, (int, float)):
        return "nombre"
    return "texte" if isinstance(x, str) else type(x).__name__


def meme_forme(a, b, chemin=()):
    """Mêmes clés et mêmes types, récursivement. `null` accepte tout type (valeur absente)."""
    if isinstance(a, dict):
        assert isinstance(b, dict), chemin
        if chemin in DYNAMIQUE:
            assert bool(a) == bool(b), chemin
            if a and b:
                meme_forme(next(iter(a.values())), next(iter(b.values())), chemin + ("*",))
            return
        assert set(a) == set(b), (chemin, set(a) ^ set(b))
        for cle in a:
            meme_forme(a[cle], b[cle], chemin + (cle,))
    elif isinstance(a, list):
        assert isinstance(b, list), chemin
        assert bool(a) == bool(b), chemin
        for x in a:
            meme_forme(x, b[0], chemin + ("[]",))
    else:
        assert a is None or b is None or _type(a) == _type(b), (chemin, _type(a), _type(b))


def _cles_interdites(x, chemin=""):
    """Aucune clé ne désigne un texte de post, un identifiant d'auteur ou un handle."""
    if isinstance(x, dict):
        for cle, v in x.items():
            assert not re.search(r"(^|_)(did|handle|auteur|texte|text|author)(_|$)", cle, re.I), chemin + "." + cle
            _cles_interdites(v, chemin + "." + cle)
    elif isinstance(x, list):
        for v in x:
            _cles_interdites(v, chemin)


def _heures(x):
    """Toute heure du JSON est en UTC `…Z`."""
    if isinstance(x, dict):
        for v in x.values():
            _heures(v)
    elif isinstance(x, list):
        for v in x:
            _heures(v)
    elif isinstance(x, str) and re.match(r"^\d{4}-\d\d-\d\dT", x):
        assert ISO.match(x), x


def _vue_normale(tmp_path):
    (tmp_path / "entites.yaml").write_text(LEXIQUE, encoding="utf-8")
    lexique = charger_lexique(tmp_path)
    b = k.bornes("7j", MAINTENANT, PREMIERE)
    t = b.tranches[-1]  # la tranche en cours
    maj = MAINTENANT - timedelta(seconds=45)
    brut = Brut(
        bornes=b,
        etat=EtatBase(premiere=PREMIERE, derniere_maj=maj),
        cibles=[
            (t, "alice-fictive", "pour", 30), (t, "alice-fictive", "contre", 10), (t, "alice-fictive", "mention", 4),
            (t, "beta-fictif", "pour", 8), (t, "beta-fictif", "contre", 25),
            (t, "gamma-fictif", "pour", 5), (t, "gamma-fictif", "contre", 5),
            (t, "delta-fictif", "pour", 6), (t, "delta-fictif", "contre", 4),
            (t, "parti-fictif", "pour", 2), (t, "parti-fictif", "contre", 3), (t, "parti-fictif", "ambigu", 1),
        ],
        cibles_precedentes=[(b.precedente[0], "alice-fictive", "pour", 3)],
        posts=[(t, "positif", "joie", 12), (t, "negatif", "colere", 9), (t, "neutre", "non_evalue", 4)],
        themes=[("economie", 40), ("social-retraites", 10), ("autre", 5)],
        pipeline=[(t, 50, 600_000, maj)],
        scoreur="lexique-v1",
        croisements_themes=[
            ("alice-fictive", "economie", 40), ("alice-fictive", "social-retraites", 10),
            ("parti-fictif", "economie", 6), ("inconnu-fictif", "economie", 99), ("alice-fictive", "", 5),
        ],
        croisements_emotions=[
            ("alice-fictive", "colere", 12), ("alice-fictive", "non_evalue", 30),
            ("parti-fictif", "joie", 2), ("parti-fictif", "", 7),
        ],
        adjectifs=[
            ("alice-fictive", "pour", "courageux", 14), ("alice-fictive", "contre", "flou", 11),
            ("alice-fictive", "pour", "rare", 2), ("beta-fictif", "contre", "arrogant", 7),
        ],
        scoreur_adjectifs="lexique-v1",
        couverture_adjectifs=(t, t),
        posts_hors_adjectifs=8,
    )
    return construire(brut, lexique, 20, 5, 30, MAINTENANT)


def _vue_vide(tmp_path):
    (tmp_path / "entites.yaml").write_text(LEXIQUE, encoding="utf-8")
    b = k.bornes("7j", MAINTENANT, None)
    brut = Brut(bornes=b, etat=EtatBase(premiere=None, derniere_maj=None), cibles=[], cibles_precedentes=[], posts=[], themes=[], pipeline=[])
    return construire(brut, charger_lexique(tmp_path), 20, 5, 30, MAINTENANT)


def _exemple(nom):
    return json.loads((CONTRAT / nom).read_text(encoding="utf-8"))


def test_forme_vue_normale_identique_a_l_exemple(tmp_path):
    cfg = depuis_env({"DASHBOARD_BANDEAU": "Données synthétiques"})
    corps = serialiser(_vue_normale(tmp_path), cfg, MAINTENANT)
    meme_forme(corps, _exemple("tableau-v4.normal.json"))
    _cles_interdites(corps)
    _heures(corps)


def test_forme_vue_vide_identique_a_l_exemple(tmp_path):
    cfg = depuis_env({})
    corps = serialiser(_vue_vide(tmp_path), cfg, MAINTENANT)
    meme_forme(corps, _exemple("tableau-v4.vide.json"))
    assert corps["bandeau"] is None and corps["etat"]["base_vide"] is True
    _heures(corps)


def test_valeurs_du_contrat(tmp_path):
    cfg = depuis_env({"DASHBOARD_BANDEAU": "Données synthétiques"})
    corps = serialiser(_vue_normale(tmp_path), cfg, MAINTENANT)
    assert corps["schema_version"] == 4 and corps["generated_at"] == "2026-10-19T10:02:30Z"
    assert corps["periode"]["code"] == "7j" and corps["periode"]["periodes"] == ["24h", "7j", "30j", "tout"]
    assert corps["periode"]["seuil_defaut"] == 20 and corps["periode"]["premiere_donnee"] == "2026-10-05T10:05:00Z"
    assert corps["barre"]["precedente"]["etat"] == "insuffisant"
    assert set(corps["emotions"]) == set(k.EMOTIONS)
    assert [t["libelle"] for t in corps["themes"]][:2] == ["Économie", "Social et retraites"]
    alice = corps["candidats"][0]
    assert alice["entite"] == "alice-fictive" and alice["rang"] == 1 and alice["nom"] == "Alice Fictive"
    assert alice["indice"] == (30 - 10) / 40
    assert corps["barre"]["etat"] == "ok" and corps["barre"]["camps"]["gauche"]["candidats"] == ["alice-fictive"]
    assert corps["non_classes_evalues"] == 10  # gamma-fictif, camp null
    assert "alice-fictive" in corps["series"] and corps["series"]["alice-fictive"][-1]["indice"] == alice["indice"]


def test_croisements_valeurs_du_contrat(tmp_path):
    corps = serialiser(_vue_normale(tmp_path), depuis_env({}), MAINTENANT)
    assert corps["croisements"]["scoreur"] == "lexique-v1"
    assert corps["croisements"]["themes"] == [
        {"entite": "alice-fictive", "theme": "economie", "libelle": "Économie", "posts": 40},
        {"entite": "alice-fictive", "theme": "social-retraites", "libelle": "Social et retraites", "posts": 10},
        {"entite": "parti-fictif", "theme": "economie", "libelle": "Économie", "posts": 6},
    ]  # inconnu-fictif (hors réponse) et valeurs vides exclus
    assert corps["croisements"]["emotions"] == [  # non_evalue (30) et valeur vide exclues
        {"entite": "alice-fictive", "emotion": "colere", "occurrences": 12},
        {"entite": "parti-fictif", "emotion": "joie", "occurrences": 2},
    ]


def test_libelle_theme_meme_fonction_pour_themes_et_croisements(tmp_path):
    """Même thème, même libellé dans `themes` (v2) et dans `croisements.themes` (v3), connu ou inconnu."""
    vue = dataclasses.replace(
        _vue_normale(tmp_path),
        themes=[("economie", 40), ("theme-inconnu-fictif", 5)],
        croisements=k.Croisements(
            scoreur="lexique-v1",
            themes=(("alice-fictive", "economie", 40), ("alice-fictive", "theme-inconnu-fictif", 2)),
        ),
    )
    corps = serialiser(vue, depuis_env({}), MAINTENANT)
    par_theme_v2 = {t["theme"]: t["libelle"] for t in corps["themes"]}
    par_theme_v3 = {t["theme"]: t["libelle"] for t in corps["croisements"]["themes"]}
    assert par_theme_v2 == par_theme_v3 == {"economie": "Économie", "theme-inconnu-fictif": "Theme inconnu fictif"}


def test_vue_vide_sans_bandeau_et_sans_derniere_maj(tmp_path):
    corps = serialiser(_vue_vide(tmp_path), depuis_env({}), MAINTENANT)
    assert corps["etat"]["derniere_maj"] is None and corps["etat"]["fraicheur"] == "unknown"
    assert corps["barre"]["manquants"] == {"gauche": 20, "droite": 20}
    assert corps["croisements"] == {"scoreur": None, "themes": [], "emotions": []}


def test_serie_camps_par_tranche(tmp_path):
    corps = serialiser(_vue_normale(tmp_path), depuis_env({}), MAINTENANT)
    assert len(corps["serie_camps"]) == len(corps["tranches"])
    derniere = corps["serie_camps"][-1]
    assert derniere["gauche"] == {"pour": 30, "contre": 10}  # alice-fictive
    assert derniere["droite"] == {"pour": 8, "contre": 25}  # beta-fictif
    assert derniere["centre"] == {"pour": 6, "contre": 4}  # delta-fictif ; gamma (sans camp) et le parti n'entrent pas
    assert all(t[c] == {"pour": 0, "contre": 0} for t in corps["serie_camps"][:-1] for c in ("gauche", "centre", "droite"))


def test_adjectifs_du_contrat(tmp_path):
    corps = serialiser(_vue_normale(tmp_path), depuis_env({}), MAINTENANT)
    assert corps["adjectifs"]["scoreur"] == "lexique-v1"
    assert corps["adjectifs"]["lignes"] == [
        {"entite": "alice-fictive", "stance": "pour", "adjectif": "courageux", "posts": 14},
        {"entite": "alice-fictive", "stance": "contre", "adjectif": "flou", "posts": 11},
        {"entite": "beta-fictif", "stance": "contre", "adjectif": "arrogant", "posts": 7},
    ]  # « rare » (2 posts) reste sous le minimum
    debut = _vue_normale(tmp_path).adjectifs.debut
    assert corps["adjectifs"]["couverture"] == {
        "debut": iso(debut), "fin": iso(debut + timedelta(minutes=5)), "posts_hors": 8}


def test_adjectifs_null_sans_table(tmp_path):
    corps = serialiser(_vue_vide(tmp_path), depuis_env({}), MAINTENANT)
    assert corps["adjectifs"] is None


def test_forme_catalogue_identique_a_l_exemple():
    from donnees import Evenement
    from serialisation import serialiser_evenements

    liste = [
        Evenement("x1", MAINTENANT - timedelta(days=2), "Titre inventé", "loi", "exemple", "https://example.org/x"),
        Evenement("x2", MAINTENANT - timedelta(days=5), "Autre titre inventé", "greve", "exemple", None),
    ]
    corps = serialiser_evenements(True, liste, MAINTENANT)
    meme_forme(corps, _exemple("evenements-v1.json"))
    _heures(corps)
    assert corps["evenements"][0]["date"] == "2026-10-17T10:02:30Z"
    assert serialiser_evenements(False, [], MAINTENANT)["disponible"] is False
