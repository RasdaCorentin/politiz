#!/usr/bin/env python3
"""Producteur Kafka du POC : Jetstream (ou posts synthétiques) -> topic `raw-posts`.

Contrat de sortie : contrat Kafka de docs/technique/contrats-poc.md (topic `raw-posts`). La valeur est l'événement Jetstream
relayé tel que reçu (JSON UTF-8), la clé est nulle. Le pré-filtre garde les créations de
posts en français qui passent la règle de mots-clés de keywords.txt (code d'ingestion.py).

Les journaux n'écrivent que des compteurs : jamais un texte, un identifiant ni une heure
précise.

Usage :
    python producer.py --bootstrap 127.0.0.1:29092                       # flux réel
    python producer.py --source synthetic --rate 50 --duration 60         # posts inventés
Toutes les options ont une variable d'environnement (liste dans docs/technique/contrats-poc.md).
"""
import argparse
import json
import logging
import os
import signal
import sys
import time
from collections import Counter
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import websocket

import ingestion
import synthetic

HERE = Path(__file__).resolve().parent
SOURCES = ("jetstream", "synthetic")
CURSOR_EVERY = 5.0          # s entre deux écritures du curseur
BEAT_EVERY = 10.0           # s entre deux battements (healthcheck)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# --- configuration -----------------------------------------------------------------------

class ConfigError(Exception):
    """Option ou variable d'environnement invalide."""


# (champ, option, variable, conversion, défaut, aide)
OPTIONS = [
    ("source", "--source", "PRODUCER_SOURCE", str, "jetstream", "jetstream ou synthetic"),
    ("bootstrap", "--bootstrap", "KAFKA_BOOTSTRAP", str, "kafka:9092", "serveurs Kafka"),
    ("topic", "--topic", "KAFKA_TOPIC", str, "raw-posts", "topic de sortie"),
    ("keywords", "--keywords", "KEYWORDS_FILE", str, str(HERE / "keywords.txt"),
     "fichier de mots-clés (3 classes)"),
    ("cursor_file", "--cursor-file", "CURSOR_FILE", str, "",
     "curseur Jetstream persistant (vide : désactivé)"),
    ("cursor_max_age", "--cursor-max-age", "CURSOR_MAX_AGE", float, 3600.0,
     "âge maximal d'une reprise par curseur, en s (0 : toujours repartir du direct)"),
    ("cursor_rewind", "--cursor-rewind", "CURSOR_REWIND", float, 5.0,
     "recul à la reprise, en s (les miroirs ne datent pas un événement pareil)"),
    ("heartbeat", "--heartbeat", "PRODUCER_HEARTBEAT", str, "", "fichier de battement"),
    ("idle_timeout", "--idle-timeout", "PRODUCER_IDLE_TIMEOUT", float, 60.0,
     "reconnexion si aucun message depuis N s"),
    ("stall_timeout", "--stall-timeout", "PRODUCER_STALL_TIMEOUT", float, 60.0,
     "plus de battement si un message attend Kafka depuis N s"),
    ("stats_interval", "--stats-interval", "PRODUCER_STATS_INTERVAL", float, 60.0,
     "période des compteurs, en s"),
    ("flush_timeout", "--flush-timeout", "PRODUCER_FLUSH_TIMEOUT", float, 20.0,
     "attente maximale des acquittements à l'arrêt, en s"),
    ("duration", "--duration", "PRODUCER_DURATION", float, 0.0, "durée en s (0 : sans fin)"),
    ("rate", "--rate", "PRODUCER_RATE", float, 5.0, "posts par seconde (mode synthetic)"),
    ("seed", "--seed", "PRODUCER_SEED", int, None, "graine (mode synthetic)"),
    ("lexique_dir", "--lexique-dir", "LEXIQUE_DIR", str, synthetic.repo_lexique_dir(),
     "dossier du lexique (mode synthetic)"),
    ("leak_marker", "--leak-marker", "LEAK_MARKER", str, None,
     "mot-témoin du contrôle de non-fuite (mode synthetic)"),
]


@dataclass(frozen=True)
class Config:
    source: str
    bootstrap: str
    topic: str
    keywords: str
    cursor_file: str
    cursor_max_age: float
    cursor_rewind: float
    heartbeat: str
    idle_timeout: float
    stall_timeout: float
    stats_interval: float
    flush_timeout: float
    duration: float
    rate: float
    seed: int | None
    lexique_dir: str
    leak_marker: str | None
    endpoints: tuple[str, ...]
    mix: synthetic.Mix


