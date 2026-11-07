"""Tests des correctifs de fiabilité de la collecte. Aucun accès réseau, aucune vraie donnée."""
import json
import sqlite3
import sys
import threading
import time
import types
from datetime import datetime, timezone

import pytest
import requests
import websocket

import ingestion
from ingestion import Contexte, KeywordFilter, LecteurContexte, Store

MIN_DT = datetime(2025, 1, 1, tzinfo=timezone.utc)
T_US = 1_790_000_000_000_000          # septembre 2026, en microsecondes
MINUTE = ingestion.event_minute(T_US, "")


@pytest.fixture
def filt():
    return KeywordFilter({
        "identites": ["bardella"],
        "orientations": ["gauche"],
        "jargon": ["gouvernement"],
    })


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


def event(text, operation="create", langs=("fr",), created="2026-09-21T10:00:00.000Z",
          time_us=T_US):
    return {"kind": "commit", "time_us": time_us, "commit": {
        "operation": operation, "collection": "app.bsky.feed.post",
        "record": {"text": text, "createdAt": created, "langs": list(langs)}}}


def process(store, filt, msg):
    return ingestion.process_message(store, msg, filt, MIN_DT)


def rows(store, sql):
    return store.db.execute(sql).fetchall()


# --- filtre -----------------------------------------------------------------

def test_filtre_trois_classes(filt):
    assert filt.test("bardella parle") is None
    assert filt.test("la gauche et le gouvernement") is None
    assert filt.test("le gouvernement") == "jargon-seul"
    assert filt.test("la gauche") == "orientation-seule"
    assert filt.test("bonjour") == "rien"


# --- stats : minute séparée du motif ---------------------------------------

def test_rejets_ranges_par_motif_et_stats_par_minute(store, filt):
    process(store, filt, event("bonjour"))                       # rien
    process(store, filt, event("le gouvernement"))               # jargon-seul
    process(store, filt, event("bardella", langs=("en",)))       # langue
    process(store, filt, event("bardella", created="2020-01-01T00:00:00Z"))  # hors-periode
    process(store, filt, event("bardella"))                      # gardé
    store.flush(T_US)
    assert rows(store, "SELECT ts, events, kept, dropped FROM ingest_stats") == [
        (MINUTE, 5, 1, 4)]
    motifs = dict(rows(store, "SELECT reason, SUM(n) FROM ingest_rejects GROUP BY reason"))
    assert motifs == {"rien": 1, "jargon-seul": 1, "langue": 1, "hors-periode": 1}
    assert all(ts == MINUTE for (ts,) in rows(store, "SELECT ts FROM ingest_rejects"))


# --- dédoublonnage ----------------------------------------------------------

def test_doublon_dans_le_meme_lot(store, filt):
    process(store, filt, event("bardella"))
    process(store, filt, event("bardella"))
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]
    assert rows(store, "SELECT kept, duplicates FROM ingest_stats") == [(1, 1)]


def test_doublon_entre_deux_lots_apres_reprise(store, filt):
    process(store, filt, event("bardella"))
    store.flush(T_US)
    process(store, filt, event("bardella"))      # rejoué par le cursor
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]
    assert rows(store, "SELECT kept, duplicates FROM ingest_stats") == [(1, 1)]


def test_flush_en_erreur_conserve_le_lot(store, filt):
    process(store, filt, event("bardella"))
    store.db.execute("DROP TABLE ingest_meta")
    with pytest.raises(sqlite3.OperationalError):
        store.flush(T_US)
    assert len(store.pending) == 1
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(0,)]   # rollback


# --- opérations -------------------------------------------------------------

@pytest.mark.parametrize("operation", ["update", "delete"])
def test_update_et_delete_ignores(store, filt, operation):
    t = process(store, filt, event("bardella", operation=operation))
    store.flush(t)
    assert t == T_US                              # le cursor avance quand même
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(0,)]
    assert store.ignored_ops == 1


def test_create_garde(store, filt):
    process(store, filt, event("bardella"))
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]


# --- erreurs par message ----------------------------------------------------

@pytest.mark.parametrize("raw", [
    "pas du json", "[1, 2]", "null", '{"time_us": "x", "commit": {"operation": "create"}}',
    '{"time_us": 5, "commit": {"operation": "create", "record": "texte"}}',
])
def test_message_invalide_ne_leve_pas(store, filt, raw):
    errors = {}
    ingestion.handle_raw(store, raw, filt, MIN_DT, errors)
    assert sum(errors.values()) == 1


def test_message_invalide_conserve_le_cursor_et_ne_logue_pas_le_contenu(store, filt, capsys):
    raw = json.dumps({"time_us": 42, "commit": {"operation": "create",
                                                "record": "SECRET-TEXTE"}})
    errors = {}
    assert ingestion.handle_raw(store, raw, filt, MIN_DT, errors) == 42
    assert "SECRET-TEXTE" not in capsys.readouterr().out


# --- migration d'une base à l'ancien schéma ---------------------------------

