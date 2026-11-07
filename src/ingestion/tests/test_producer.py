"""Tests unitaires du producteur. Aucun réseau, aucun broker : Kafka est simulé."""
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("confluent_kafka")

import ingestion
import producer
from producer import Config, Counters, CursorFile, Publisher, Stop

KEYWORDS = Path(__file__).resolve().parents[1] / "keywords.txt"


@pytest.fixture(scope="module")
def filtre():
    return ingestion.load_keywords(str(KEYWORDS))[1]


class FauxErr:
    def __init__(self, nom="ERR"):
        self.nom = nom

    def name(self):
        return self.nom


class FauxProducer:
    """Mémorise les envois ; `livrer()` appelle les rappels comme le ferait poll()."""

    def __init__(self, plein=0):
        self.envoyes, self.rappels, self.plein = [], [], plein

    def produce(self, topic, value=None, key=None, on_delivery=None):
        if self.plein:
            self.plein -= 1
            raise BufferError("file pleine")
        self.envoyes.append((topic, key, value))
        self.rappels.append(on_delivery)

    def poll(self, timeout=0):
        return 0

    def livrer(self, err=None):
        for cb in self.rappels:
            cb(err, None)
        self.rappels = []

    def flush(self, timeout):
        return len(self.rappels)


def evenement(text="Glucksmann a parlé", langs=("fr",), op="create", kind="commit",
              collection="app.bsky.feed.post", time_us=1_700_000_000_000_000):
    commit = {"rev": "r", "operation": op, "collection": collection, "rkey": "k"}
    if op != "delete":
        commit["record"] = {"$type": collection, "text": text, "langs": list(langs),
                            "createdAt": "2026-01-01T00:00:00Z"}
    return {"did": "did:plc:synthetic0001", "time_us": time_us, "kind": kind, "commit": commit}


def classer(filtre, msg):
    return producer.classify(msg, filtre)


# --- pré-filtre --------------------------------------------------------------------------

def test_evenement_garde(filtre):
    assert classer(filtre, evenement()) is None


@pytest.mark.parametrize("msg,motif", [
    (evenement(kind="identity"), "non-commit"),
    (evenement(kind="account"), "non-commit"),
    (evenement(op="update"), "operation"),
    (evenement(op="delete"), "operation"),
    (evenement(collection="app.bsky.feed.like"), "collection"),
    (evenement(langs=("en",)), "langue"),
    (evenement(langs=()), "langue"),
    ([], "forme"),
    ({"kind": "commit", "commit": "x"}, "forme"),
])
def test_motifs_de_rejet(filtre, msg, motif):
    assert classer(filtre, msg) == motif


def test_langue_absente(filtre):
    msg = evenement()
    del msg["commit"]["record"]["langs"]
    assert classer(filtre, msg) == "langue"


def test_hors_sujet_rejete_par_les_mots_cles(filtre):
    motif = classer(filtre, evenement(text="Une recette de gâteau au chocolat"))
    assert motif is not None and motif not in {"langue", "operation", "collection"}


def test_texte_absent_rejete(filtre):
    msg = evenement()
    del msg["commit"]["record"]["text"]
    assert classer(filtre, msg) is not None


# --- relais ------------------------------------------------------------------------------

def test_valeur_relayee_telle_que_recue_et_cle_nulle(filtre):
    brut = json.dumps(evenement(text="Glucksmann  « é » é"), ensure_ascii=False,
                      separators=(",", ":")).encode()
    fp, c = FauxProducer(), Counters()
    pub = Publisher(fp, "raw-posts", c)
    producer.process_raw(brut, filtre, pub, c)
    fp.livrer()
    assert fp.envoyes == [("raw-posts", None, brut)]
    assert (c.recus, c.gardes, c.envoyes, c.publies) == (1, 1, 1, 1)


def test_texte_recu_en_str_est_encode_utf8(filtre):
    brut = json.dumps(evenement(text="Glucksmann é"), ensure_ascii=False)
    fp, c = FauxProducer(), Counters()
    producer.process_raw(brut, filtre, Publisher(fp, "t", c), c)
    assert fp.envoyes[0][2] == brut.encode("utf-8")