def parse_config(argv=None, env=None) -> Config:
    """Options de la ligne de commande, puis variables d'environnement, puis défauts."""
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description="Producteur Kafka : Jetstream ou posts synthétiques")
    for champ, option, var, _, defaut, aide in OPTIONS:
        ap.add_argument(option, dest=champ, default=None, help=f"{aide} [{var}, défaut {defaut!r}]")
    ap.add_argument("--endpoint", action="append", dest="endpoints", default=None,
                    help="miroir Jetstream (répétable ; défaut : les deux miroirs d'ingestion.py)")
    synthetic.add_mix_arguments(ap, env)
    args = ap.parse_args(argv)

    valeurs = {}
    for champ, option, var, cast, defaut, _ in OPTIONS:
        brut = getattr(args, champ)
        if brut is None:
            brut = env.get(var)
            brut = brut if brut is not None and str(brut).strip() else None
        try:
            valeurs[champ] = defaut if brut is None else cast(brut)
        except ValueError:
            raise ConfigError(f"{option} ({var}) : valeur invalide") from None
    try:
        mix = synthetic.mix_from_args(args)
    except ValueError as e:
        raise ConfigError(str(e)) from None
    cfg = Config(**valeurs, endpoints=tuple(args.endpoints or ingestion.ENDPOINTS), mix=mix)

    if cfg.source not in SOURCES:
        raise ConfigError(f"PRODUCER_SOURCE doit valoir {' ou '.join(SOURCES)}")
    if cfg.source == "synthetic" and cfg.rate <= 0:
        raise ConfigError("PRODUCER_RATE doit être positif")
    if min(cfg.duration, cfg.cursor_max_age, cfg.cursor_rewind) < 0:
        raise ConfigError("les durées ne peuvent pas être négatives")
    if min(cfg.idle_timeout, cfg.stall_timeout, cfg.stats_interval, cfg.flush_timeout) <= 0:
        raise ConfigError("les délais doivent être positifs")
    return cfg


# --- compteurs ---------------------------------------------------------------------------

class Counters:
    """Seule donnée écrite dans les journaux. Les clés sont des motifs de rejet ou des types
    d'erreur d'un ensemble fermé, jamais une valeur lue dans un message."""

    def __init__(self):
        self.recus = self.gardes = self.envoyes = self.publies = 0
        self.rejetes: Counter[str] = Counter()
        self.erreurs: Counter[str] = Counter()

    def erreur(self, nom: str) -> None:
        self.erreurs[nom] += 1
        if self.erreurs[nom] == 1:                    # 1re occurrence seulement ; cumul ensuite
            log(f"Erreur ({nom}) : suite dans les compteurs")

    def line(self, **autres) -> str:
        parts = [f"recus={self.recus}", f"gardes={self.gardes}", f"envoyes={self.envoyes}",
                 f"publies={self.publies}"]
        parts += [f"rejet_{k}={v}" for k, v in sorted(self.rejetes.items())]
        parts += [f"erreur_{k}={v}" for k, v in sorted(self.erreurs.items())]
        parts += [f"{k}={v}" for k, v in autres.items()]
        return " ".join(parts)


class Stop:
    """Drapeau d'arrêt (SIGTERM, SIGINT, erreur Kafka fatale, fin de durée)."""

    def __init__(self):
        self.requested = False
        self.fatal = False

    def __call__(self) -> bool:
        return self.requested

    def set(self, *_) -> None:
        self.requested = True


# --- pré-filtre --------------------------------------------------------------------------

def classify(msg, filt: ingestion.KeywordFilter) -> str | None:
    """Motif de rejet d'un événement Jetstream, ou None s'il est gardé (pré-filtre du contrat Kafka).

    Ordre : forme, genre, opération, collection, langue déclarée `fr`, mots-clés.
    """
    if not isinstance(msg, dict):
        return "forme"
    if msg.get("kind") != "commit":
        return "non-commit"                          # événements identity et account
    commit = msg.get("commit")
    if not isinstance(commit, dict):
        return "forme"
    if commit.get("operation") != "create":
        return "operation"                           # update et delete
    if commit.get("collection") != ingestion.COLLECTION:
        return "collection"
    record = commit.get("record")
    if not isinstance(record, dict):
        return "forme"
    langs = record.get("langs")
    if not isinstance(langs, list) or "fr" not in langs:
        return "langue"                              # absente ou autre que `fr`
    text = record.get("text")
    return filt.test(ingestion.normalize(text if isinstance(text, str) else ""))


def event_time_us(msg) -> int:
    t = msg.get("time_us") if isinstance(msg, dict) else None
    return t if isinstance(t, int) and not isinstance(t, bool) and t > 0 else 0


