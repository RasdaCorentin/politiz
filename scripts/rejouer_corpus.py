#!/usr/bin/env python3
"""Rejeu d'un corpus SQLite par le code du job Spark (job Spark et tables ClickHouse : docs/technique/contrats-poc.md).

Lit les posts de la table `posts` dont `created_at` tombe dans [--depuis, --avant[, applique les
étapes 1 et 2 du job (`pii.projeter`, `pii.nettoyer`), dédoublonne par hash, puis appelle
`job.traiter_micro_lot` par lots de posts. Sans `--importer`, affiche des comptes. Avec
`--importer`, insère les agrégats dans `sae.*` : toutes les tables du job, ou celles de `--tables`.

Ne journalise, n'affiche et n'écrit aucun texte de post ni aucun identifiant : seulement des comptes.
Documentation : docs/technique/rejeu-corpus.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SRC_STREAMING = RACINE / "src" / "streaming"
sys.path.insert(0, str(SRC_STREAMING))
os.environ.setdefault("LEXIQUE_DIR", str(RACINE / "ressources" / "lexique"))

from pyspark.sql import DataFrame, SparkSession  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql import Window  # noqa: E402

import job  # noqa: E402
import modeles as mdl  # noqa: E402
import pii  # noqa: E402
import scoring  # noqa: E402

EPOQUE = datetime(1970, 1, 1, tzinfo=timezone.utc)
FENETRE = timedelta(minutes=5)
WATERMARK_US = 10 * 60 * 1_000_000        # filigrane du job (étape de dédoublonnage)
FORMAT_CREATED = "%Y-%m-%dT%H:%M:%S.%fZ"  # format de `created_at` dans la base (millisecondes)
TAILLE_LOT = 4000                          # posts par micro-lot du rejeu
TACHES = 2                                 # tâches Spark simultanées, 2 threads torch chacune

# Clés (grain) et colonnes de chaque table ClickHouse du contrat.
CLES = {
    "cibles_fenetre": ("fenetre_debut", "entite", "stance"),
    "posts_fenetre": ("fenetre_debut", "sentiment", "emotion"),
    "themes_fenetre": ("fenetre_debut", "theme"),
    "pipeline_fenetre": ("fenetre_debut",),
    "croisements_fenetre": ("fenetre_debut", "entite", "stance", "sentiment", "emotion", "theme",
                            "scoreur"),
    "adjectifs_fenetre": ("fenetre_debut", "entite", "stance", "adjectif", "scoreur"),
}
# Ordre d'insertion : `pipeline_fenetre` d'abord, car le garde-fou lit les tables dans cet ordre
# (un import partiel reste alors détectable).
ORDRE_INSERTION = ("pipeline_fenetre", "cibles_fenetre", "posts_fenetre", "themes_fenetre",
                   "croisements_fenetre", "adjectifs_fenetre")
COLONNES_INSERTION = {
    "cibles_fenetre": ("fenetre_debut", "entite", "stance", "nb_posts"),
    "posts_fenetre": ("fenetre_debut", "sentiment", "emotion", "nb_posts"),
    "themes_fenetre": ("fenetre_debut", "theme", "nb_posts"),
    "pipeline_fenetre": ("fenetre_debut", "derniere_maj", "nb_posts", "somme_latence_ms"),
    "croisements_fenetre": ("fenetre_debut", "entite", "stance", "sentiment", "emotion", "theme",
                            "scoreur", "nb_posts"),
    "adjectifs_fenetre": ("fenetre_debut", "entite", "stance", "adjectif", "scoreur", "nb_posts"),
}


class DejaImporte(RuntimeError):
    """Une table à importer a déjà des lignes dans la période : refus d'importer."""


