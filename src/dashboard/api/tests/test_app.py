"""Routes WSGI sans ClickHouse : `donnees.lire` et `donnees.ping` sont remplacés."""

import json
from datetime import datetime, timezone

import pytest

import donnees
from app import creer_app
from config import depuis_env
from donnees import Brut, ErreurBase, EtatBase

MAINTENANT = datetime(2026, 10, 19, 10, 2, 30, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "entites.yaml").write_text("entites: []\n", encoding="utf-8")
    return depuis_env({"LEXIQUE_DIR": str(tmp_path), "DASHBOARD_SEUIL_DEFAUT": "20"})


@pytest.fixture
def appels(monkeypatch):
    """Enregistre les codes de période lus ; réponse : une base vide (aucune fenêtre)."""
    journal = []
    monkeypatch.setattr(donnees, "etat_base", lambda cfg: EtatBase(premiere=None, derniere_maj=None))

    def lire(cfg, bornes, etat):
        journal.append(bornes.code if bornes.code != "perso" else ("perso", bornes.debut, bornes.fin))
        return Brut(bornes=bornes, etat=etat, cibles=[], cibles_precedentes=[], posts=[], themes=[], pipeline=[])

    monkeypatch.setattr(donnees, "lire", lire)
    return journal


def requete(app, methode="GET", chemin="/api/tableau", query="", entetes=None):
    statut, reponse = {}, {}

    def start_response(code, en_tetes):
        statut["code"] = code
        reponse["entetes"] = {k.lower(): v for k, v in en_tetes}

    environ = {"REQUEST_METHOD": methode, "PATH_INFO": chemin, "QUERY_STRING": query}
    if entetes:
        environ["HTTP_IF_NONE_MATCH"] = entetes
    corps = b"".join(app(environ, start_response))
    return statut["code"], reponse["entetes"], corps


@pytest.fixture
def app(cfg):
    return creer_app(cfg, horloge=lambda: MAINTENANT)


def test_tableau_200_et_en_tetes(app, appels):
    code, h, corps = requete(app, query="periode=24h")
    assert code == "200 OK" and appels == ["24h"]
    assert h["cache-control"] == "no-store" and h["etag"].startswith('"') and h["x-generated-at"] == "2026-10-19T10:02:30Z"
    doc = json.loads(corps)
    assert doc["schema_version"] == 4 and doc["periode"]["code"] == "24h" and doc["periode"]["seuil_defaut"] == 20
    assert doc["croisements"] == {"scoreur": None, "themes": [], "emotions": []}  # base vide dans ce test
    assert int(h["content-length"]) == len(corps)


def test_periode_absente_vaut_7j(app, appels):
    requete(app)
    assert appels == ["7j"]


def test_plage_de_dates_vaut_perso(app, appels):
    code, _, corps = requete(app, query="debut=2026-10-01&fin=2026-10-03")
    assert code == "200 OK" and json.loads(corps)["periode"]["code"] == "perso"
    assert appels[0][0] == "perso" and appels[0][1].isoformat() == "2026-09-30T22:00:00+00:00"


def test_seuil_explicite_et_valeurs_limites(app, appels):
    for seuil in ("1", "10000"):
        code, _, corps = requete(app, query=f"seuil={seuil}")
        assert code == "200 OK" and json.loads(corps)["periode"]["seuil"] == int(seuil)


def test_304_si_etag_identique(app, appels):
    _, h, _ = requete(app, query="periode=7j")
    code, h2, corps = requete(app, query="periode=7j", entetes=h["etag"])
    assert code == "304 Not Modified" and corps == b""
    assert h2["x-generated-at"] == "2026-10-19T10:02:30Z" and h2["cache-control"] == "no-store"


def test_etag_avec_liste_et_prefixe_faible(app, appels):
    _, h, _ = requete(app)
    code, _, _ = requete(app, entetes=f'"autre", W/{h["etag"]}')
    assert code == "304 Not Modified"