def process_raw(raw, filt, pub: "Publisher", counters: Counters) -> int:
    """Filtre un message reçu et publie les gardés tels quels ; renvoie son time_us (0 si
    inconnu). Une erreur est comptée par type et n'interrompt pas la connexion."""
    counters.recus += 1
    time_us = 0
    try:
        msg = json.loads(raw)
        time_us = event_time_us(msg)
        motif = classify(msg, filt)
        if motif is not None:
            counters.rejetes[motif] += 1
            return time_us
        counters.gardes += 1
        pub.publish(raw if isinstance(raw, bytes) else raw.encode("utf-8"), time_us)
    except Exception as e:
        counters.erreur(type(e).__name__)
    return time_us


# --- Kafka -------------------------------------------------------------------------------

def kafka_config(cfg: Config) -> dict:
    return {
        "bootstrap.servers": cfg.bootstrap,
        "client.id": "sae-producer",
        "enable.idempotence": True,                  # ni perte ni doublon sur nouvel essai
        "acks": "all",
        "linger.ms": 50,
        # Le topic est créé par l'initialisation avec la rétention du contrat : jamais ici.
        "allow.auto.create.topics": False,
        "queue.buffering.max.messages": 100_000,
        "queue.buffering.max.kbytes": 65_536,
        "socket.keepalive.enable": True,
        "log.connection.close": False,
    }


def make_producer(cfg: Config, counters: Counters, stop: Stop):
    """Producteur confluent-kafka. Les journaux de librdkafka sont coupés : ses erreurs
    arrivent par `error_cb` et deviennent des compteurs."""
    from confluent_kafka import Producer

    def on_error(err):
        counters.erreur("kafka_" + err.name())
        if err.fatal():
            stop.fatal = True
            stop.set()

    silencieux = logging.getLogger("producer.rdkafka")
    silencieux.addHandler(logging.NullHandler())
    silencieux.propagate = False
    return Producer(kafka_config(cfg), error_cb=on_error, logger=silencieux)


class Publisher:
    """Publie des valeurs à clé nulle, applique la contre-pression et suit les messages en vol.

    Le suivi donne le curseur sûr (aucun message en vol avant lui) et l'âge du plus ancien
    message sans acquittement (signal de santé).
    """

    def __init__(self, producer, topic: str, counters: Counters, stop=None,
                 clock=time.monotonic):
        self.producer, self.topic, self.counters = producer, topic, counters
        self.stop, self.clock = stop or (lambda: False), clock
        self._seq = 0
        self._inflight: dict[int, tuple[int, float]] = {}    # seq -> (time_us, instant d'envoi)

    @property
    def en_vol(self) -> int:
        return len(self._inflight)

    def publish(self, value: bytes, time_us: int = 0) -> bool:
        self._seq += 1
        seq = self._seq
        self._inflight[seq] = (time_us, self.clock())
        while True:
            try:
                self.producer.produce(self.topic, value=value,
                                      on_delivery=partial(self._delivered, seq))
                break
            except BufferError:
                self.counters.erreur("BufferError")          # file locale pleine : on attend
                self.producer.poll(0.5)
                if self.stop():
                    self._inflight.pop(seq, None)
                    return False
            except Exception as e:
                self.counters.erreur(type(e).__name__)
                self._inflight.pop(seq, None)
                return False
        self.counters.envoyes += 1
        self.producer.poll(0)
        return True

    def _delivered(self, seq: int, err, _msg) -> None:
        self._inflight.pop(seq, None)
        if err is None:
            self.counters.publies += 1
        else:
            self.counters.erreur("livraison_" + err.name())  # message perdu

    def poll(self, timeout: float = 0) -> None:
        self.producer.poll(timeout)

    def flush(self, timeout: float) -> int:
        """Attend les acquittements ; renvoie le nombre de messages non livrés."""
        return self.producer.flush(timeout)

    def safe_cursor(self, last_seen_us: int) -> int:
        """time_us avant lequel tout est acquitté, rejeté ou perdu définitivement."""
        en_vol = [t for t, _ in self._inflight.values() if t > 0]
        return min(en_vol) - 1 if en_vol else last_seen_us

    def oldest_age(self) -> float:
        if not self._inflight:
            return 0.0
        return self.clock() - min(t for _, t in self._inflight.values())


# --- curseur Jetstream -------------------------------------------------------------------