# --- temps et lecture -------------------------------------------------------------
def formater_borne(texte: str) -> str:
    """Borne ISO 8601 UTC (ex. 2026-10-12T00:00:00Z) -> format de `created_at` (ms, `Z`)."""
    dt = datetime.fromisoformat(texte.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def temps_us(created_at: str) -> int:
    """`created_at` (UTC, millisecondes) -> microsecondes depuis l'époque, comme `time_us`."""
    dt = datetime.strptime(created_at, FORMAT_CREATED).replace(tzinfo=timezone.utc)
    return (dt - EPOQUE) // timedelta(microseconds=1)


def lire_posts(db: Path, depuis: str, avant: str) -> list[tuple[str, str]]:
    """(created_at, texte) des posts dans [depuis, avant[, par ordre d'horodatage. Base ouverte en lecture seule.

    Les bornes sont des chaînes au même format que `created_at` : la comparaison de chaînes
    suit alors l'ordre chronologique."""
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT created_at, text FROM posts WHERE created_at >= ? AND created_at < ? "
            "ORDER BY created_at, id", (depuis, avant)).fetchall()
    finally:
        con.close()


def evenement(created_at: str, texte: str) -> str:
    """Événement JSON au format Jetstream, réduit aux champs que lit `pii.projeter`.

    `langs` vaut `fr` : la base ne garde pas la langue ; le collecteur ne retient que le français
    (src/ingestion/producer.py, filtre `langs`). Hypothèse déclarée dans la documentation."""
    return json.dumps({
        "time_us": temps_us(created_at),
        "commit": {"operation": "create", "collection": "app.bsky.feed.post",
                   "record": {"text": texte, "langs": ["fr"]}},
    }, ensure_ascii=False)


# --- étapes 1 à 3 du job, en lot -------------------------------------------------------
def preparer(spark: SparkSession, posts: list[tuple[str, str]]) -> tuple[DataFrame, dict]:
    """Projection, nettoyage (`pii`) et dédoublonnage par hash. Renvoie (`time_us`, `texte`) et des comptes.

    Le dédoublonnage est celui du job en lot : `dropDuplicatesWithinWatermark` n'existe qu'en
    streaming. Ici, le premier post (par `time_us`) de chaque hash est gardé, sur toute la période."""
    brut = spark.createDataFrame([(evenement(c, t),) for c, t in posts], "value string")
    nettoye = pii.nettoyer(pii.projeter(brut)).select("time_us", "texte", "hash").cache()
    nb_propres = nettoye.count()
    par_hash = Window.partitionBy("hash").orderBy("time_us")
    doublons_espaces = (nettoye.withColumn("precedent", F.lag("time_us").over(par_hash))
                        .where(F.col("precedent").isNotNull()
                               & (F.col("time_us") - F.col("precedent") > WATERMARK_US))
                        .count())
    dedup = (nettoye.withColumn("rang_hash", F.row_number().over(par_hash))
             .where(F.col("rang_hash") == 1).select("time_us", "texte"))
    stats = {"lus": len(posts), "propres": nb_propres, "doublons_espaces": doublons_espaces}
    return dedup, stats


# --- agrégation par lots -----------------------------------------------------------
def _cle(valeur):
    return "" if valeur is None else valeur


