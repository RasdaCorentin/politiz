#!/usr/bin/env python3
"""Ingestion Bluesky -> SQLite (texte + horodatage uniquement).

Méthode : firehose Jetstream public (WebSocket, une connexion persistante,
aucune limite de requêtes à respecter). Filtrage côté client selon keywords.txt
et la langue (fr). Aucun identifiant d'auteur n'est stocké (Livr. 1 M1/M2) :
seuls created_at, text et un hash local de déduplication sont écrits.

Usage :
    python ingestion.py --db data/bluesky_posts.db                 # continu
    python ingestion.py --duration 60                              # test 60 s
    python ingestion.py --keywords keywords.txt --batch-size 200
    python ingestion.py --backfill 500 --db data/bluesky_posts.db  # complément AppView
"""
import argparse
import hashlib
import json
import os
import re
import signal
import sqlite3
import queue
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import websocket

ENDPOINTS = [
    "wss://jetstream1.us-east.bsky.network/subscribe",
    "wss://jetstream2.us-east.bsky.network/subscribe",
]
COLLECTION = "app.bsky.feed.post"

# mots-clés par défaut si --keywords absent (normalisés sans accents/lowercase)
DEFAULT_KEYWORDS = [
    "presidentielle", "presidentiel", "presidential", "election", "elections",
    "candidat", "candidats", "scrutin", "primaire", "vote", "votants",
    "electoral", "electoraux", "electeur", "electeurs", "vote blanc",
]

# fallback si aucun keywords.txt : identités explicites minimales
DEFAULT_IDENTITY_KEYWORDS = [
    "le pen", "bardella", "melenchon", "glucksmann", "zemmour", "attal",
    "rassemblement national", "rn", "lfi", "la france insoumise",
    "parti socialiste", "pcf", "les republicains", "lr",
]

# contexte des réponses et citations (nouveau corpus) : lecture publique getPosts
GETPOSTS_URL = "https://api.bsky.app/xrpc/app.bsky.feed.getPosts"
USER_AGENT = "sae-data-poc/0.1 (education)"
CONTEXTE_TIMEOUT_S = 2.0                 # délai de connexion, puis de chaque lecture (requests)
CONTEXTE_MAX_PAR_MINUTE_DEFAUT = 60      # une requête par seconde ; non mesuré, à surveiller (429)
CONTEXTE_FILE_MAX = 60                   # demandes de contexte en file (au-delà : file pleine)
GARDE_DELAI_S = 60.0                     # réponse en attente de la garde de son parent : délai
GARDE_ATTENTE_MAX = 50                   # réponses en attente de la garde de leur parent (mémoire)
ARRET_DELAI_S = 5.0                      # arrêt (SIGTERM) : attente maximale du fil de lecture

STOP = False


def set_stop(signum, _frame):
    global STOP
    STOP = True


def normalize(text: str) -> str:
    """Minuscule + suppression des accents (presidentielle ≡ présidentielle)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


URL_RE = re.compile(r"\b(?:https?://|www\.)\S*[^\s.,;:!?\"')\]]")   # sans ponctuation finale
MENTION_RE = re.compile(r"(?<![\w@])@[\w-]+(?:\.[\w-]+)*")


NOM_PUBLIC_MIN = 4   # caractères, sans espace ni tiret : écarte « rn », « ps », « re », « lo »…


def noms_publics(identites: list[str]) -> dict[str, str]:
    """Clé de handle (sans espace ni tiret) -> expression de `identites`, pour les noms d'au moins 4 caractères."""
    noms = {}
    for expr in identites:
        cle = re.sub(r"[ \-]", "", expr)
        if len(cle) >= NOM_PUBLIC_MIN:
            noms[cle] = expr
    return noms


HASHTAG_RE = re.compile(r"#(\w+)")


def _distance_approchee(nom: str, texte: str) -> int:
    """Distance d'édition minimale entre `nom` et une sous-chaîne de `texte` (algorithme de Sellers)."""
    prec = list(range(len(nom) + 1))
    meilleure = prec[-1]
    for c in texte:
        cur = [0]                                    # la sous-chaîne peut commencer ici
        for i in range(1, len(nom) + 1):
            cout = 0 if nom[i - 1] == c else 1
            cur.append(min(prec[i] + 1, cur[i - 1] + 1, prec[i - 1] + cout))
        prec = cur
        meilleure = min(meilleure, prec[-1])
    return meilleure


def nom_public_dans(fragment: str, noms: dict[str, str]) -> str | None:
    """Nom public de `noms` approché dans `fragment` (mention ou hashtag), ou None.

    Insensible à la casse et aux accents, sans espace, tiret ni point. Une erreur au plus pour un
    nom de 4 à 7 lettres (sinon « lepen » accrocherait « penser »), deux erreurs au plus au-delà.
    """
    cible = re.sub(r"[\s\-_.]", "", normalize(fragment))
    for cle, expr in noms.items():
        if _distance_approchee(cle, cible) <= (1 if len(cle) <= 7 else 2):
            return expr
    return None


def nom_public_marque(texte: str, noms: dict[str, str]) -> str | None:
    """Premier nom public approché dans une mention (@handle) ou un hashtag du texte brut."""
    for fragment in MENTION_RE.findall(texte) + HASHTAG_RE.findall(texte):
        nom = nom_public_dans(fragment, noms)
        if nom:
            return nom
    return None