def test_rejet_compte_par_motif_sans_publier(filtre):
    fp, c = FauxProducer(), Counters()
    pub = Publisher(fp, "t", c)
    for msg in (evenement(op="delete"), evenement(langs=("en",)), evenement(langs=("en",))):
        producer.process_raw(json.dumps(msg), filtre, pub, c)
    assert fp.envoyes == []
    assert c.rejetes == {"operation": 1, "langue": 2} and c.recus == 3


def test_json_invalide_est_une_erreur_comptee(filtre):
    fp, c = FauxProducer(), Counters()
    producer.process_raw(b"{pas du json", filtre, Publisher(fp, "t", c), c)
    assert c.erreurs and not fp.envoyes


def test_les_compteurs_n_exposent_aucun_contenu(filtre):
    c = Counters()
    c.rejetes["langue"] += 1
    c.erreurs["JSONDecodeError"] += 1
    ligne = c.line(en_vol=0)
    assert "did:" not in ligne and "Glucksmann" not in ligne
    assert "rejet_langue=1" in ligne and "erreur_JSONDecodeError=1" in ligne


# --- publication -------------------------------------------------------------------------

def test_contre_pression_attend_la_file_locale():
    fp, c = FauxProducer(plein=2), Counters()
    pub = Publisher(fp, "t", c)
    assert pub.publish(b"x", 5) is True
    assert c.erreurs["BufferError"] == 2 and len(fp.envoyes) == 1


def test_contre_pression_abandonnee_a_l_arret():
    stop = Stop()
    stop.set()
    pub = Publisher(FauxProducer(plein=99), "t", Counters(), stop)
    assert pub.publish(b"x", 5) is False and pub.en_vol == 0


def test_livraison_en_erreur_est_comptee():
    fp, c = FauxProducer(), Counters()
    pub = Publisher(fp, "t", c)
    pub.publish(b"x", 5)
    fp.livrer(FauxErr("MSG_TIMED_OUT"))
    assert c.publies == 0 and c.erreurs["livraison_MSG_TIMED_OUT"] == 1 and pub.en_vol == 0


def test_curseur_sur_reste_avant_le_plus_ancien_en_vol():
    fp, c = FauxProducer(), Counters()
    pub = Publisher(fp, "t", c)
    pub.publish(b"a", 100)
    pub.publish(b"b", 200)
    assert pub.safe_cursor(300) == 99
    fp.livrer()
    assert pub.safe_cursor(300) == 300


def test_age_du_plus_ancien_message():
    t = [10.0]
    pub = Publisher(FauxProducer(), "t", Counters(), clock=lambda: t[0])
    assert pub.oldest_age() == 0
    pub.publish(b"a", 1)
    t[0] = 25.0
    assert pub.oldest_age() == 15.0


def test_configuration_kafka_du_contrat():
    cfg = producer.parse_config([], {})
    k = producer.kafka_config(cfg)
    assert k["enable.idempotence"] is True and k["acks"] == "all" and k["linger.ms"] == 50
    assert k["allow.auto.create.topics"] is False


# --- curseur -----------------------------------------------------------------------------

def test_reprise_du_curseur():
    now = 2_000_000_000_000_000
    assert producer.resume_point(0, now, 3600, 5) == 0
    assert producer.resume_point(now - 10_000_000, now, 3600, 5) == now - 15_000_000
    assert producer.resume_point(now - 7200 * 1_000_000, now, 3600, 5) == 0     # trop vieux
    assert producer.resume_point(now - 10_000_000, now, 0, 5) == 0              # désactivé
    assert producer.resume_point(now + 99, now, 3600, 0) == now                 # futur borné


def test_fichier_curseur(tmp_path):
    f = CursorFile(str(tmp_path / "c.json"))
    assert f.load() == 0
    f.save(42)
    assert CursorFile(str(tmp_path / "c.json")).load() == 42
    (tmp_path / "c.json").write_text("pas du json")
    assert CursorFile(str(tmp_path / "c.json")).load() == 0