def make_old_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            text TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE);
        CREATE TABLE ingest_stats (ts TEXT PRIMARY KEY, events INTEGER NOT NULL DEFAULT 0,
            kept INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE ingest_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO posts(created_at, text, dedup_key) VALUES ('2026-01-01T00:00:00.000Z','a','k1');
        INSERT INTO ingest_stats VALUES ('2026-01-01T00:00', 10, 4, 2);
        INSERT INTO ingest_stats VALUES ('rien', 0, 0, 140665);
        INSERT INTO ingest_stats VALUES ('jargon-seul', 0, 0, 7);
        INSERT INTO ingest_meta VALUES ('jetstream_cursor', '123');
    """)
    db.commit()
    db.close()


def test_migration_ancienne_base(tmp_path, filt):
    path = str(tmp_path / "old.db")
    make_old_db(path)
    s = Store(path)
    assert s.cursor == 123
    assert rows(s, "SELECT COUNT(*) FROM posts") == [(1,)]
    assert rows(s, "SELECT ts, events, kept, dropped, duplicates FROM ingest_stats") == [
        ("2026-01-01T00:00", 10, 4, 2, 0)]
    assert dict(rows(s, "SELECT reason, n FROM ingest_rejects")) == {
        "rien": 140665, "jargon-seul": 7}
    process(s, filt, event("bardella"))           # la base migrée reste utilisable
    s.flush(T_US)
    assert rows(s, "SELECT COUNT(*) FROM posts") == [(2,)]
    s.close()


def test_migration_idempotente(tmp_path):
    path = str(tmp_path / "old.db")
    make_old_db(path)
    Store(path).close()
    s = Store(path)
    assert dict(rows(s, "SELECT reason, n FROM ingest_rejects")) == {
        "rien": 140665, "jargon-seul": 7}
    s.close()


# --- chien de garde et battement --------------------------------------------

class FrozenWS:
    """WebSocket ouverte qui n'envoie jamais rien."""
    sock = type("S", (), {"settimeout": lambda self, t: None})()

    def recv(self):
        time.sleep(0.05)
        raise websocket.WebSocketTimeoutException()

    def close(self):
        pass


def test_flux_fige_provoque_une_reconnexion(store, filt, monkeypatch):
    connexions = []
    monkeypatch.setattr(ingestion.websocket, "create_connection",
                        lambda url, timeout: connexions.append(url) or FrozenWS())
    monkeypatch.setattr(ingestion, "STOP", False)
    # durée 3,5 s : 1re connexion, flux figé à 0,3 s, reconnexion après 2 s de backoff
    ingestion.run_stream(store, filt, MIN_DT, 3.5, 200, 5.0, idle_timeout=0.3)
    assert len(connexions) >= 2


def test_battement(tmp_path):
    p = tmp_path / "hb"
    ingestion.beat(str(p))
    assert p.read_text().isdigit()
    ingestion.beat(None)                          # sans chemin : sans effet
    ingestion.beat(str(tmp_path / "absent" / "hb"))  # chemin invalide : pas d'exception


# --- nouveau corpus : langue du texte (phrases fabriquées) --------------------

FR = "Le gouvernement annonce une nouvelle réforme des retraites pour les salariés de la région."
FR_CANDIDAT = "Bardella présente la réforme des retraites pour les salariés de la région."
EN_CANDIDAT = "Bardella explains the reform of the pension system for workers across the region."


def test_est_francais():
    assert ingestion.est_francais(FR)
    assert not ingestion.est_francais(EN_CANDIDAT)
    assert not ingestion.est_francais("🙂🙂🙂")       # sans indice lexical : pas français
    assert not ingestion.est_francais("")


def test_nouveau_corpus_rejette_texte_non_francais(store, filt):
    ingestion.process_message(store, event(EN_CANDIDAT), filt, MIN_DT, nouveau=True)
    ingestion.process_message(store, event(FR_CANDIDAT), filt, MIN_DT, nouveau=True)
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]
    assert dict(rows(store, "SELECT reason, SUM(n) FROM ingest_rejects GROUP BY reason")) == {
        "langue-texte": 1}


def test_nouveau_corpus_garde_texte_francais_declare_en(store, filt):
    # langue déclarée en, texte français : gardé dans le nouveau corpus, rejeté dans l'existant
    ingestion.process_message(store, event(FR_CANDIDAT, langs=("en",)), filt, MIN_DT, nouveau=True)
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]


def test_corpus_existant_rejette_langue_declaree_en(store, filt):
    ingestion.process_message(store, event(FR_CANDIDAT, langs=("en",)), filt, MIN_DT)
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(0,)]
    assert dict(rows(store, "SELECT reason, SUM(n) FROM ingest_rejects GROUP BY reason")) == {
        "langue": 1}


def test_masquer_url_et_mentions():
    assert ingestion.masquer("Lire https://exemple.fr/page?x=1 puis @nom.exemple.social.") == \
        "Lire [url] puis [mention]."
    assert ingestion.masquer("Voir www.exemple.fr, merci.") == "Voir [url], merci."
    assert ingestion.masquer("Rien à masquer ici.") == "Rien à masquer ici."