def resume_point(time_us: int, now_us: int, max_age: float, rewind: float) -> int:
    """time_us de reprise pour un curseur, ou 0 pour repartir du direct.

    Un curseur plus vieux que `max_age` n'est pas repris : Kafka ne garde que 1 h (rétention du topic) et
    Spark ignore les événements en retard. Le recul `rewind` couvre l'écart de datation entre
    les deux miroirs ; les doublons sont écartés par Spark (dédoublonnage du texte).
    """
    if time_us <= 0 or max_age <= 0:
        return 0
    time_us = min(time_us, now_us)
    if (now_us - time_us) / 1e6 > max_age:
        return 0
    return max(1, time_us - int(rewind * 1e6))


class CursorFile:
    """Dernier time_us acquitté, dans un petit fichier JSON (volume nommé, facultatif)."""

    def __init__(self, path: str):
        self.path = path
        self.saved = 0

    def load(self) -> int:
        try:
            with open(self.path, encoding="utf-8") as f:
                value = json.load(f)["time_us"]
        except (OSError, ValueError, KeyError, TypeError):
            return 0                                          # absent ou illisible : direct
        self.saved = value if isinstance(value, int) and value > 0 else 0
        return self.saved

    def save(self, time_us: int) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"time_us": time_us}, f)
        os.replace(tmp, self.path)                            # écriture atomique
        self.saved = time_us

    def checkpoint(self, pub: "Publisher", vu_us: int, counters: "Counters") -> None:
        """Écrit le curseur sûr s'il a avancé. Un disque en erreur est compté, pas fatal."""
        sur = pub.safe_cursor(vu_us)
        if sur > self.saved:
            try:
                self.save(sur)
            except OSError as e:
                counters.erreur("curseur_" + type(e).__name__)


# --- boucle d'entretien ------------------------------------------------------------------

class Entretien:
    """Tâches périodiques d'une boucle de source : acquittements, curseur, battement, compteurs."""

    def __init__(self, cfg: Config, pub: Publisher, counters: Counters,
                 cursor: CursorFile | None = None, clock=time.monotonic, extra=None):
        self.cfg, self.pub, self.counters, self.cursor = cfg, pub, counters, cursor
        self.clock, self.extra = clock, extra
        now = clock()
        self.t_cursor = self.t_stats = now
        self.t_beat = float("-inf")                           # premier battement sans attendre

    def tick(self, vivant: bool, vu_us: int = 0) -> None:
        """`vivant` : la source livre des messages ; `vu_us` : time_us du dernier événement."""
        now = self.clock()
        self.pub.poll(0)
        if self.cursor and now - self.t_cursor >= CURSOR_EVERY:
            self.t_cursor = now
            self.cursor.checkpoint(self.pub, vu_us, self.counters)
        if (self.cfg.heartbeat and vivant and now - self.t_beat >= BEAT_EVERY
                and self.pub.oldest_age() < self.cfg.stall_timeout):
            ingestion.beat(self.cfg.heartbeat)
            self.t_beat = now
        if now - self.t_stats >= self.cfg.stats_interval:
            self.t_stats = now
            log(self.stats(vu_us))

    def stats(self, vu_us: int = 0) -> str:
        autres = {"en_vol": self.pub.en_vol}
        if vu_us:                                             # retard du flux, sans l'heure
            autres["retard_s"] = max(0, int(time.time() - vu_us / 1e6))
        if self.extra:
            autres.update(self.extra())
        return self.counters.line(**autres)


# --- sources -----------------------------------------------------------------------------

def stream_url(endpoint: str, resume_us: int) -> str:
    url = f"{endpoint}?wantedCollections={ingestion.COLLECTION}"
    return url + f"&cursor={resume_us}" if resume_us else url