def agreger(spark: SparkSession, dedup: DataFrame, modeles: mdl.Modeles | None, avant_us: int,
            taille: int = TAILLE_LOT, progression=None, taches: int = TACHES) -> dict[str, Counter]:
    """Appelle `job.traiter_micro_lot` par tranches de `taille` posts (ordre de `time_us`) et somme les agrégats.

    Les tables se somment : sommer les lots donne le même résultat qu'un seul appel. Chaque tranche
    est répartie en `taches` partitions, scorées en parallèle. Renvoie, par table, un compteur
    {clé: nb_posts}. La clé de `fenetre_debut` est un entier (secondes UTC)."""
    ordonne = dedup.withColumn("rang", F.row_number().over(Window.orderBy("time_us"))).cache()
    n = ordonne.count()
    acc: dict[str, Counter] = {t: Counter() for t in CLES}
    nb_lots = -(-n // taille)
    for k in range(nb_lots):
        tranche = ordonne.where((F.col("rang") > k * taille) & (F.col("rang") <= (k + 1) * taille))
        debut = time.monotonic()
        lot = job.traiter_micro_lot(tranche.select("time_us", "texte").repartition(taches), spark, 5,
                                    maintenant_us=avant_us, modeles=modeles)
        posts_lot = 0
        try:
            for table, agg in lot.agregats().items():
                cles = CLES[table]
                vue = agg.withColumn("fenetre_debut", F.unix_timestamp("fenetre_debut"))
                for r in vue.select(*cles, "nb_posts").collect():
                    cle = tuple(_cle(r[c]) for c in cles)
                    acc[table][cle] += r["nb_posts"]
                    if table == "pipeline_fenetre":
                        posts_lot += r["nb_posts"]
        finally:
            lot.liberer()
        if progression is not None:
            progression(k + 1, nb_lots, posts_lot, time.monotonic() - debut)
    ordonne.unpersist()
    return acc


# --- vérifications et import ----------------------------------------------------------
def sommes(acc: dict[str, Counter]) -> dict[str, int]:
    return {t: sum(c.values()) for t, c in acc.items()}


def verifier_absence(client, depuis: datetime, avant: datetime,
                     tables: tuple[str, ...] = ORDRE_INSERTION) -> None:
    """Refuse si l'une des `tables` a déjà une ligne dans [depuis, avant[ (les tables se somment)."""
    for table in tables:
        n = client.query(
            f"SELECT count() FROM sae.{table} "
            "WHERE fenetre_debut >= {d:DateTime('UTC')} AND fenetre_debut < {a:DateTime('UTC')}",
            parameters={"d": depuis, "a": avant}).result_rows[0][0]
        if n:
            raise DejaImporte(f"{n} ligne(s) de sae.{table} dans la période : import refusé")


def lignes_insertion(acc: dict[str, Counter],
                     tables: tuple[str, ...] = ORDRE_INSERTION) -> dict[str, list[list]]:
    """Lignes à insérer par table. Latence nulle (rejeu) ; `derniere_maj` = fin de la fenêtre de 5 min."""
    sortie: dict[str, list[list]] = {}
    for table in tables:
        lignes = []
        for cle, nb in acc[table].items():
            debut = datetime.fromtimestamp(cle[0], timezone.utc)
            if table == "pipeline_fenetre":
                lignes.append([debut, debut + FENETRE, nb, 0])
            else:
                lignes.append([debut, *cle[1:], nb])
        sortie[table] = lignes
    return sortie


def importer(client, acc: dict[str, Counter], depuis: datetime, avant: datetime,
             tables: tuple[str, ...] = ORDRE_INSERTION) -> None:
    """Insère les agrégats des `tables` dans `sae.*`, puis vérifie que les sommes lues égalent celles calculées."""
    verifier_absence(client, depuis, avant, tables)
    lignes = lignes_insertion(acc, tables)
    for table in tables:
        client.insert(f"sae.{table}", lignes[table], column_names=list(COLONNES_INSERTION[table]))
    attendu = sommes(acc)
    for table in tables:
        lu = client.query(
            f"SELECT sum(nb_posts) FROM sae.{table} "
            "WHERE fenetre_debut >= {d:DateTime('UTC')} AND fenetre_debut < {a:DateTime('UTC')}",
            parameters={"d": depuis, "a": avant}).result_rows[0][0]
        if int(lu or 0) != attendu[table]:
            raise RuntimeError(f"somme différente dans sae.{table} : {lu} lu, {attendu[table]} calculé")


# --- agrégats sur disque (aucun texte) -------------------------------------------------
def ecrire_agregats(dossier: Path, acc: dict[str, Counter], stats: dict, duree_s: float) -> None:
    """Écrit `agregats.json` : comptes par clé et comptes de contrôle. Aucun texte ni identifiant
    (un adjectif vient du lexique fermé, jamais du texte)."""
    dossier.mkdir(parents=True, exist_ok=True)
    charge = {
        "stats": stats,
        "duree_s": round(duree_s, 1),
        "tables": {t: [[*cle, nb] for cle, nb in acc[t].items()] for t in CLES if t in acc},
    }
    (dossier / "agregats.json").write_text(json.dumps(charge, ensure_ascii=False), encoding="utf-8")


def lire_agregats(dossier: Path) -> tuple[dict[str, Counter], dict]:
    """Agrégats d'un `agregats.json`. Une table absente du fichier (rejeu plus ancien) est absente du résultat."""
    charge = json.loads((dossier / "agregats.json").read_text(encoding="utf-8"))
    acc: dict[str, Counter] = {}
    for table in CLES:
        if table not in charge["tables"]:
            continue
        compteur: Counter = Counter()
        for ligne in charge["tables"][table]:
            compteur[tuple(ligne[:-1])] += ligne[-1]
        acc[table] = compteur
    return acc, charge["stats"]


# --- Spark et environnement -------------------------------------------------------------
def creer_session(taches: int = TACHES) -> SparkSession:
    os.environ["PYTHONPATH"] = str(SRC_STREAMING) + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable
    spark = (SparkSession.builder.master(f"local[{2 * taches}]").appName("rejeu-corpus")
             .config("spark.task.cpus", "2")  # `taches` tâches simultanées x 2 threads torch (scoreur à modèles)
             .config("spark.ui.enabled", "false")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", "4")
             .config("spark.sql.execution.arrow.maxRecordsPerBatch", "2000")
             .config("spark.driver.bindAddress", "127.0.0.1")
             .config("spark.driver.host", "127.0.0.1")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    for module in ("pii.py", "scoring.py", "modeles.py"):
        spark.sparkContext.addPyFile(str(SRC_STREAMING / module))
    return spark


def lire_variable(chemin: Path, nom: str) -> str:
    """Valeur d'une variable du fichier `.env`. Le message d'erreur ne contient jamais la valeur."""
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        cle, sep, valeur = ligne.partition("=")
        if sep and cle.strip() == nom:
            return valeur.strip().strip("'\"")
    raise SystemExit(f"variable {nom} absente de {chemin}")


def connecter(args):
    import clickhouse_connect

    mot_de_passe = lire_variable(Path(args.env), "CLICKHOUSE_PIPELINE_PASSWORD")
    return clickhouse_connect.get_client(host=args.ch_host, port=args.ch_port, username="pipeline",
                                         password=mot_de_passe, database="sae")


def afficher_comptes(stats: dict, acc: dict[str, Counter]) -> None:
    sommes_tables = sommes(acc)
    print(f"posts lus (période) : {stats['lus']}")
    print(f"après nettoyage (fr, texte non vide) : {stats['propres']}")
    print(f"scorés (après dédoublonnage) : {sommes_tables['pipeline_fenetre']}")
    print(f"doublons espacés de plus de 10 min, retirés en lot (approximation) : "
          f"{stats['doublons_espaces']}")
    print(f"gardés par le filtre fin : {sommes_tables['posts_fenetre']}")
    for table in ORDRE_INSERTION:
        if table in acc:
            print(f"lignes {table} : {len(acc[table])}")
    print("sentiment :", dict(_repartir(acc["posts_fenetre"], 1)))
    print("émotion :", dict(_repartir(acc["posts_fenetre"], 2)))
    print("stance (occurrences cibles) :", dict(_repartir(acc["cibles_fenetre"], 2)))
    print("scoreur (occurrences croisées) :", dict(_repartir(acc["croisements_fenetre"], 6)))
    if "adjectifs_fenetre" in acc:
        print("stance (occurrences adjectifs) :", dict(_repartir(acc["adjectifs_fenetre"], 2)))


def _repartir(compteur: Counter, position: int) -> Counter:
    sortie: Counter = Counter()
    for cle, nb in compteur.items():
        sortie[cle[position]] += nb
    return sortie


def afficher_progression(k: int, n: int, nb_posts: int, duree: float) -> None:
    print(f"lot {k}/{n} : {nb_posts} posts, {nb_posts / max(duree, 1e-9):.1f} posts/s", flush=True)


def lire_tables(texte: str) -> tuple[str, ...]:
    """`--tables` : noms séparés par des virgules, rendus dans l'ordre d'insertion."""
    noms = {t.strip() for t in texte.split(",") if t.strip()}
    inconnues = noms - set(ORDRE_INSERTION)
    if inconnues or not noms:
        raise argparse.ArgumentTypeError(f"tables inconnues : {', '.join(sorted(inconnues)) or 'aucune'}")
    return tuple(t for t in ORDRE_INSERTION if t in noms)


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Rejeu d'un corpus SQLite par le job Spark.")
    p.add_argument("--db", type=Path, help="base SQLite source (absente avec --depuis-agregats)")
    p.add_argument("--agregats-sortie", type=Path,
                   help="dossier où écrire agregats.json (comptes seuls, aucun texte)")
    p.add_argument("--depuis-agregats", type=Path,
                   help="dossier d'un agregats.json à importer, sans rescorer")
    p.add_argument("--depuis", required=True, help="borne incluse, ex. 2026-10-12T00:00:00Z")
    p.add_argument("--avant", required=True, help="borne exclue, ex. 2026-10-19T16:25:00Z")
    p.add_argument("--run-stance", help="dossier du run de stance (vide : règles)")
    p.add_argument("--run-emotion", help="dossier du run d'émotion (vide : règles)")
    p.add_argument("--importer", action="store_true", help="insérer dans sae.* (refus si déjà importé)")
    p.add_argument("--tables", type=lire_tables, default=ORDRE_INSERTION,
                   help="tables à importer, séparées par des virgules (défaut : toutes) ; "
                        "le garde-fou ne lit que celles-ci")
    p.add_argument("--taches", type=int, default=TACHES,
                   help=f"tâches Spark simultanées, 2 cœurs chacune (défaut : {TACHES})")
    p.add_argument("--env", default=str(RACINE / "infra" / ".env"),
                   help="fichier .env qui contient CLICKHOUSE_PIPELINE_PASSWORD")
    p.add_argument("--ch-host", default="127.0.0.1")
    p.add_argument("--ch-port", type=int, default=18123)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construire_parseur().parse_args(argv)
    if args.depuis_agregats is None and (args.db is None or not args.db.is_file()):
        print("base SQLite introuvable", file=sys.stderr)
        return 1
    depuis_txt, avant_txt = formater_borne(args.depuis), formater_borne(args.avant)
    depuis_dt = datetime.fromisoformat(args.depuis.replace("Z", "+00:00"))
    avant_dt = datetime.fromisoformat(args.avant.replace("Z", "+00:00"))
    avant_us = temps_us(avant_txt)
    client = connecter(args) if args.importer else None
    if client is not None:
        verifier_absence(client, depuis_dt, avant_dt, args.tables)  # avant le calcul : échec rapide
    if args.depuis_agregats is not None:
        acc, stats = lire_agregats(args.depuis_agregats)
        manquantes = [t for t in args.tables if t not in acc]
        if client is not None and manquantes:
            print(f"tables absentes des agrégats : {', '.join(manquantes)}", file=sys.stderr)
            return 1
        afficher_comptes(stats, acc)
        if client is not None:
            importer(client, acc, depuis_dt, avant_dt, args.tables)
            print("import vérifié : sommes lues = sommes calculées")
        return 0
    modeles = mdl.Modeles(stance=args.run_stance, emotion=args.run_emotion)
    try:
        modeles.verifier()
    except mdl.ModeleError as e:
        print(e, file=sys.stderr)
        return 2
    posts = lire_posts(args.db, depuis_txt, avant_txt)
    print(f"scoreur : {scoring.libelle_scoreur(modeles)}")
    debut = time.monotonic()
    spark = creer_session(args.taches)
    try:
        dedup, stats = preparer(spark, posts)
        del posts
        acc = agreger(spark, dedup, modeles, avant_us, progression=afficher_progression,
                      taches=args.taches)
    except Exception as e:  # le type seul : un message Spark peut contenir des données
        print(f"échec du rejeu : {type(e).__name__}", file=sys.stderr)
        return 1
    finally:
        spark.stop()
    duree = time.monotonic() - debut
    print(f"durée du calcul : {duree:.0f} s")
    afficher_comptes(stats, acc)
    if args.agregats_sortie is not None:
        ecrire_agregats(args.agregats_sortie, acc, stats, duree)
        print("agrégats écrits")
    if client is not None:
        importer(client, acc, depuis_dt, avant_dt, args.tables)
        print("import vérifié : sommes lues = sommes calculées")
    return 0


if __name__ == "__main__":
    sys.exit(main())