@pytest.mark.parametrize(
    "query",
    [
        "periode=7h", "periode=", "periode=7j&periode=24h", "periode=1h", "periode=perso",
        "seuil=0", "seuil=10001", "seuil=abc", "seuil=-3", "seuil=", "seuil=2.5",
        "debut=2026-10-01", "fin=2026-10-01", "debut=abc&fin=2026-10-02", "debut=2026-13-01&fin=2026-10-02",
        "debut=2026-10-03&fin=2026-10-01", "debut=2026-10-01&fin=2026-10-30", "debut=2026-10-01&fin=2026-10-02&periode=7j",
        "debut=2026-10-01&debut=2026-10-02&fin=2026-10-03",
    ],
)
def test_400_parametre_invalide(app, appels, query):
    code, _, corps = requete(app, query=query)
    assert code == "400 Bad Request" and "erreur" in json.loads(corps)
    assert appels == []


def test_404_route_inconnue(app):
    assert requete(app, chemin="/api/inconnu")[0] == "404 Not Found"
    assert requete(app, chemin="/api/tableau/")[0] == "404 Not Found"


def test_405_autre_methode(app):
    code, h, corps = requete(app, methode="POST")
    assert code == "405 Method Not Allowed" and h["allow"] == "GET, HEAD"
    assert json.loads(corps) == {"erreur": "lecture seule"}


def test_head_sans_corps(app, appels):
    code, h, corps = requete(app, methode="HEAD")
    assert code == "200 OK" and corps == b"" and int(h["content-length"]) > 0


def test_503_sans_detail_de_connexion(app, monkeypatch):
    monkeypatch.setattr(donnees, "etat_base", lambda cfg: EtatBase(premiere=None, derniere_maj=None))
    def lire(cfg, bornes, etat):
        raise ErreurBase("connexion impossible (hote-secret:8123)")

    monkeypatch.setattr(donnees, "lire", lire)
    code, _, corps = requete(app)
    assert code == "503 Service Unavailable"
    assert json.loads(corps) == {"erreur": "base injoignable"}
    assert b"hote-secret" not in corps


def test_500_sans_trace(app, monkeypatch):
    monkeypatch.setattr(donnees, "etat_base", lambda cfg: EtatBase(premiere=None, derniere_maj=None))
    def lire(cfg, bornes, etat):
        raise RuntimeError("secret interne")

    monkeypatch.setattr(donnees, "lire", lire)
    code, _, corps = requete(app)
    assert code == "500 Internal Server Error" and b"secret" not in corps


def test_sante_ok_et_503(app, monkeypatch):
    monkeypatch.setattr(donnees, "ping", lambda cfg: None)
    code, _, corps = requete(app, chemin="/api/sante")
    assert code == "200 OK" and json.loads(corps) == {"status": "ok"}

    def ping(cfg):
        raise ErreurBase("ping impossible (OperationalError)")

    monkeypatch.setattr(donnees, "ping", ping)
    code, _, corps = requete(app, chemin="/api/sante")
    assert code == "503 Service Unavailable" and json.loads(corps) == {"erreur": "base injoignable"}


def test_catalogue_200_sans_table(app, monkeypatch):
    monkeypatch.setattr(donnees, "evenements", lambda cfg: (False, []))
    code, h, corps = requete(app, chemin="/api/evenements")
    doc = json.loads(corps)
    assert code == "200 OK" and h["cache-control"] == "no-store" and "etag" in h
    assert doc == {"schema_version": 1, "generated_at": "2026-10-19T10:02:30Z", "disponible": False, "evenements": []}


def test_catalogue_503_si_base_injoignable(app, monkeypatch):
    def panne(cfg):
        raise ErreurBase("x")

    monkeypatch.setattr(donnees, "evenements", panne)
    code, _, corps = requete(app, chemin="/api/evenements")
    assert code == "503 Service Unavailable" and json.loads(corps) == {"erreur": "base injoignable"}