def run_jetstream(cfg: Config, filt, pub: Publisher, counters: Counters, stop: Stop,
                  cursor: CursorFile | None = None, clock=time.monotonic,
                  sleep=time.sleep) -> int:
    """Lit Jetstream jusqu'à l'arrêt ou la fin de durée ; renvoie le dernier time_us vu.

    Reconnexion avec attente exponentielle (2 s à 60 s) et alternance des miroirs. Sans
    aucun message pendant `idle_timeout` s, le flux est considéré figé. Chaque connexion
    reprend au curseur sûr, reculé de `cursor_rewind` s.
    """
    t0 = clock()
    fin = t0 + cfg.duration if cfg.duration > 0 else None

    def fini() -> bool:
        return stop() or (fin is not None and clock() >= fin)

    vu_us = cursor.load() if cursor else 0                    # curseur du volume (avant recul)
    entretien = Entretien(cfg, pub, counters, cursor, clock)
    miroir, tentative, prochaine = 0, 0, t0
    while not fini():
        if clock() < prochaine:                               # attente de reconnexion
            entretien.tick(False, vu_us)
            sleep(0.5)
            continue
        url = stream_url(cfg.endpoints[miroir % len(cfg.endpoints)], resume_point(
            pub.safe_cursor(vu_us), int(time.time() * 1e6), cfg.cursor_max_age, cfg.cursor_rewind))
        miroir += 1
        ws = None
        try:
            ws = websocket.create_connection(url, timeout=10)
            ws.sock.settimeout(1.0)
            tentative = 0
            dernier_msg = clock()
            log(f"Connecté au miroir {(miroir - 1) % len(cfg.endpoints) + 1}")
            while not fini():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    raw = None
                    if clock() - dernier_msg > cfg.idle_timeout:
                        raise ingestion.StreamIdle("flux figé")
                if raw:
                    dernier_msg = clock()
                    vu_us = max(vu_us, process_raw(raw, filt, pub, counters))
                entretien.tick(clock() - dernier_msg < cfg.idle_timeout, vu_us)
            ws.close()
        except Exception as e:
            try:
                if ws is not None:
                    ws.close()
            except Exception:
                pass
            tentative += 1
            attente = min(60, 2 ** min(tentative, 6))
            prochaine = clock() + attente
            counters.erreur(type(e).__name__)
            log(f"Déconnexion ({type(e).__name__}) : reconnexion dans {attente}s")
    if cursor:
        cursor.checkpoint(pub, vu_us, counters)
    return vu_us


def run_synthetic(cfg: Config, gen: synthetic.SyntheticGenerator, pub: Publisher,
                  counters: Counters, stop: Stop, clock=time.monotonic, sleep=time.sleep) -> int:
    """Publie des posts inventés à `cfg.rate` par seconde, sans pré-filtre : les parts
    hors-sujet et étrangères atteignent Kafka pour exercer les filtres de Spark."""
    entretien = Entretien(cfg, pub, counters, None, clock,
                          extra=lambda: {f"synth_{k}": v for k, v in sorted(gen.kinds.items())})
    for _ in synthetic.cadence(cfg.rate, cfg.duration, stop=stop, clock=clock, sleep=sleep):
        value, _t = gen.next_raw()
        counters.recus += 1
        counters.gardes += 1
        pub.publish(value)
        entretien.tick(True)
    return 0


# --- programme ---------------------------------------------------------------------------

def main(argv=None, env=None) -> int:
    try:
        cfg = parse_config(argv, env)
    except ConfigError as e:
        print(f"Configuration invalide : {e}", file=sys.stderr)
        return 2

    stop, counters = Stop(), Counters()
    signal.signal(signal.SIGINT, stop.set)
    signal.signal(signal.SIGTERM, stop.set)
    try:
        if cfg.source == "jetstream":
            filt = ingestion.load_keywords(cfg.keywords)[1]
            gen = None
        else:
            gen = synthetic.SyntheticGenerator(
                synthetic.load_lexique(cfg.lexique_dir), seed=cfg.seed, mix=cfg.mix,
                leak_marker=cfg.leak_marker)
            if not cfg.leak_marker:                           # fourni : jamais écrit ici
                log(f"Mot-témoin généré : {gen.leak_marker}")
        producer = make_producer(cfg, counters, stop)
    except Exception as e:
        print(f"Erreur de démarrage ({type(e).__name__})", file=sys.stderr)
        return 2

    pub = Publisher(producer, cfg.topic, counters, stop)
    cursor = CursorFile(cfg.cursor_file) if cfg.cursor_file and cfg.source == "jetstream" else None
    log(f"Démarrage : source={cfg.source} topic={cfg.topic} bootstrap={cfg.bootstrap} "
        f"curseur={'oui' if cursor else 'non'}")
    try:
        if cfg.source == "jetstream":
            vu_us = run_jetstream(cfg, filt, pub, counters, stop, cursor)
        else:
            vu_us = run_synthetic(cfg, gen, pub, counters, stop)
    except Exception as e:                                    # bogue : type seulement
        counters.erreur("fatale_" + type(e).__name__)
        stop.fatal, vu_us = True, 0

    restant = pub.flush(cfg.flush_timeout)                    # arrêt propre : tout est acquitté
    if restant:
        counters.erreurs["non_livres"] += restant
    if cursor:
        cursor.checkpoint(pub, vu_us, counters)
    log("Arrêt : " + counters.line(en_vol=pub.en_vol))
    return 1 if stop.fatal or restant else 0


if __name__ == "__main__":
    sys.exit(main())