def masquer(texte: str, noms: dict[str, str] | None = None) -> str:
    """Remplace les URL par `[url]` et les mentions @ par `[mention]` (M11, corpus de développement).

    Exception : si le handle contient un nom public de `noms` (candidat ou parti, approché), la
    mention devient `[mention:<nom>]`. Les autres personnes restent masquées.
    """
    def marque(m: re.Match) -> str:
        nom = nom_public_dans(m.group(0)[1:], noms or {})
        return f"[mention:{nom}]" if nom else "[mention]"
    return MENTION_RE.sub(marque, URL_RE.sub("[url]", texte))


def est_francais(texte: str) -> bool:
    """Vrai si langdetect classe le texte en français (détecteur épinglé, graine fixe).

    Texte vide ou sans indice lexical (emojis seuls) : langdetect lève une exception,
    le texte n'est pas tenu pour français. Import local : le producteur importe ce
    module sans cette dépendance.
    """
    from langdetect import DetectorFactory, LangDetectException, detect
    DetectorFactory.seed = 0                    # même réponse d'un lancement à l'autre
    try:
        return detect(texte) == "fr"
    except LangDetectException:
        return False


# classes machine-lisibles du keywords.txt : '#identites', '#orientations', '#jargon'
SECTIONS = ("identites", "orientations", "jargon")


class KeywordFilter:
    """Décision de garde à 3 classes : identites OU (orientations ET jargon).

    gardes_secondaires=False (nouveau corpus) : identites OU orientations OU jargon ; le jargon
    ou l'orientation seuls suffisent.
    patterns compilés une fois (frontières de mot, texte normalisé sans accents) ;
    test() renvoie None si le post est gardé, sinon la raison du rejet (audit).
    Sans classes explicites (pas de marqueurs) : mode compat 'tout matche'.
    """

    def __init__(self, classes: dict[str, list[str]], gardes_secondaires: bool = True):
        self.legacy = not any(classes.values())
        self.gardes_secondaires = gardes_secondaires
        self.noms = noms_publics(classes.get("identites") or [])
        self.ids = re.compile(_alt(classes.get("identites") or []))
        self.orient = re.compile(_alt(classes.get("orientations") or []))
        self.jargon = re.compile(_alt(classes.get("jargon") or
                                      ([] if not self.legacy else list(DEFAULT_KEYWORDS))))

    def test(self, norm: str) -> str | None:
        if self.ids.search(norm):
            return None                              # mention explicite candidat/parti
        po = self.orient.search(norm) is not None
        pj = self.jargon.search(norm) is not None
        if self.legacy:
            return None if pj else "rien"
        if not self.gardes_secondaires:
            return None if (po or pj) else "rien"
        if po and pj:
            return None                              # orientation + jargon politique
        if pj:
            return "jargon-seul"
        if po:
            return "orientation-seule"
        return "rien"


def _alt(kws: list[str]) -> str:
    """Regex alternée compilée ; '' → pattern qui ne matche rien."""
    return r"\b(" + "|".join(map(re.escape, kws)) + r")\b" if kws else r"(?!)x"


def load_keywords(path: str | None) -> tuple[list[str], KeywordFilter]:
    """Parse keywords.txt en classes ; renvoie (requêtes API brutes, filtre).

    les lignes précédant un marqueur de classe et les commentaires sont ignorés ;
    pour les requêtes AppView du backfill, le texte brut (avec accents) de
    #identites est utilisé.
    """
    if not path:
        classes = {"identites": list(DEFAULT_IDENTITY_KEYWORDS), "orientations": [],
                   "jargon": list(DEFAULT_KEYWORDS)}
        query_kws = list(DEFAULT_IDENTITY_KEYWORDS)
    else:
        classes: dict[str, list[str]] = {s: [] for s in SECTIONS}
        current: str | None = None
        for line in open(path, encoding="utf-8"):
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                tag = s.lstrip("#").strip().lower()
                if tag in SECTIONS:
                    current = tag
                continue                        # commentaire libre
            if current is None:
                continue                        # en-tête sans classe
            classes[current].append(normalize(s))
        query_kws = _section_raw(path, "identites")
    filt = KeywordFilter(classes)
    sized = ", ".join(f"{s}={len(v)}" for s, v in classes.items())
    print(f"mots-cles {sized} (mode {'legacy' if filt.legacy else '3 classes'})",
          flush=True)
    return query_kws, filt


def _section_raw(path: str, section: str) -> list[str]:
    """Lignes brutes (avec accents) de la section '#<section>'."""
    out: list[str] = []
    current: str | None = None
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            tag = s.lstrip("#").strip().lower()
            current = tag if tag in SECTIONS else current
            continue
        if current == section:
            out.append(s)
    return out


def dedup_key(created_at: str, text: str) -> str:
    """Hash local (aucun champ identifiant d'auteur)."""
    return hashlib.sha256((created_at + "\x00" + text).encode("utf-8")).hexdigest()[:32]


@dataclass
class LienContexte:
    """Demande de contexte d'un post encore en file d'écriture (côté thread principal)."""
    ctype: str | None                       # 'reponse' ou 'citation'
    rowid: int | None = None                # ligne du post, connue à l'écriture
    texte: str | None = None                # texte masqué du contexte, quand il est reçu


