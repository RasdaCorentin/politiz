"""Test d'intégration du producteur contre un Kafka jetable.

Lancé seulement si KAFKA_TEST_BOOTSTRAP est défini (ex. 127.0.0.1:29192) :
    KAFKA_TEST_BOOTSTRAP=127.0.0.1:29192 pytest -m integration tests/test_producer_integration.py
Chaque test crée son topic (4 partitions, comme le contrat Kafka) et le supprime ensuite.
"""
import json
import os
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("yaml")
confluent_kafka = pytest.importorskip("confluent_kafka")

import ingestion
import producer
import synthetic

BOOTSTRAP = os.environ.get("KAFKA_TEST_BOOTSTRAP")
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not BOOTSTRAP, reason="KAFKA_TEST_BOOTSTRAP non défini")]

KEYWORDS = Path(__file__).resolve().parents[1] / "keywords.txt"


@pytest.fixture
def topic():
    from confluent_kafka.admin import AdminClient, NewTopic
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    nom = "test-raw-posts-" + uuid.uuid4().hex[:8]
    for f in admin.create_topics([NewTopic(nom, num_partitions=4, replication_factor=1)]).values():
        f.result(15)
    yield nom
    for f in admin.delete_topics([nom]).values():
        try:
            f.result(15)
        except Exception:
            pass


def lire(topic, attendu, delai=20):
    """Tous les messages du topic (clé, valeur) jusqu'à `attendu` ou délai."""
    from confluent_kafka import Consumer
    c = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "t-" + uuid.uuid4().hex,
                  "auto.offset.reset": "earliest", "enable.auto.commit": False})
    c.subscribe([topic])
    out, fin = [], time.monotonic() + delai
    while len(out) < attendu and time.monotonic() < fin:
        m = c.poll(0.5)
        if m is not None and not m.error():
            out.append((m.key(), m.value()))
    c.close()
    return out


def evenement(text="Glucksmann a parlé", langs=("fr",), op="create", kind="commit",
              collection="app.bsky.feed.post", n=0):
    commit = {"rev": "r", "operation": op, "collection": collection, "rkey": f"k{n}"}
    if op != "delete":
        commit["record"] = {"$type": collection, "text": text, "langs": list(langs)}
    return {"did": "did:plc:synthetic0001", "time_us": 1_700_000_000_000_000 + n,
            "kind": kind, "commit": commit}


def test_pre_filtre_relais_et_motifs(topic):
    filt = ingestion.load_keywords(str(KEYWORDS))[1]
    cfg = producer.parse_config(["--bootstrap", BOOTSTRAP, "--topic", topic], {})
    c, stop = producer.Counters(), producer.Stop()
    pub = producer.Publisher(producer.make_producer(cfg, c, stop), topic, c, stop)

    gardes = [json.dumps(evenement(text=f"Glucksmann a parlé é{i}", n=i), ensure_ascii=False,
                         separators=(",", ":")).encode() for i in range(5)]
    rejets = {
        "non-commit": evenement(kind="identity", n=10),
        "operation": evenement(op="delete", n=11),
        "collection": evenement(collection="app.bsky.feed.like", n=12),
        "langue": evenement(langs=("en",), n=13),
        "rien": evenement(text="Une recette de gâteau", n=14),
    }
    for brut in gardes:
        producer.process_raw(brut, filt, pub, c)
    for msg in rejets.values():
        producer.process_raw(json.dumps(msg), filt, pub, c)
    assert pub.flush(15) == 0

    assert (c.recus, c.gardes, c.publies) == (10, 5, 5)
    assert dict(c.rejetes) == {k: 1 for k in rejets}
    lus = lire(topic, 5)
    assert sorted(v for _, v in lus) == sorted(gardes)         # valeur inchangée, octet pour octet
    assert all(k is None for k, _ in lus)                      # clé nulle


def test_debit_synthetique_et_marqueur(topic):
    marqueur = "temoinfuite" + uuid.uuid4().hex[:6]
    cfg = producer.parse_config(
        ["--bootstrap", BOOTSTRAP, "--topic", topic, "--source", "synthetic", "--rate", "100",
         "--duration", "5", "--seed", "7", "--leak-marker", marqueur, "--leak-ratio", "0.2"], {})
    gen = synthetic.SyntheticGenerator(synthetic.load_lexique(cfg.lexique_dir), seed=7,
                                       mix=cfg.mix, leak_marker=marqueur)
    c, stop = producer.Counters(), producer.Stop()
    pub = producer.Publisher(producer.make_producer(cfg, c, stop), topic, c, stop)
    t0 = time.monotonic()
    producer.run_synthetic(cfg, gen, pub, c, stop)
    duree = time.monotonic() - t0
    assert pub.flush(15) == 0

    assert 4.5 <= duree <= 7
    assert 400 <= c.publies <= 550                             # 100 posts/s pendant 5 s
    assert not c.erreurs
    lus = lire(topic, c.publies)
    assert len(lus) == c.publies
    evts = [json.loads(v) for _, v in lus]
    assert all(k is None for k, _ in lus)
    assert all(e["did"].startswith("did:plc:synthetic") for e in evts)
    avec = sum(marqueur in json.dumps(e, ensure_ascii=False) for e in evts)
    assert 0.1 * len(evts) <= avec <= 0.3 * len(evts)