def test_masquer_garde_le_nom_public_des_candidats():
    noms = ingestion.noms_publics(["glucksmann", "le pen", "rn"])
    assert ingestion.masquer("Avis de @glucksmann.bsky.social.", noms) == "Avis de [mention:glucksmann]."
    assert ingestion.masquer("@le-pen.fr répond", noms) == "[mention:le pen] répond"
    assert ingestion.masquer("@rn.exemple.fr", noms) == "[mention]"          # « rn » : moins de 4 caractères
    assert ingestion.masquer("@nom.exemple.social", noms) == "[mention]"


def test_masquer_accepte_une_erreur_sur_un_nom_court_et_deux_sur_un_long():
    noms = ingestion.noms_publics(["glucksmann", "lepen"])
    assert ingestion.masquer("@glucksmnn2027.fr", noms) == "[mention:glucksmann]"   # 1 erreur
    assert ingestion.masquer("@glucksmnnn.fr", noms) == "[mention:glucksmann]"      # 2 erreurs
    assert ingestion.masquer("@penser.fr", noms) == "[mention]"                     # « lepen » ≠ « penser »


def test_nom_public_marque_dans_un_hashtag_ou_une_mention():
    noms = ingestion.noms_publics(["melenchon"])
    assert ingestion.nom_public_marque("Vive #StopMelenchon", noms) == "melenchon"
    assert ingestion.nom_public_marque("Vive #Melanchon", noms) == "melenchon"     # 1 erreur
    assert ingestion.nom_public_marque("@melenchon2027.fr", noms) == "melenchon"
    assert ingestion.nom_public_marque("rien à voir #Vacances", noms) is None


def test_nouveau_corpus_stocke_texte_masque(store, filt):
    texte = "Bardella répond à @nom.exemple.social sur https://exemple.fr/dossier, la réforme."
    ingestion.process_message(store, event(texte), filt, MIN_DT, nouveau=True)
    store.flush(T_US)
    assert rows(store, "SELECT text FROM posts") == [
        ("Bardella répond à [mention] sur [url], la réforme.",)]


def test_corpus_existant_stocke_texte_brut(store, filt):
    texte = "Bardella répond à @nom.exemple.social sur https://exemple.fr/dossier, la réforme."
    process(store, filt, event(texte))
    store.flush(T_US)
    assert rows(store, "SELECT text FROM posts") == [(texte,)]


def test_corpus_existant_garde_texte_non_francais_declare_fr(store, filt):
    process(store, filt, event(EN_CANDIDAT))      # nouveau=False : comportement d'origine
    store.flush(T_US)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]


def test_nouveau_corpus_refuse_la_base_existante(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "ingestion.py", "--nouveau-corpus", "--db", str(tmp_path / "bluesky_posts.db")])
    assert ingestion.main() == 2
    assert not (tmp_path / "bluesky_posts.db").exists()


# --- nouveau corpus : contexte des réponses et citations (requests simulé) ---

PARENT = "at://did:plc:exemple0001/app.bsky.feed.post/3parent0001"     # fabriqué
PARENT2 = "at://did:plc:exemple0002/app.bsky.feed.post/3parent0002"   # fabriqué
PARENT_FR = "Bardella présente la réforme sur https://exemple.fr/dossier pour les retraites."
PARENT_FR2 = "Bardella répond sur la fiscalité des entreprises de la région."
PARENT_EN = "Bardella explains the reform of the pension system for workers across the region."
REPONSE = "Bardella répond à ta question sur la réforme des retraites pour la région."
CITATION = {"$type": "app.bsky.embed.record", "record": {"uri": PARENT, "cid": "bafyexemple"}}
CITATION2 = {"$type": "app.bsky.embed.record", "record": {"uri": PARENT2, "cid": "bafyexemple2"}}


class Reponse:
    """Réponse HTTP simulée : statut et corps JSON (None : corps non JSON)."""

    def __init__(self, status=200, corps=None):
        self.status_code = status
        self._corps = corps

    def json(self):
        if self._corps is None:
            raise ValueError("pas du JSON")
        return self._corps


def posts(texte):
    return Reponse(200, {"posts": [{"uri": PARENT, "record": {"text": texte}}]})


@pytest.fixture
def api(monkeypatch):
    """requests.get simulé : réponse par URI, appels enregistrés, blocage optionnel du fil.

    `bloque` : si défini, chaque appel attend cet Event (3 s au plus) avant de répondre.
    `entree` : levé à chaque appel, pour savoir que le fil a pris une demande.
    """
    ns = types.SimpleNamespace(reponses={}, appels=[], bloque=None, entree=threading.Event())

    def get(url, params=None, headers=None, timeout=None):
        ns.entree.set()
        if ns.bloque is not None:
            ns.bloque.wait(3)
        ns.appels.append({"url": url, "uris": params["uris"], "timeout": timeout})
        reponse = ns.reponses.get(params["uris"][0], Reponse(200, {"posts": []}))
        if isinstance(reponse, Exception):
            raise reponse
        return reponse

    monkeypatch.setattr(requests, "get", get)
    return ns