class Store:
    """SQLite en mode WAL, écritures en lot (marge débit) : jamais 1 write/message.

    Seul le thread principal ouvre et écrit la base.
    """

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                text      TEXT NOT NULL,
                dedup_key TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS ingest_stats (
                ts     TEXT PRIMARY KEY,
                events INTEGER NOT NULL DEFAULT 0,
                kept   INTEGER NOT NULL DEFAULT 0,
                dropped INTEGER NOT NULL DEFAULT 0,
                duplicates INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ingest_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ingest_rejects (
                ts     TEXT NOT NULL,
                reason TEXT NOT NULL,
                n      INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (ts, reason)
            );
            CREATE TABLE IF NOT EXISTS ingest_compteurs (
                ts  TEXT NOT NULL,
                cle TEXT NOT NULL,
                n   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (ts, cle)
            );
        """)
        self._migrate()
        self.db.commit()
        # (created_at, text, dedup_key, minute, contexte_type, contexte_texte, req)
        self.pending: list[tuple[str, str, str, str, str | None, str | None, int | None]] = []
        self.contextes: dict[int, LienContexte] = {}           # demandes de contexte en vol
        self.stats_minute: dict[str, list[int]] = {}
        self.rejects: dict[tuple[str, str], int] = {}
        self.compteurs: dict[tuple[str, str], int] = {}        # (minute, clé) → n
        self.cumul: dict[str, int] = {}                        # clé → n, depuis le démarrage
        self.ignored_ops = 0                    # update/delete écartés (mémoire, suivi seulement)
        row = self.db.execute(
            "SELECT value FROM ingest_meta WHERE key='jetstream_cursor'"
        ).fetchone()
        self.cursor = int(row[0]) if row else 0

    def _migrate(self) -> None:
        """Migration additive d'une base à l'ancien schéma (idempotente).

        Avant, les motifs de rejet ('rien', 'jargon-seul'…) étaient écrits dans
        ingest_stats.ts à la place de la minute. On déplace ces lignes vers
        ingest_rejects (ts='ancien-schema') ; aucun compteur n'est perdu.
        """
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(ingest_stats)")}
        if "duplicates" not in cols:
            self.db.execute(
                "ALTER TABLE ingest_stats ADD COLUMN duplicates INTEGER NOT NULL DEFAULT 0")
        self.db.execute(
            "INSERT INTO ingest_rejects(ts, reason, n) "
            "SELECT 'ancien-schema', ts, dropped FROM ingest_stats "
            "WHERE ts NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T*' "
            "ON CONFLICT(ts, reason) DO UPDATE SET n = n + excluded.n"
        )
        self.db.execute(
            "DELETE FROM ingest_stats "
            "WHERE ts NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T*'"
        )
        # contexte des réponses et citations (nouveau corpus) : colonnes nulles par défaut
        cols_posts = {r[1] for r in self.db.execute("PRAGMA table_info(posts)")}
        for col in ("contexte_type", "contexte_texte"):
            if col not in cols_posts:
                self.db.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT")

    def accept(self, created_at: str, text: str, event_minute: str,
               contexte_type: str | None = None, contexte_texte: str | None = None,
               req: int | None = None) -> None:
        """Met un post en attente. Kept/doublon sont comptés au flush (INSERT OR IGNORE).

        req : demande de contexte en vol pour ce post. Son texte, reçu plus tard, est écrit
        par UPDATE sur la ligne du post au flush suivant (contexte_recu).
        """
        self.stats_minute.setdefault(event_minute, [0, 0, 0, 0])[0] += 1
        self.pending.append((created_at, text, dedup_key(created_at, text), event_minute,
                             contexte_type, contexte_texte, req))
        if req is not None:
            self.contextes[req] = LienContexte(contexte_type)

    def contexte_recu(self, req: int, texte: str) -> None:
        """Texte de contexte reçu pour une demande ; il est écrit au prochain flush."""
        lien = self.contextes.get(req)
        if lien is not None:
            lien.texte = texte

    def compte(self, minute: str, cle: str) -> None:
        """Compteur par minute (garde par parent, contexte absent…). Jamais de contenu."""
        self.compteurs[(minute, cle)] = self.compteurs.get((minute, cle), 0) + 1
        self.cumul[cle] = self.cumul.get(cle, 0) + 1

    def reject(self, event_minute: str, reason: str) -> None:
        """Compte un rejet : dropped sur la minute, motif dans ingest_rejects."""
        m = self.stats_minute.setdefault(event_minute, [0, 0, 0, 0])
        m[0] += 1
        m[2] += 1
        key = (event_minute, reason)
        self.rejects[key] = self.rejects.get(key, 0) + 1

    def flush(self, cursor: int) -> None:
        """Écrit lot, stats, motifs, compteurs, contexte reçu et cursor dans une seule transaction.

        Le doublon est détecté par INSERT OR IGNORE : rowcount vaut 0 si la
        dedup_key existe déjà (reprise par cursor, post identique) ; la demande de
        contexte du doublon se rattache alors à la ligne existante. Le texte de
        contexte n'est écrit que dans une colonne vide. En cas d'erreur SQLite :
        rollback, l'état en mémoire est conservé (nouvel essai).
        """
        stats = {ts: list(v) for ts, v in self.stats_minute.items()}
        ecrits: list[int] = []                  # demandes écrites par ce flush
        try:
            for created_at, text, key, minute, ctype, ctexte, req in self.pending:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO posts(created_at, text, dedup_key, "
                    "contexte_type, contexte_texte) VALUES (?,?,?,?,?)",
                    (created_at, text, key, ctype, ctexte))
                stats.setdefault(minute, [0, 0, 0, 0])[1 if cur.rowcount == 1 else 3] += 1
                if req is not None and req in self.contextes:
                    if cur.rowcount == 1:
                        rowid = cur.lastrowid
                    else:
                        row = self.db.execute(
                            "SELECT id FROM posts WHERE dedup_key = ?", (key,)).fetchone()
                        rowid = row[0] if row else None
                    self.contextes[req].rowid = rowid
            for req, lien in self.contextes.items():
                if lien.texte is not None and lien.rowid is not None:
                    self.db.execute(
                        "UPDATE posts SET contexte_type = ?, contexte_texte = ? "
                        "WHERE id = ? AND contexte_texte IS NULL",
                        (lien.ctype, lien.texte, lien.rowid))
                    ecrits.append(req)
            for ts, (e, k, d, dup) in stats.items():
                self.db.execute(
                    "INSERT INTO ingest_stats(ts, events, kept, dropped, duplicates) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(ts) DO UPDATE SET "
                    "events=events+?, kept=kept+?, dropped=dropped+?, duplicates=duplicates+?",
                    (ts, e, k, d, dup, e, k, d, dup),
                )
            for (ts, reason), n in self.rejects.items():
                self.db.execute(
                    "INSERT INTO ingest_rejects(ts, reason, n) VALUES (?,?,?) "
                    "ON CONFLICT(ts, reason) DO UPDATE SET n=n+excluded.n", (ts, reason, n)
                )
            for (ts, cle), n in self.compteurs.items():
                self.db.execute(
                    "INSERT INTO ingest_compteurs(ts, cle, n) VALUES (?,?,?) "
                    "ON CONFLICT(ts, cle) DO UPDATE SET n=n+excluded.n", (ts, cle, n)
                )
            self.db.execute(
                "INSERT INTO ingest_meta(key, value) VALUES ('jetstream_cursor', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(cursor),)
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for req in ecrits:
            del self.contextes[req]
        self.pending.clear()
        self.stats_minute.clear()
        self.rejects.clear()
        self.compteurs.clear()

    def close(self) -> None:
        self.db.close()


def cible_contexte(record: dict) -> tuple[str, str] | None:
    """Post référencé par un post : ('reponse', uri) ou ('citation', uri), sinon None.

    Une réponse prime sur une citation (un post peut être les deux). L'URI ne sert
    qu'à l'appel : il n'est ni stocké ni journalisé.
    """
    uri = ((record.get("reply") or {}).get("parent") or {}).get("uri")
    if isinstance(uri, str) and uri:
        return "reponse", uri
    embed = record.get("embed") or {}
    if embed.get("$type") == "app.bsky.embed.record":
        uri = (embed.get("record") or {}).get("uri")
    elif embed.get("$type") == "app.bsky.embed.recordWithMedia":
        uri = ((embed.get("record") or {}).get("record") or {}).get("uri")
    else:
        return None
    return ("citation", uri) if isinstance(uri, str) and uri else None


class Retour(NamedTuple):
    """Résultat d'une demande de contexte : texte brut, ou motif d'absence. Jamais d'URI."""
    req: int
    texte: str | None
    motif: str | None


class LecteurContexte:
    """Lit le texte des posts référencés dans un thread de travail unique (daemon).

    Le thread principal n'attend jamais le réseau : il dépose une demande (req, uri) dans
    une file bornée (`demander`) et récupère les résultats (`retours`). Le plafond glissant
    sur 60 s est tenu ici : au-delà, le résultat porte le motif `plafond`, sans appel.
    `timeout` borne la connexion et chaque lecture, pas l'appel entier (la résolution DNS
    n'est pas bornée). Les erreurs sortent par motif, jamais par message : celui de
    requests contient l'URL, donc l'URI.
    """

    def __init__(self, max_par_minute: int, file_max: int = CONTEXTE_FILE_MAX,
                 timeout: float = CONTEXTE_TIMEOUT_S, clock=time.monotonic):
        self.max_par_minute = max_par_minute
        self.timeout = timeout
        self.clock = clock
        self.appels_total = 0
        self._fenetre: deque[float] = deque()
        self._demandes: queue.Queue = queue.Queue(maxsize=file_max)
        self._retours: queue.Queue = queue.Queue()        # une réponse par demande acceptée
        self._arret = threading.Event()
        self._fil = threading.Thread(target=self._boucle, name="contexte", daemon=True)
        self._fil.start()

    def demander(self, req: int, uri: str) -> bool:
        """Dépose une demande sans attendre. Faux si la file est pleine (rien n'est déposé)."""
        try:
            self._demandes.put_nowait((req, uri))
        except queue.Full:
            return False
        return True

    def retours(self) -> list[Retour]:
        """Résultats déjà rendus par le fil, sans attendre."""
        sortie: list[Retour] = []
        while True:
            try:
                sortie.append(self._retours.get_nowait())
            except queue.Empty:
                return sortie

    def arreter(self, delai: float) -> None:
        """Arrête le fil après la lecture en cours, sans attendre plus de `delai` s."""
        self._arret.set()
        self._fil.join(timeout=delai)

    def _boucle(self) -> None:
        while not self._arret.is_set():
            try:
                req, uri = self._demandes.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._arret.is_set():
                break
            try:
                texte, motif = self._lire(uri)
            except Exception:                    # le fil survit à toute erreur : motif générique
                texte, motif = None, "erreur"
            self._retours.put(Retour(req, texte, motif))

    def _autorise(self) -> bool:
        now = self.clock()
        while self._fenetre and now - self._fenetre[0] >= 60.0:
            self._fenetre.popleft()
        if len(self._fenetre) >= self.max_par_minute:
            return False
        self._fenetre.append(now)
        return True

    def _lire(self, uri: str) -> tuple[str | None, str | None]:
        """(texte brut, None), ou (None, motif) : plafond, reseau, http, format,
        introuvable (post supprimé ou non visible), vide (sans texte)."""
        if not self._autorise():
            return None, "plafond"
        import requests                          # import local : comme run_backfill
        self.appels_total += 1
        try:
            resp = requests.get(GETPOSTS_URL, params={"uris": [uri]},
                                headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
        except Exception:
            return None, "reseau"
        if resp.status_code != 200:
            return None, "http"
        try:
            posts = resp.json()["posts"]
            if not posts:
                return None, "introuvable"
            texte = (posts[0].get("record") or {}).get("text")
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            return None, "format"
        if not isinstance(texte, str) or not texte.strip():
            return None, "vide"
        return texte, None


@dataclass
class Attente:
    """Réponse qui échoue la garde sur son texte, en attente de la garde de son parent."""
    created_at: str
    texte: str                              # masqué, tel qu'il serait stocké
    minute: str
    time_us: int                            # événement Jetstream : borne le curseur d'écriture
    echeance: float                         # horloge : au-delà, rejet (contexte_absent_delai)


class Contexte:
    """Contexte du nouveau corpus, côté thread principal (seul écrivain SQLite).

    Aucune attente réseau ici : les demandes partent vers LecteurContexte, et les résultats
    sont consommés à chaque message et à chaque flush (`consommer`).

    - Post dont la garde passe : stocké aussitôt. Son texte de contexte est écrit par UPDATE
      sur sa ligne au flush suivant le résultat. Si la demande ne part pas (file pleine), le
      post est stocké sans contexte (contexte_absent_file_pleine).
    - Réponse qui échoue la garde : mise en attente (`attentes`, bornée) avec son parent. Au
      résultat du parent, elle est gardée si le parent passe la garde et est français, sinon
      rejetée (garde_par_parent_refusee). Sans résultat après `delai` s, rejetée
      (contexte_absent_delai).
    """

    def __init__(self, lecteur: LecteurContexte, filt: KeywordFilter,
                 delai: float = GARDE_DELAI_S, attente_max: int = GARDE_ATTENTE_MAX,
                 clock=time.monotonic):
        self.lecteur = lecteur
        self.filt = filt
        self.delai = delai
        self.attente_max = attente_max
        self.clock = clock
        self.en_vol: dict[int, str] = {}                 # demande sans résultat → minute
        self.attentes: dict[int, Attente] = {}           # demande du parent → réponse attendue
        self._prochain = 0

    @property
    def appels_total(self) -> int:
        return self.lecteur.appels_total

    def _demander(self, minute: str, uri: str) -> int | None:
        self._prochain += 1
        if not self.lecteur.demander(self._prochain, uri):
            return None
        self.en_vol[self._prochain] = minute
        return self._prochain

    def stocker_avec_contexte(self, store: Store, created_at: str, texte: str, minute: str,
                              ctype: str, uri: str) -> None:
        """Post gardé dont la réponse ou la citation est lue par getPosts (sans attendre)."""
        req = self._demander(minute, uri)
        if req is None:
            store.compte(minute, "contexte_absent_file_pleine")
            store.accept(created_at, texte, minute, ctype)
        else:
            store.accept(created_at, texte, minute, ctype, req=req)

    def attendre_parent(self, store: Store, created_at: str, texte: str, minute: str,
                        time_us: int, uri: str) -> None:
        """Réponse qui échoue la garde : attente du parent, bornée en mémoire et en délai."""
        if len(self.attentes) >= self.attente_max:
            _refuser(store, minute, "contexte_absent_file_pleine")
            return
        req = self._demander(minute, uri)
        if req is None:
            _refuser(store, minute, "contexte_absent_file_pleine")
            return
        self.attentes[req] = Attente(created_at, texte, minute, time_us,
                                     self.clock() + self.delai)

    def consommer(self, store: Store) -> None:
        """Applique les résultats rendus par le fil, puis expire les attentes échues."""
        for retour in self.lecteur.retours():
            minute = self.en_vol.pop(retour.req, None)
            if minute is None:
                continue                         # demande expirée : résultat ignoré
            attente = self.attentes.pop(retour.req, None)
            if attente is None:
                self._contexte_post(store, retour.req, minute, retour)
            else:
                self._garde_parent(store, attente, retour)
        self._expirer(store)

    def curseur_sur(self, curseur: int) -> int:
        """Curseur à écrire : jamais au-delà de l'événement le plus ancien encore en attente.

        Une réponse en attente n'est pas encore écrite : si le curseur la dépassait, un
        redémarrage ne la relirait jamais. Le curseur reste donc juste avant elle.
        """
        if not self.attentes:
            return curseur
        return min(curseur, min(a.time_us for a in self.attentes.values()) - 1)

    def _contexte_post(self, store: Store, req: int, minute: str, retour: Retour) -> None:
        masque = _contexte_utile(store, minute, retour, self.filt.noms)
        if masque is None:
            store.contextes.pop(req, None)       # rien à écrire : le post reste sans texte
        else:
            store.contexte_recu(req, masque)

    def _garde_parent(self, store: Store, attente: Attente, retour: Retour) -> None:
        masque = _contexte_utile(store, attente.minute, retour, self.filt.noms)
        if masque is None or self.filt.test(normalize(retour.texte)) is not None:
            _refuser(store, attente.minute, "garde_par_parent_refusee")
            return
        store.compte(attente.minute, "garde_par_parent")
        store.accept(attente.created_at, attente.texte, attente.minute, "reponse", masque)

    def _expirer(self, store: Store) -> None:
        now = self.clock()
        for req, attente in list(self.attentes.items()):
            if attente.echeance <= now:
                del self.attentes[req]
                self.en_vol.pop(req, None)
                _refuser(store, attente.minute, "contexte_absent_delai")

    def arreter(self, store: Store, delai: float | None = None) -> None:
        """Arrêt (SIGTERM) : applique les résultats déjà rendus, abandonne le reste, compté.

        Les réponses en attente et les demandes sans résultat sont abandonnées (motif et
        compteur `contexte_abandonne`). Elles ne sont pas relues au redémarrage : le curseur
        n'est donc pas retenu pour elles. Le fil de lecture est arrêté au plus `delai` s.
        """
        self.consommer(store)
        for req, attente in list(self.attentes.items()):
            del self.attentes[req]
            self.en_vol.pop(req, None)
            _refuser(store, attente.minute, "contexte_abandonne")
        for req, minute in list(self.en_vol.items()):
            del self.en_vol[req]
            store.contextes.pop(req, None)           # le post reste écrit, sans contexte
            store.compte(minute, "contexte_abandonne")
        self.lecteur.arreter(ARRET_DELAI_S if delai is None else delai)


def vidanger(store: Store, contexte: Contexte | None) -> None:
    """Consomme les résultats du contexte, puis écrit le lot avec le curseur borné."""
    if contexte is None:
        store.flush(store.cursor)
        return
    contexte.consommer(store)
    store.flush(contexte.curseur_sur(store.cursor))


def _contexte_utile(store: Store, minute: str, retour: Retour, noms: dict[str, str]) -> str | None:
    """Texte masqué du post référencé s'il est français ; sinon None (absence comptée)."""
    if retour.texte is None:
        store.compte(minute, f"contexte_absent_{retour.motif}")
        return None
    masque = masquer(" ".join(retour.texte.split()), noms)
    if not est_francais(masque):
        store.compte(minute, "contexte_absent_langue")
        return None
    store.compte(minute, "contexte_recupere")
    return masque


def _refuser(store: Store, minute: str, motif: str) -> None:
    """Rejet d'une réponse : motif dans ingest_rejects, compteur de même nom."""
    store.reject(minute, motif)
    store.compte(minute, motif)


def traiter_nouveau_corpus(store: Store, record: dict, created_at: str, text: str, minute: str,
                           time_us: int, reason: str | None,
                           contexte: Contexte | None, garde_parent: bool = True,
                           noms: dict[str, str] | None = None) -> None:
    """Décide d'un post du nouveau corpus. `reason` : motif de la garde sur le texte, None si gardé.

    Garde passée : le texte doit être français ; le contexte (réponse ou citation) est demandé
    sans attendre. Garde échouée : seule une réponse française est gardée, et seulement si son
    parent passe la garde : la décision se prend au résultat du parent (Contexte). Avec
    garde_parent=False, la réponse est jugée sur son seul texte, comme les autres posts.
    """
    texte = masquer(" ".join(text.split()), noms)    # M11 : URL et mentions masquées
    cible = cible_contexte(record) if contexte is not None else None
    if reason is None:
        if not est_francais(texte):
            store.reject(minute, "langue-texte")     # texte non français, langue déclarée ignorée
        elif cible is None:
            store.accept(created_at, texte, minute)
        else:
            contexte.stocker_avec_contexte(store, created_at, texte, minute, cible[0], cible[1])
        return
    if cible is None or cible[0] != "reponse" or not est_francais(texte) or not garde_parent:
        store.reject(minute, reason)
        return
    contexte.attendre_parent(store, created_at, texte, minute, time_us, cible[1])


def minute_of(created_at: str) -> str:
    return created_at[:16]  # "YYYY-MM-DDTHH:MM"


def event_minute(time_us: int, fallback: str) -> str:
    """Minute (UTC) de l'évènement Jetstream ; repli sur celle du post."""
    if time_us > 0:
        return datetime.fromtimestamp(time_us / 1e6, timezone.utc).strftime("%Y-%m-%dT%H:%M")
    return minute_of(fallback)


def parse_iso(ts: str) -> datetime | None:
    """Parse un horodatage ISO-8601 ('2026-…T…Z' ou avec offset) en datetime UTC."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def to_utc_iso(created_at: str, time_us: int) -> str:
    """Horodatage normalisé : ISO-8601 UTC systématique ('…T…mm.mmmZ').

    Chaque post arrive avec l'offset du client auteur (+02:00, Z, +08:00 …) —
    on stocke tout en UTC pour des comparaisons/tris/stats cohérents.
    """
    dt = parse_iso(created_at)
    if dt is None:
        dt = datetime.fromtimestamp(time_us / 1e6, timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def process_message(store: Store, msg: dict, filt: KeywordFilter, min_dt: datetime,
                    nouveau: bool = False, contexte: Contexte | None = None) -> int:
    """Traite un évènement ; renvoie le time_us pour le cursor. 0 si non-post.

    nouveau : nouveau corpus de développement. La langue déclarée est ignorée : seul le
    texte compte, il doit être français (langdetect), et il est stocké masqué ; le contexte d'une réponse ou citation est lu si
    `contexte` est fourni ; une réponse qui échoue la garde est sauvée si son parent la
    passe (traiter_nouveau_corpus). Sans `nouveau`, le corpus existant est inchangé.
    """
    commit = msg.get("commit") or {}
    if commit and commit.get("operation") != "create":
        store.ignored_ops += 1                    # update/delete : une édition n'est pas un nouveau post
        return int(msg.get("time_us", 0))
    records = commit.get("records")
    if records is None and commit.get("record") is not None:
        records = [commit.get("record")]          # forme réelle observée (cf. docs/exemples)
    if not records:
        return int(msg.get("time_us", 0))
    for record in records:
        text = record.get("text")
        if not text:
            continue                              # posts vides : rien à exploiter
        time_us = int(msg.get("time_us") or 0)
        created_at = to_utc_iso(record.get("createdAt") or "", time_us)
        dt = parse_iso(created_at)
        minute = event_minute(time_us, created_at)   # débit par minute d'arrivée
        if dt is not None and dt < min_dt:
            store.reject(minute, "hors-periode")
            continue                              # édit récent d'un vieux post → rejeté
        langs = set(record.get("langs") or [])
        if not nouveau and langs and "fr" not in langs:     # nouveau : la langue se lit dans le texte
            store.reject(minute, "langue")
            continue
        reason = filt.test(normalize(text))
        if nouveau and reason is not None and nom_public_marque(text, filt.noms):
            reason = None                            # nom public dans une mention ou un hashtag
        if nouveau:
            traiter_nouveau_corpus(store, record, created_at, text, minute, time_us, reason,
                                   contexte, garde_parent=filt.gardes_secondaires, noms=filt.noms)
            continue
        if reason:
            store.reject(minute, reason)
            continue
        store.accept(created_at, " ".join(text.split()), minute)
    return int(msg.get("time_us", 0))


def handle_raw(store: Store, raw, filt: KeywordFilter, min_dt: datetime,
               errors: dict[str, int], nouveau: bool = False,
               contexte: Contexte | None = None) -> int:
    """Traite un message brut en isolant ses erreurs ; renvoie le time_us (0 si inconnu).

    Un message illisible est compté par type d'exception (jamais son contenu :
    ni texte, ni identifiant dans les traces) et n'interrompt pas la connexion.
    """
    msg = None
    try:
        msg = json.loads(raw)
        return process_message(store, msg, filt, min_dt, nouveau, contexte)
    except Exception as e:
        name = type(e).__name__
        errors[name] = errors.get(name, 0) + 1
        if errors[name] == 1:                   # 1re occurrence seulement ; cumul au battement
            print(f"Message ignore ({name})", flush=True)
        try:
            return int(msg.get("time_us") or 0)   # le cursor avance malgré l'erreur
        except Exception:
            return 0


def beat(path: str | None) -> None:
    """Met à jour le fichier de battement (healthcheck Docker). Sans effet si path vide."""
    if not path:
        return
    try:
        with open(path, "w") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass                                    # le battement ne doit jamais tuer la collecte


class StreamIdle(Exception):
    """Aucun message reçu depuis trop longtemps : flux figé, on se reconnecte."""


def run_stream(store: Store, filt: KeywordFilter, min_dt: datetime, duration: float,
               batch_size: int, batch_interval: float, idle_timeout: float = 60.0,
               heartbeat: str | None = None, nouveau: bool = False,
               contexte: Contexte | None = None) -> None:
    """Boucle principale : connexion persistante, reconnexion backoff, cursor.

    Battement : le fichier `heartbeat` est mis à jour toutes les 10 s tant que des
    messages arrivent ET que les écritures SQLite réussissent. Un fichier périmé
    signale donc une collecte à l'arrêt (réseau coupé, boucle bloquée, base en erreur).

    Chien de garde : le firehose envoie des dizaines de messages par seconde ; sans
    aucun message pendant idle_timeout s, la connexion est considérée figée.
    """
    t_start = time.monotonic()                  # repère absolu pour --duration
    last_batch = t_start
    last_status = t_start
    last_beat = 0.0
    next_attempt = t_start
    attempt = 0
    total_events = 0
    errors: dict[str, int] = {}                 # messages ignorés, par type d'exception
    global STOP
    while not STOP and (duration <= 0 or time.monotonic() - t_start < duration):
        if time.monotonic() < next_attempt:
            time.sleep(0.5)
            continue
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        url += f"?wantedCollections={COLLECTION}"
        if store.cursor:
            url += f"&cursor={store.cursor}"
        ws = None
        try:
            ws = websocket.create_connection(url, timeout=10)
            ws.sock.settimeout(1.0)
            attempt = 0
            last_msg = time.monotonic()
            print(f"Connecte : {url.split('?')[0]} cursor={store.cursor}", flush=True)
            while not STOP and (duration <= 0 or time.monotonic() - t_start < duration):
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    if time.monotonic() - last_msg > idle_timeout:
                        raise StreamIdle(f"aucun message depuis {idle_timeout:.0f}s")
                except Exception:
                    raise                       # → reconnexion (backoff)
                else:
                    last_msg = time.monotonic()
                    if raw:
                        total_events += 1
                        t_us = handle_raw(store, raw, filt, min_dt, errors, nouveau, contexte)
                        if t_us > store.cursor:
                            store.cursor = t_us
                now = time.monotonic()
                if contexte is not None:
                    contexte.consommer(store)        # résultats et délais, sans attente réseau
                if len(store.pending) >= batch_size or now - last_batch >= batch_interval:
                    vidanger(store, contexte)
                    last_batch = now
                    if now - last_msg < idle_timeout and now - last_beat >= 10:
                        beat(heartbeat)
                        last_beat = now
                if now - last_status >= 60:     # battement de suivi (aucun contenu)
                    extra = ""
                    if contexte is not None:    # compteurs seuls, jamais d'URI ni de texte
                        extra = (f" appels_contexte={contexte.appels_total} "
                                 f"en_vol={len(contexte.en_vol)} "
                                 f"attentes={len(contexte.attentes)} {store.cumul}")
                    print(f"[{time.strftime('%H:%M:%S')}] events_total={total_events} "
                          f"en_attente={len(store.pending)} cursor={store.cursor} "
                          f"ops_ignorees={store.ignored_ops} erreurs={errors or 0}{extra}",
                          flush=True)
                    last_status = now
            ws.close()
            break                               # durée terminée
        except Exception as e:
            try:
                if ws is not None:
                    ws.close()                  # libère le socket avant de se reconnecter
            except Exception:
                pass
            attempt += 1
            wait = min(60, 2 ** min(attempt, 6))
            next_attempt = time.monotonic() + wait
            print(f"Deconnexion ({type(e).__name__}) : reconnexion dans {wait}s "
                  f"(cursor={store.cursor})", flush=True)
    if contexte is not None:
        contexte.arreter(store)                      # abandons comptés, fil arrêté (borné)
    vidanger(store, contexte)
    store.close()
    print(f"Arret propre : {total_events} evenements traites au total.", flush=True)


def run_backfill(store: Store, keywords: list[str], max_posts: int,
                 min_interval: float, min_dt: datetime) -> None:
    """Complément AppView (recherche REST) : marge = intervalle min entre requêtes."""
    import random
    import requests
    fetched = 0
    page = 0
    while fetched < max_posts and not STOP:
        kw = keywords[page % len(keywords)]
        url = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
        try:
            resp = requests.get(url, params={"q": kw, "limit": min(100, max_posts - fetched)},
                                headers={"User-Agent": "sae-data-poc/0.1 (education)"},
                                timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("x-ratelimit-reset", 60)) or 60
                print(f"429 rate limit : pause {wait}s (marge respectee)", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            for p in resp.json().get("posts", []):
                record = p.get("record", {})
                text = record.get("text")
                if not text:
                    continue
                created_at = to_utc_iso(record.get("createdAt") or
                                        p.get("indexedAt", ""), 0)
                dt = parse_iso(created_at)
                if dt is None or dt < min_dt:
                    continue
                store.accept(created_at, " ".join(text.split()), minute_of(created_at))
                fetched += 1
            page += 1
            time.sleep(min_interval + random.uniform(0, 1.5))   # marge + jitter
        except Exception as e:
            wait = min(120, 10 * 2 ** page)
            print(f"Backfill erreur ({type(e).__name__}) : pause {wait}s", flush=True)
            time.sleep(wait)
            page += 1
    store.flush(store.cursor)
    store.close()
    print(f"Backfill termine : {fetched} posts demandes (doubles possibles ignores par dedup).",
          flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingestion Bluesky -> SQLite")
    ap.add_argument("--db", default="data/bluesky_posts.db")
    ap.add_argument("--duration", type=float, default=0, help="s (0 = continu)")
    ap.add_argument("--keywords", default=None, help="fichier, 1 mot par ligne")
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--batch-interval", type=float, default=5.0, help="flush tous les N s")
    ap.add_argument("--idle-timeout", type=float, default=60.0,
                    help="reconnexion si aucun message depuis N s (flux figé)")
    ap.add_argument("--heartbeat", default=None,
                    help="fichier de battement mis à jour par la boucle (healthcheck)")
    ap.add_argument("--min-date", default="2025-01-01",
                    help="ne garder que les posts crées après cette date (ISO, défaut 2025-01-01)")
    ap.add_argument("--backfill", type=int, default=0,
                    help="compléter via AppView (N posts) puis terminer")
    ap.add_argument("--backfill-interval", type=float, default=3.0,
                    help="marge entre requêtes AppView (s)")
    ap.add_argument("--nouveau-corpus", action="store_true",
                    help="nouveau corpus de développement : texte vérifié en français, masqué, "
                         "avec contexte des réponses et citations. Refuse bluesky_posts.db")
    ap.add_argument("--contexte-max-par-minute", type=int,
                    default=os.environ.get("CONTEXTE_MAX_PAR_MINUTE",
                                           str(CONTEXTE_MAX_PAR_MINUTE_DEFAUT)),
                    help="plafond d'appels getPosts par minute, nouveau corpus "
                         "[CONTEXTE_MAX_PAR_MINUTE, défaut 60]")
    args = ap.parse_args()

    if args.nouveau_corpus and Path(args.db).name == "bluesky_posts.db":
        print("--nouveau-corpus refuse bluesky_posts.db : donner une autre base (--db)",
              file=sys.stderr, flush=True)
        return 2

    signal.signal(signal.SIGINT, set_stop)
    signal.signal(signal.SIGTERM, set_stop)

    query_kws, filt = load_keywords(args.keywords)
    if args.nouveau_corpus:
        filt.gardes_secondaires = False             # nouveau corpus seul : producteur Kafka inchangé
    min_dt = parse_iso(args.min_date) or datetime(2025, 1, 1, tzinfo=timezone.utc)
    store = Store(args.db)
    print(f"DB={args.db} min_date={args.min_date} "
          f"cursor_depart={store.cursor} "
          f"mode={'nouveau-corpus' if args.nouveau_corpus else 'corpus-existant'}", flush=True)
    if args.backfill:
        run_backfill(store, query_kws, args.backfill, args.backfill_interval, min_dt)
    else:
        contexte = (Contexte(LecteurContexte(args.contexte_max_par_minute), filt)
                    if args.nouveau_corpus else None)
        run_stream(store, filt, min_dt, args.duration, args.batch_size,
                   args.batch_interval, args.idle_timeout, args.heartbeat,
                   nouveau=args.nouveau_corpus, contexte=contexte)
    return 0


if __name__ == "__main__":
    sys.exit(main())