def test_checkpoint_n_ecrit_que_le_curseur_sur(tmp_path):
    fp, c = FauxProducer(), Counters()
    pub = Publisher(fp, "t", c)
    f = CursorFile(str(tmp_path / "c.json"))
    pub.publish(b"a", 100)
    f.checkpoint(pub, 500, c)
    assert f.saved == 99
    fp.livrer()
    f.checkpoint(pub, 500, c)
    assert f.saved == 500


def test_url_du_flux():
    assert producer.stream_url("wss://x/subscribe", 0) == \
        "wss://x/subscribe?wantedCollections=app.bsky.feed.post"
    assert producer.stream_url("wss://x/subscribe", 7).endswith("&cursor=7")


# --- configuration, battement, arrêt -----------------------------------------------------

def test_configuration_par_variables():
    cfg = producer.parse_config([], {"PRODUCER_SOURCE": "synthetic", "PRODUCER_RATE": "12.5",
                                     "KAFKA_BOOTSTRAP": "h:1", "LEAK_MARKER": "temoin",
                                     "CURSOR_FILE": "/data/cursor.json"})
    assert (cfg.source, cfg.rate, cfg.bootstrap, cfg.leak_marker) == \
        ("synthetic", 12.5, "h:1", "temoin")
    assert cfg.endpoints == tuple(ingestion.ENDPOINTS) and cfg.cursor_file == "/data/cursor.json"


def test_option_prioritaire_sur_variable():
    assert producer.parse_config(["--rate", "3"], {"PRODUCER_RATE": "9"}).rate == 3


@pytest.mark.parametrize("argv,env", [
    ([], {"PRODUCER_SOURCE": "autre"}),
    ([], {"PRODUCER_SOURCE": "synthetic", "PRODUCER_RATE": "0"}),
    ([], {"PRODUCER_RATE": "abc"}),
    ([], {"PRODUCER_DURATION": "-1"}),
])
def test_configuration_invalide(argv, env):
    with pytest.raises(producer.ConfigError):
        producer.parse_config(argv, env)


def cfg_battement(chemin, **kw):
    return producer.parse_config(["--heartbeat", str(chemin)] + kw.pop("argv", []), {})


def test_battement_seulement_si_le_flux_vit(tmp_path):
    hb = tmp_path / "hb"
    t = [0.0]
    pub = Publisher(FauxProducer(), "t", Counters(), clock=lambda: t[0])
    e = producer.Entretien(cfg_battement(hb), pub, Counters(), clock=lambda: t[0])
    e.tick(False)
    assert not hb.exists()                      # flux figé : pas de battement
    e.tick(True)
    assert hb.exists()


def test_pas_de_battement_si_kafka_ne_repond_plus(tmp_path):
    hb = tmp_path / "hb"
    t = [0.0]
    pub = Publisher(FauxProducer(), "t", Counters(), clock=lambda: t[0])
    pub.publish(b"a", 1)
    t[0] = 100.0                                # message sans acquittement depuis 100 s
    producer.Entretien(cfg_battement(hb), pub, Counters(), clock=lambda: t[0]).tick(True)
    assert not hb.exists()


def test_synthetique_publie_au_debit_et_s_arrete():
    cfg = producer.parse_config(["--source", "synthetic", "--rate", "500", "--duration", "0.4",
                                 "--seed", "1"], {})
    from synthetic import SyntheticGenerator, load_lexique
    gen = SyntheticGenerator(load_lexique(cfg.lexique_dir), seed=1, mix=cfg.mix)
    fp, c = FauxProducer(), Counters()
    producer.run_synthetic(cfg, gen, Publisher(fp, "t", c), c, Stop())
    assert 120 <= len(fp.envoyes) <= 280
    assert all(k is None and json.loads(v)["did"].startswith("did:plc:synthetic")
               for _, k, v in fp.envoyes)


def test_arret_demande_interrompt_le_mode_synthetique():
    cfg = producer.parse_config(["--source", "synthetic", "--rate", "50"], {})
    from synthetic import SyntheticGenerator, load_lexique
    gen = SyntheticGenerator(load_lexique(cfg.lexique_dir), seed=1, mix=cfg.mix)
    stop = Stop()
    stop.set()
    t0 = time.monotonic()
    producer.run_synthetic(cfg, gen, Publisher(FauxProducer(), "t", Counters()), Counters(), stop)
    assert time.monotonic() - t0 < 1