@pytest.fixture
def nouveau(api, filt):
    """Fabrique de Contexte à lecteur réel ; les fils sont arrêtés à la fin du test."""
    lecteurs = []

    def fabrique(max_par_minute=20, clock=time.monotonic, file_max=60, delai=60.0,
                 attente_max=50):
        lecteur = LecteurContexte(max_par_minute, file_max=file_max, clock=clock)
        lecteurs.append(lecteur)
        return Contexte(lecteur, filt, delai=delai, attente_max=attente_max, clock=clock)

    yield fabrique
    if api.bloque is not None:
        api.bloque.set()
    for lecteur in lecteurs:
        lecteur.arreter(0.5)


def record(text, reply=None, embed=None):
    r = {"text": text, "createdAt": "2026-09-21T10:00:00.000Z", "langs": ["fr"]}
    if reply:
        r["reply"] = {"root": {"uri": reply, "cid": "bafyexemple"},
                      "parent": {"uri": reply, "cid": "bafyexemple"}}
    if embed:
        r["embed"] = embed
    return r


def envoyer(store, filt, rec, contexte, time_us=T_US):
    """Traite un post du nouveau corpus, sans attendre les résultats."""
    msg = {"kind": "commit", "time_us": time_us, "commit": {
        "operation": "create", "collection": "app.bsky.feed.post", "record": rec}}
    ingestion.process_message(store, msg, filt, MIN_DT, True, contexte)


def terminer(store, contexte, delai=2.0):
    """Consomme les résultats jusqu'à ce qu'il n'en reste plus, puis écrit le lot."""
    fin = time.monotonic() + delai
    while contexte.en_vol and time.monotonic() < fin:
        contexte.consommer(store)
        time.sleep(0.005)
    contexte.consommer(store)
    ingestion.vidanger(store, contexte)


def traiter(store, filt, rec, contexte, time_us=T_US):
    envoyer(store, filt, rec, contexte, time_us)
    terminer(store, contexte)


def attendre_retours(lecteur, n, delai=2.0):
    """Récupère n résultats du fil (sondage court)."""
    sortie, fin = [], time.monotonic() + delai
    while len(sortie) < n and time.monotonic() < fin:
        sortie += lecteur.retours()
        time.sleep(0.005)
    return sortie


def compteurs(store):
    return dict(rows(store, "SELECT cle, n FROM ingest_compteurs"))


def motifs(store):
    return dict(rows(store, "SELECT reason, SUM(n) FROM ingest_rejects GROUP BY reason"))


def curseur_db(store):
    return int(rows(store, "SELECT value FROM ingest_meta WHERE key='jetstream_cursor'")[0][0])


def test_cible_contexte():
    avec_medias = {"$type": "app.bsky.embed.recordWithMedia",
                   "record": {"record": {"uri": PARENT, "cid": "bafyexemple"},
                              "media": {"$type": "app.bsky.embed.images"}}}
    assert ingestion.cible_contexte(record(REPONSE, reply=PARENT)) == ("reponse", PARENT)
    assert ingestion.cible_contexte(record(REPONSE, embed=CITATION)) == ("citation", PARENT)
    assert ingestion.cible_contexte(record(REPONSE, embed=avec_medias)) == ("citation", PARENT)
    assert ingestion.cible_contexte(record(REPONSE, reply=PARENT, embed=CITATION)) == \
        ("reponse", PARENT)
    assert ingestion.cible_contexte(record(REPONSE, embed={"$type": "app.bsky.embed.images"})) is None
    assert ingestion.cible_contexte(record(REPONSE)) is None


def test_lecteur_renvoie_le_texte_du_parent(api, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    lecteur = nouveau(max_par_minute=10).lecteur
    assert lecteur.demander(1, PARENT)
    assert attendre_retours(lecteur, 1) == [ingestion.Retour(1, PARENT_FR, None)]
    assert api.appels == [{"url": ingestion.GETPOSTS_URL, "uris": [PARENT],
                           "timeout": ingestion.CONTEXTE_TIMEOUT_S}]


@pytest.mark.parametrize("reponse, motif", [
    (Reponse(429, {}), "http"),
    (Reponse(200, {"posts": []}), "introuvable"),
    (Reponse(200, {"posts": [{"uri": PARENT, "record": {}}]}), "vide"),
    (Reponse(200, ["pas", "un", "objet"]), "format"),
    (Reponse(200, None), "format"),
    (requests.ConnectionError(f"connexion refusée vers {PARENT}"), "reseau"),
])
def test_lecteur_motifs_d_absence(api, nouveau, reponse, motif):
    api.reponses[PARENT] = reponse
    lecteur = nouveau(max_par_minute=10).lecteur
    lecteur.demander(1, PARENT)
    (retour,) = attendre_retours(lecteur, 1)
    assert retour == (1, None, motif)           # l'URI n'apparaît pas dans le résultat


def test_plafond_glissant(api, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    horloge = [0.0]
    lecteur = nouveau(max_par_minute=2, clock=lambda: horloge[0]).lecteur
    for req in (1, 2, 3):
        lecteur.demander(req, PARENT)
    retours = attendre_retours(lecteur, 3)
    assert [(r.req, r.motif) for r in retours] == [(1, None), (2, None), (3, "plafond")]
    assert len(api.appels) == 2                 # le plafond évite l'appel
    horloge[0] = 60.0                           # la fenêtre de 60 s se libère
    lecteur.demander(4, PARENT)
    assert attendre_retours(lecteur, 1)[0].motif is None
    assert len(api.appels) == 3


def test_nouveau_corpus_stocke_le_contexte_de_la_reponse(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    traiter(store, filt, record(REPONSE, reply=PARENT), nouveau())
    assert rows(store, "SELECT text, contexte_type, contexte_texte FROM posts") == [
        (REPONSE, "reponse", "Bardella présente la réforme sur [url] pour les retraites.")]
    assert compteurs(store) == {"contexte_recupere": 1}
    contenu = " ".join(str(v) for ligne in rows(store, "SELECT * FROM posts") for v in ligne)
    assert "at://" not in contenu and "did:" not in contenu


def test_nouveau_corpus_stocke_le_contexte_de_la_citation(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    traiter(store, filt, record(REPONSE, embed=CITATION), nouveau())
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts") == [
        ("citation", "Bardella présente la réforme sur [url] pour les retraites.")]


def test_contexte_absent_garde_le_post_et_compte_le_motif(api, store, filt, nouveau):
    api.reponses[PARENT] = Reponse(404, {})
    traiter(store, filt, record(REPONSE, reply=PARENT), nouveau())
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts") == [("reponse", None)]
    assert compteurs(store) == {"contexte_absent_http": 1}


def test_plafond_atteint_garde_sans_appel(api, store, filt, nouveau):
    traiter(store, filt, record(REPONSE, reply=PARENT), nouveau(max_par_minute=0))
    assert api.appels == []
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts") == [("reponse", None)]
    assert compteurs(store) == {"contexte_absent_plafond": 1}


def test_contexte_non_francais_n_est_pas_stocke(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_EN)
    traiter(store, filt, record(REPONSE, reply=PARENT), nouveau())
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts") == [("reponse", None)]
    assert compteurs(store) == {"contexte_absent_langue": 1}


def test_corpus_existant_n_appelle_pas_getposts(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    contexte = nouveau()
    msg = {"kind": "commit", "time_us": T_US, "commit": {
        "operation": "create", "collection": "app.bsky.feed.post",
        "record": record(REPONSE, reply=PARENT)}}
    ingestion.process_message(store, msg, filt, MIN_DT, False, contexte)
    ingestion.vidanger(store, contexte)
    assert api.appels == []
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts") == [(None, None)]


def test_migration_ajoute_les_colonnes_de_contexte(tmp_path):
    path = str(tmp_path / "old.db")
    make_old_db(path)
    s = Store(path)
    assert {"contexte_type", "contexte_texte"} <= {r[1] for r in rows(s, "PRAGMA table_info(posts)")}
    assert rows(s, "SELECT contexte_type, contexte_texte FROM posts") == [(None, None)]
    s.close()


# --- nouveau corpus : garde par parent (réponse qui échoue la garde) ---------

REPONSE_COURTE = "Oui, tout à fait, merci pour ce retour."     # aucun mot-clé : garde échouée
PARENT_HORS_SUJET = "Le gouvernement annonce une nouvelle réforme des retraites pour la région."


def test_garde_par_parent_sauve_la_reponse_courte(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    traiter(store, filt, record(REPONSE_COURTE, reply=PARENT), nouveau())
    assert rows(store, "SELECT text, contexte_type, contexte_texte FROM posts") == [
        (REPONSE_COURTE, "reponse", "Bardella présente la réforme sur [url] pour les retraites.")]
    assert compteurs(store) == {"contexte_recupere": 1, "garde_par_parent": 1}
    assert motifs(store) == {}
    assert rows(store, "SELECT events, kept, dropped FROM ingest_stats") == [(1, 1, 0)]


def test_garde_par_parent_rejette_si_le_parent_echoue(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_HORS_SUJET)
    traiter(store, filt, record(REPONSE_COURTE, reply=PARENT), nouveau())
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(0,)]
    assert motifs(store) == {"garde_par_parent_refusee": 1}
    assert compteurs(store) == {"contexte_recupere": 1, "garde_par_parent_refusee": 1}
    assert rows(store, "SELECT events, kept, dropped FROM ingest_stats") == [(1, 0, 1)]


def test_garde_par_parent_exige_un_parent_francais(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_EN)          # passe la garde, mais en anglais
    traiter(store, filt, record(REPONSE_COURTE, reply=PARENT), nouveau())
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(0,)]
    assert motifs(store) == {"garde_par_parent_refusee": 1}
    assert compteurs(store) == {"contexte_absent_langue": 1, "garde_par_parent_refusee": 1}


def test_garde_par_parent_sans_plafond_rejette_sans_appel(api, store, filt, nouveau):
    traiter(store, filt, record(REPONSE_COURTE, reply=PARENT), nouveau(max_par_minute=0))
    assert api.appels == []
    assert motifs(store) == {"garde_par_parent_refusee": 1}
    assert compteurs(store) == {"contexte_absent_plafond": 1, "garde_par_parent_refusee": 1}


def test_citation_qui_echoue_la_garde_est_rejetee_sans_appel(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    traiter(store, filt, record(REPONSE_COURTE, embed=CITATION), nouveau())
    assert api.appels == []
    assert motifs(store) == {"rien": 1}


def test_reponse_non_francaise_qui_echoue_la_garde_est_rejetee_sans_appel(api, store, filt, nouveau):
    traiter(store, filt, record("Thanks a lot for your reply, very interesting.", reply=PARENT),
            nouveau())
    assert api.appels == []
    assert motifs(store) == {"rien": 1}


def test_corpus_existant_ne_sauve_pas_par_le_parent(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    msg = {"kind": "commit", "time_us": T_US, "commit": {
        "operation": "create", "collection": "app.bsky.feed.post",
        "record": record(REPONSE_COURTE, reply=PARENT)}}
    ingestion.process_message(store, msg, filt, MIN_DT, False, nouveau())
    ingestion.vidanger(store, None)
    assert api.appels == []
    assert motifs(store) == {"rien": 1}


# --- nouveau corpus : fonctionnement asynchrone -----------------------------

class FluxMessages:
    """WebSocket simulée : messages prêts, puis silence court (aucun réseau)."""
    sock = type("S", (), {"settimeout": lambda self, t: None})()

    def __init__(self, messages):
        self.messages = list(messages)

    def recv(self):
        if self.messages:
            return self.messages.pop(0)
        time.sleep(0.01)
        raise websocket.WebSocketTimeoutException()

    def close(self):
        pass


def test_reponse_lente_ne_bloque_pas_la_boucle(api, store, filt, nouveau):
    api.bloque = threading.Event()                  # le fil reste bloqué pendant la mesure
    api.reponses[PARENT] = posts(PARENT_FR)
    contexte = nouveau()
    durees = []
    for i in range(20):
        rec = record(f"Bardella répond à la question numéro {i} sur la réforme des retraites.",
                     reply=PARENT)
        debut = time.perf_counter()
        envoyer(store, filt, rec, contexte, T_US + i)
        contexte.consommer(store)
        durees.append(time.perf_counter() - debut)
    ingestion.vidanger(store, contexte)
    assert api.appels == []                         # rien n'a encore abouti
    assert rows(store, "SELECT COUNT(*) FROM posts WHERE contexte_texte IS NULL") == [(20,)]
    api.bloque.set()
    terminer(store, contexte)
    assert max(durees) < 0.5
    assert rows(store, "SELECT COUNT(*) FROM posts WHERE contexte_texte IS NULL") == [(0,)]


def test_flux_continu_pendant_un_appel_lent(api, filt, nouveau, monkeypatch, tmp_path):
    api.bloque = threading.Event()                  # chaque appel reste bloqué pendant 3 s
    monkeypatch.setattr(ingestion, "ARRET_DELAI_S", 0.2)   # borne de l'arrêt, testée à part
    api.reponses[PARENT] = posts(PARENT_FR)
    messages = [json.dumps({"kind": "commit", "time_us": T_US + i, "commit": {
        "operation": "create", "collection": "app.bsky.feed.post",
        "record": record(f"Bardella répond à la question numéro {i} sur la réforme des retraites.",
                         reply=PARENT)}}) for i in range(50)]
    connexions = []
    monkeypatch.setattr(ingestion.websocket, "create_connection",
                        lambda url, timeout: connexions.append(url) or FluxMessages(messages))
    monkeypatch.setattr(ingestion, "STOP", False)
    chemin = str(tmp_path / "flux.db")
    store = Store(chemin)
    debut = time.monotonic()
    ingestion.run_stream(store, filt, MIN_DT, 1.0, 200, 5.0, idle_timeout=60.0,
                         nouveau=True, contexte=nouveau())
    duree = time.monotonic() - debut
    api.bloque.set()
    assert len(connexions) == 1                     # aucune coupure du flux
    assert duree < 2.0                              # la boucle n'a pas attendu le réseau
    db = sqlite3.connect(chemin)
    assert db.execute("SELECT SUM(events), SUM(kept) FROM ingest_stats").fetchone() == (50, 50)
    db.close()


def test_file_pleine_stocke_le_post_sans_contexte(api, store, filt, nouveau):
    api.bloque = threading.Event()
    api.reponses[PARENT] = posts(PARENT_FR)
    contexte = nouveau(file_max=1)
    envoyer(store, filt, record("Bardella répond à la question numéro 1 sur les retraites.",
                                reply=PARENT), contexte, T_US)
    assert api.entree.wait(2)                       # le fil a pris la 1re demande
    envoyer(store, filt, record("Bardella répond à la question numéro 2 sur les retraites.",
                                reply=PARENT), contexte, T_US + 1)
    envoyer(store, filt, record("Bardella répond à la question numéro 3 sur les retraites.",
                                reply=PARENT), contexte, T_US + 2)
    ingestion.vidanger(store, contexte)
    assert compteurs(store) == {"contexte_absent_file_pleine": 1}
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts WHERE text LIKE '%numéro 3%'") \
        == [("reponse", None)]
    assert len(rows(store, "SELECT id FROM posts")) == 3     # aucun post perdu
    api.bloque.set()
    terminer(store, contexte)
    assert compteurs(store) == {"contexte_absent_file_pleine": 1, "contexte_recupere": 2}
    assert rows(store, "SELECT COUNT(*) FROM posts WHERE contexte_texte IS NULL") == [(1,)]


def test_reponse_sans_resultat_rejetee_apres_le_delai(api, store, filt, nouveau):
    api.bloque = threading.Event()                  # le parent ne répond pas
    horloge = [0.0]
    contexte = nouveau(clock=lambda: horloge[0], delai=60.0)
    envoyer(store, filt, record(REPONSE_COURTE, reply=PARENT), contexte, T_US)
    assert len(contexte.attentes) == 1
    horloge[0] = 59.9
    contexte.consommer(store)
    assert len(contexte.attentes) == 1              # pas encore échue
    horloge[0] = 60.0
    contexte.consommer(store)
    assert contexte.attentes == {} and contexte.en_vol == {}
    ingestion.vidanger(store, contexte)
    assert motifs(store) == {"contexte_absent_delai": 1}
    assert compteurs(store) == {"contexte_absent_delai": 1}
    assert rows(store, "SELECT events, kept, dropped FROM ingest_stats") == [(1, 0, 1)]
    api.reponses[PARENT] = posts(PARENT_FR)
    api.bloque.set()
    fin = time.monotonic() + 2.0
    while not api.appels and time.monotonic() < fin:
        time.sleep(0.005)                           # le parent répond après le délai
    time.sleep(0.05)
    contexte.consommer(store)                       # le retour tardif est ignoré
    ingestion.vidanger(store, contexte)
    assert compteurs(store) == {"contexte_absent_delai": 1}
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(0,)]


def test_attente_bornee_rejette_avec_file_pleine(api, store, filt, nouveau):
    api.bloque = threading.Event()
    contexte = nouveau(attente_max=1)
    envoyer(store, filt, record(REPONSE_COURTE, reply=PARENT), contexte, T_US)
    envoyer(store, filt, record(REPONSE_COURTE + " Deux.", reply=PARENT), contexte, T_US + 1)
    ingestion.vidanger(store, contexte)
    assert motifs(store) == {"contexte_absent_file_pleine": 1}
    assert compteurs(store) == {"contexte_absent_file_pleine": 1}
    assert len(contexte.attentes) == 1


def test_curseur_ne_depasse_pas_la_reponse_en_attente(api, store, filt, nouveau):
    api.bloque = threading.Event()
    api.reponses[PARENT] = posts(PARENT_FR)
    contexte = nouveau()
    envoyer(store, filt, record(REPONSE_COURTE, reply=PARENT), contexte, T_US)
    store.cursor = T_US + 1_000_000                 # la boucle a déjà vu des événements plus récents
    ingestion.vidanger(store, contexte)
    assert curseur_db(store) == T_US - 1
    api.bloque.set()
    terminer(store, contexte)
    assert curseur_db(store) == T_US + 1_000_000
    assert rows(store, "SELECT text, contexte_type FROM posts") == [(REPONSE_COURTE, "reponse")]


def test_mise_a_jour_arrive_sur_la_bonne_ligne(api, store, filt, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    api.reponses[PARENT2] = posts(PARENT_FR2)
    contexte = nouveau()
    textes = {
        "reponse": "Bardella répond à la question sur la réforme des retraites, merci.",
        "sans": "Bardella annonce une baisse de la fiscalité pour la région.",
        "citation": "Bardella commente la réforme des retraites de la région, à lire.",
    }
    envoyer(store, filt, record(textes["reponse"], reply=PARENT), contexte, T_US)
    envoyer(store, filt, record(textes["sans"]), contexte, T_US + 1)
    envoyer(store, filt, record(textes["citation"], embed=CITATION2), contexte, T_US + 2)
    terminer(store, contexte)
    assert rows(store, "SELECT text, contexte_type, contexte_texte FROM posts ORDER BY id") == [
        (textes["reponse"], "reponse", "Bardella présente la réforme sur [url] pour les retraites."),
        (textes["sans"], None, None),
        (textes["citation"], "citation", PARENT_FR2),
    ]


def test_doublon_rattache_le_contexte_a_la_ligne_existante(api, store, filt, nouveau):
    api.bloque = threading.Event()
    api.reponses[PARENT] = posts(PARENT_FR)
    contexte = nouveau()
    rec = record(REPONSE, reply=PARENT)
    envoyer(store, filt, rec, contexte, T_US)
    envoyer(store, filt, rec, contexte, T_US)       # même post, reprise du cursor
    ingestion.vidanger(store, contexte)
    api.bloque.set()
    terminer(store, contexte)
    assert rows(store, "SELECT COUNT(*) FROM posts") == [(1,)]
    assert rows(store, "SELECT contexte_texte FROM posts") == [
        ("Bardella présente la réforme sur [url] pour les retraites.",)]
    assert compteurs(store) == {"contexte_recupere": 2}


def test_base_et_journal_sans_uri_ni_did_ni_cid(api, store, filt, nouveau, capsys):
    api.reponses[PARENT] = posts(PARENT_FR)
    api.reponses[PARENT2] = posts(PARENT_FR2)
    contexte = nouveau()
    traiter(store, filt, record(REPONSE, reply=PARENT), contexte, T_US)
    traiter(store, filt, record(REPONSE_COURTE, reply=PARENT), contexte, T_US + 1)
    traiter(store, filt, record(REPONSE, embed=CITATION2), contexte, T_US + 2)
    contenu = []
    for (nom,) in rows(store, "SELECT name FROM sqlite_master WHERE type='table'"):
        contenu += [repr(ligne) for ligne in rows(store, f"SELECT * FROM {nom}")]
    texte = "\n".join(contenu) + capsys.readouterr().out
    for interdit in ("at://", "did:", "exemple0001", "exemple0002", "3parent", "bafyexemple"):
        assert interdit not in texte


# --- arrêt propre (SIGTERM) ----------------------------------------------------

def test_arret_abandonne_les_demandes_compte_et_borne_la_sortie(api, store, filt, nouveau,
                                                                monkeypatch):
    api.bloque = threading.Event()                  # le fil ne rend rien pendant l'arrêt
    api.reponses[PARENT] = posts(PARENT_FR)
    monkeypatch.setattr(ingestion, "ARRET_DELAI_S", 0.2)
    contexte = nouveau()
    envoyer(store, filt, record(REPONSE, reply=PARENT), contexte, T_US)              # en vol
    envoyer(store, filt, record(REPONSE_COURTE, reply=PARENT), contexte, T_US + 1)   # attente
    debut = time.monotonic()
    contexte.arreter(store)
    assert time.monotonic() - debut < 1.5           # la sortie n'attend pas le réseau
    ingestion.vidanger(store, contexte)
    assert motifs(store) == {"contexte_abandonne": 1}
    assert compteurs(store) == {"contexte_abandonne": 2}
    assert rows(store, "SELECT text, contexte_type, contexte_texte FROM posts") == [
        (REPONSE, "reponse", None)]
    assert contexte.en_vol == {} and contexte.attentes == {}


def test_sigterm_ecrit_le_lot_et_compte_les_abandons(api, filt, nouveau, monkeypatch, tmp_path):
    api.bloque = threading.Event()
    api.reponses[PARENT] = posts(PARENT_FR)
    monkeypatch.setattr(ingestion, "ARRET_DELAI_S", 0.2)
    monkeypatch.setattr(ingestion, "STOP", True)    # SIGTERM reçu avant la boucle
    chemin = str(tmp_path / "arret.db")
    store = Store(chemin)
    contexte = nouveau()
    envoyer(store, filt, record(REPONSE_COURTE, reply=PARENT), contexte, T_US)
    debut = time.monotonic()
    ingestion.run_stream(store, filt, MIN_DT, 0, 200, 5.0, nouveau=True, contexte=contexte)
    assert time.monotonic() - debut < 1.5
    db = sqlite3.connect(chemin)
    assert db.execute("SELECT reason, SUM(n) FROM ingest_rejects GROUP BY reason").fetchall() == [
        ("contexte_abandonne", 1)]
    assert db.execute("SELECT cle, n FROM ingest_compteurs").fetchall() == [
        ("contexte_abandonne", 1)]
    db.close()


# --- nouveau corpus : gardes secondaires levées (jargon seul, orientation seule, parent) ---

def filt_leve():
    return KeywordFilter({"identites": ["bardella"], "orientations": ["gauche"],
                          "jargon": ["gouvernement"]}, gardes_secondaires=False)


def test_gardes_levees_gardent_jargon_et_orientation_seuls():
    f = filt_leve()
    assert f.test("le gouvernement") is None
    assert f.test("la gauche") is None
    assert f.test("bardella") is None
    assert f.test("bonjour tout le monde") == "rien"


def test_gardes_levees_reponse_jugee_sur_son_texte(api, store, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)                  # parent politique : sans effet
    traiter(store, filt_leve(), record(REPONSE_COURTE, reply=PARENT), nouveau())
    assert rows(store, "SELECT text FROM posts") == []
    assert motifs(store) == {"rien": 1}
    assert api.appels == []                                  # ni attente ni lecture du parent


def test_gardes_levees_reponse_a_jargon_seul_gardee_avec_contexte(api, store, nouveau):
    api.reponses[PARENT] = posts(PARENT_FR)
    traiter(store, filt_leve(), record(PARENT_HORS_SUJET, reply=PARENT), nouveau())
    assert rows(store, "SELECT contexte_type, contexte_texte FROM posts") == [
        ("reponse", "Bardella présente la réforme sur [url] pour les retraites.")]
    assert motifs(store) == {}
