"""Job Spark Structured Streaming : Kafka -> nettoyage -> scoring -> MinIO / ClickHouse.

Contrat : docs/technique/contrats-poc.md (job Spark, stockages, variables, données). Lancement :
    spark-submit --master spark://spark-master:7077 /opt/streaming/job.py

Trois parties :
  (a) `construire_flux`  : lecture Kafka, projection, nettoyage, dédoublonnage (état streaming) ;
  (b) `traiter_micro_lot` : DataFrame statique -> lignes froides et agrégats (testable) ;
  (c) `ecrire_micro_lot` : `foreachBatch`, MinIO puis ClickHouse.
Le code n'écrit dans les journaux que des compteurs.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass

import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modeles as mdl  # noqa: E402
import pii  # noqa: E402
import scoring  # noqa: E402

log = logging.getLogger("streaming")

TABLES_CLICKHOUSE = ("cibles_fenetre", "posts_fenetre", "themes_fenetre", "pipeline_fenetre",
                     "croisements_fenetre", "adjectifs_fenetre")


@dataclass(frozen=True)
class Config:
    kafka_bootstrap: str = "kafka:9092"
    kafka_topic: str = "raw-posts"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    bucket_scores: str = "scores"
    bucket_checkpoints: str = "checkpoints"
    clickhouse_host: str = "clickhouse"
    clickhouse_port: str = "8123"
    clickhouse_user: str = "pipeline"
    clickhouse_password: str = ""
    clickhouse_db: str = "sae"
    fenetre_minutes: int = 5
    trigger_seconds: int = 30
    watermark_minutes: int = 10

    @staticmethod
    def depuis_env(env=os.environ) -> "Config":
        g = env.get
        return Config(
            kafka_bootstrap=g("KAFKA_BOOTSTRAP", "kafka:9092"),
            kafka_topic=g("KAFKA_TOPIC", "raw-posts"),
            s3_endpoint=g("S3_ENDPOINT", "http://minio:9000"),
            s3_access_key=g("S3_ACCESS_KEY", ""),
            s3_secret_key=g("S3_SECRET_KEY", ""),
            bucket_scores=g("S3_BUCKET_SCORES", "scores"),
            bucket_checkpoints=g("S3_BUCKET_CHECKPOINTS", "checkpoints"),
            clickhouse_host=g("CLICKHOUSE_HOST", "clickhouse"),
            clickhouse_port=g("CLICKHOUSE_PORT", "8123"),
            clickhouse_user=g("CLICKHOUSE_USER", "pipeline"),
            clickhouse_password=g("CLICKHOUSE_PASSWORD", ""),
            clickhouse_db=g("CLICKHOUSE_DB", "sae"),
            fenetre_minutes=int(g("FENETRE_MINUTES", "5")),
            trigger_seconds=int(g("TRIGGER_SECONDS", "30")),
            watermark_minutes=int(g("WATERMARK_MINUTES", "10")),
        )


# --- (a) flux ---------------------------------------------------------------------
def dedoublonner_flux(df: DataFrame, watermark_minutes: int) -> DataFrame:
    """Un texte nettoyé identique dans le filigrane compte une fois (état dans le checkpoint)."""
    return (df.withWatermark("event_time", f"{watermark_minutes} minutes")
            .dropDuplicatesWithinWatermark(["hash"])
            .select("time_us", "texte"))


def preparer_flux(brut: DataFrame, watermark_minutes: int) -> DataFrame:
    """Étapes 1 à 3 du job (liste blanche, nettoyage, dédoublonnage) sur un DataFrame ayant une colonne `value` (JSON)."""
    return dedoublonner_flux(pii.nettoyer(pii.projeter(brut)), watermark_minutes)


def construire_flux(spark: SparkSession, cfg: Config) -> DataFrame:
    brut = (spark.readStream.format("kafka")
            .option("kafka.bootstrap.servers", cfg.kafka_bootstrap)
            .option("subscribe", cfg.kafka_topic)
            # `earliest` ne vaut que pour un checkpoint neuf : après un arrêt de plus d'un jour,
            # Kafka (rétention 1 h) ne garde que des messages postérieurs au dernier lot validé.
            .option("startingOffsets", "earliest")
            .option("maxOffsetsPerTrigger", 20000)
            .option("failOnDataLoss", "false")
            .option("minPartitions", 4)
            .load())
    return preparer_flux(brut.select("value"), cfg.watermark_minutes)


# --- (b) micro-lot ----------------------------------------------------------------
SCHEMA_SCORE = T.StructType([
    T.StructField("cibles", T.ArrayType(T.StructType([
        T.StructField("entite", T.StringType()),
        T.StructField("stance", T.StringType()),
        T.StructField("confiance", T.StringType()),
    ]))),
    T.StructField("sentiment", T.StringType()),
    T.StructField("emotion", T.StringType()),
    T.StructField("themes", T.ArrayType(T.StringType())),
    T.StructField("adjectifs", T.ArrayType(T.StringType())),  # lexique fermé, une fois par post
    T.StructField("retenu", T.BooleanType()),  # filtre fin, calculé par le lexique seul
])


def creer_score_udf(modeles: mdl.Modeles | None):
    """`pandas_udf` du scoreur. Les dossiers des runs sont fermés dans la fonction : chaque executor
    charge ses modèles à partir d'eux, sans variable d'environnement côté worker."""
    def _score(textes: pd.Series) -> pd.DataFrame:
        return scoring.scorer_serie(textes, modeles)
    return F.pandas_udf(_score, SCHEMA_SCORE)


@dataclass
class Lot:
    """Sorties d'un micro-lot. Les DataFrames partagent un `scored` mis en cache."""
    posts: DataFrame          # lignes froides (MinIO), colonne `dt` en plus pour la partition
    cibles_fenetre: DataFrame
    posts_fenetre: DataFrame
    themes_fenetre: DataFrame
    pipeline_fenetre: DataFrame
    croisements_fenetre: DataFrame
    adjectifs_fenetre: DataFrame
    _cache: DataFrame

    def agregats(self) -> dict[str, DataFrame]:
        return {t: getattr(self, t) for t in TABLES_CLICKHOUSE}

    def liberer(self) -> None:
        self._cache.unpersist()


def traiter_micro_lot(df: DataFrame, spark: SparkSession | None = None,
                      fenetre_minutes: int = 5, maintenant_us: int | None = None,
                      modeles: mdl.Modeles | None = None) -> Lot:
    """`df` : colonnes `time_us` (long) et `texte` (nettoyé). Le texte est jeté après le scoring ;
    la latence est calculée avec `time_us` puis `time_us` est jeté lui aussi."""
    spark = spark or df.sparkSession
    score_udf = creer_score_udf(modeles)
    libelle = scoring.libelle_scoreur(modeles)
    maintenant_us = int(time.time() * 1_000_000) if maintenant_us is None else maintenant_us
    fen_us = fenetre_minutes * 60 * 1_000_000

    scored = (df.select("time_us", score_udf(F.col("texte")).alias("s"))
              .select(
                  F.expr(f"timestamp_micros(cast(floor(time_us / {fen_us}) * {fen_us} as bigint))")
                  .alias("fenetre_debut"),
                  F.greatest(F.lit(0), F.floor((F.lit(maintenant_us) - F.col("time_us")) / 1000)
                             ).cast("long").alias("latence_ms"),
                  F.col("s.cibles").alias("cibles"), F.col("s.sentiment").alias("sentiment"),
                  F.col("s.emotion").alias("emotion"), F.col("s.themes").alias("themes"),
                  F.col("s.adjectifs").alias("adjectifs"), F.col("s.retenu").alias("retenu"),
              ).cache())

    pipeline = scored.groupBy("fenetre_debut").agg(
        F.count(F.lit(1)).cast("long").alias("nb_posts"),
        F.sum("latence_ms").cast("long").alias("somme_latence_ms"),
        F.lit(maintenant_us // 1_000_000).cast("timestamp").alias("derniere_maj"),
    )

    # filtre fin : au moins une entité, un thème ou une émotion reconnus par le lexique
    retenus = scored.where(F.col("retenu"))

    lignes = (retenus.select("fenetre_debut", F.explode("cibles").alias("c"),
                             "sentiment", "emotion", "themes")
              .select("fenetre_debut",
                      F.lit("fr").alias("langue"),
                      F.col("c.entite").alias("entite"),
                      F.col("c.stance").alias("stance"),
                      "sentiment", "emotion", "themes",
                      F.col("c.confiance").alias("confiance"),
                      F.lit(libelle).alias("scoreur")))

    cibles = (lignes.where(F.col("entite").isNotNull())
              .groupBy("fenetre_debut", "entite", "stance")
              .agg(F.count(F.lit(1)).cast("long").alias("nb_posts")))
    posts_f = (retenus.groupBy("fenetre_debut", "sentiment", "emotion")
               .agg(F.count(F.lit(1)).cast("long").alias("nb_posts")))
    themes_f = (retenus.select("fenetre_debut", F.explode("themes").alias("theme"))
                .groupBy("fenetre_debut", "theme")
                .agg(F.count(F.lit(1)).cast("long").alias("nb_posts")))
    froides = lignes.withColumn("dt", F.date_format("fenetre_debut", "yyyy-MM-dd"))
    # une occurrence par (post, cible ou '', thème) : un post à deux cibles et deux thèmes compte 4
    croisements = (retenus.select("fenetre_debut", F.explode("cibles").alias("c"),
                                  "sentiment", "emotion", "themes")
                   .select("fenetre_debut",
                           F.coalesce(F.col("c.entite"), F.lit("")).alias("entite"),
                           F.col("c.stance").alias("stance"),
                           "sentiment", "emotion",
                           F.explode("themes").alias("theme"))
                   .groupBy("fenetre_debut", "entite", "stance", "sentiment", "emotion", "theme")
                   .agg(F.count(F.lit(1)).cast("long").alias("nb_posts"))
                   .select("fenetre_debut", "entite", "stance", "sentiment", "emotion", "theme",
                           F.lit(libelle).alias("scoreur"), "nb_posts"))
    # une occurrence par (post, cible évaluée pour ou contre, adjectif du lexique) : l'adjectif
    # est rattaché à chaque cible du post, sans lien grammatical (src/streaming/AGENTS.md)
    adjectifs = (retenus.select("fenetre_debut", F.explode("cibles").alias("c"), "adjectifs")
                 .where(F.col("c.entite").isNotNull() & F.col("c.stance").isin("pour", "contre"))
                 .select("fenetre_debut", F.col("c.entite").alias("entite"),
                         F.col("c.stance").alias("stance"), F.explode("adjectifs").alias("adjectif"))
                 .groupBy("fenetre_debut", "entite", "stance", "adjectif")
                 .agg(F.count(F.lit(1)).cast("long").alias("nb_posts"))
                 .select("fenetre_debut", "entite", "stance", "adjectif",
                         F.lit(libelle).alias("scoreur"), "nb_posts"))
    return Lot(froides, cibles, posts_f, themes_f, pipeline, croisements, adjectifs, scored)


# --- (c) écriture -----------------------------------------------------------------
def ecrire_micro_lot(cfg: Config, modeles: mdl.Modeles | None = None):
    def _ecrire(batch_df: DataFrame, batch_id: int) -> None:
        if batch_df.isEmpty():
            return
        spark = batch_df.sparkSession
        lot = traiter_micro_lot(batch_df, spark, cfg.fenetre_minutes, modeles=modeles)
        try:
            n_lignes = lot.posts.count()
            n_posts = lot._cache.count()
            # MinIO d'abord, puis ClickHouse (ordre des écritures du contrat)
            (lot.posts.write.mode("append").partitionBy("dt")
             .parquet(f"s3a://{cfg.bucket_scores}/posts/"))
            for table, agg in lot.agregats().items():
                agg.writeTo(f"clickhouse.{cfg.clickhouse_db}.{table}").append()
            log.warning("lot=%s posts=%s lignes_minio=%s", batch_id, n_posts, n_lignes)
        finally:
            lot.liberer()
    return _ecrire


# --- (d) reprise après expiration de l'état (M6) ------------------------------------
# La règle MinIO supprime `streaming/state/` après un jour. Un job arrêté plus longtemps ne
# relit plus son état : il efface le checkpoint et redémarre (Docker relance le conteneur).
CODE_REINITIALISATION = 3
PREFIXE_ETAT = "streaming/state/"


def chemin_checkpoint(cfg: Config) -> str:
    return f"s3a://{cfg.bucket_checkpoints}/streaming/"


def etat_checkpoint_perdu(message: str) -> bool:
    """Vrai si l'échec vient d'un fichier d'état du checkpoint introuvable (et seulement de lui)."""
    fichier_manquant = "Error reading delta file" in message or "FileNotFoundException" in message
    return fichier_manquant and PREFIXE_ETAT in message


def chaine_messages(exc: BaseException) -> str:
    """Message de l'exception et de ses causes : Spark enveloppe l'erreur Java d'origine."""
    morceaux, vus, courant = [], set(), exc
    while courant is not None and id(courant) not in vus:
        vus.add(id(courant))
        morceaux.append(str(courant))
        courant = courant.__cause__ or courant.__context__
    return "\n".join(morceaux)


def supprimer_checkpoint(fs, chemin) -> None:
    """Efface le checkpoint entier. `fs` : org.apache.hadoop.fs.FileSystem ; `chemin` : Path."""
    fs.delete(chemin, True)


def reinitialiser_checkpoint(spark: SparkSession, url: str) -> None:
    jvm = spark.sparkContext._jvm
    chemin = jvm.org.apache.hadoop.fs.Path(url)
    fs = chemin.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    supprimer_checkpoint(fs, chemin)


def traiter_arret(exc: Exception, reinitialiser) -> None:
    """Réinitialise puis quitte si l'état est perdu ; relance toute autre erreur telle quelle."""
    if not etat_checkpoint_perdu(chaine_messages(exc)):
        raise exc
    log.error("checkpoint réinitialisé : état expiré (M6), reprise depuis le début de Kafka")
    reinitialiser()
    raise SystemExit(CODE_REINITIALISATION) from None


def creer_session(cfg: Config) -> SparkSession:
    b = (SparkSession.builder.appName("sae-streaming")
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.hadoop.fs.s3a.endpoint", cfg.s3_endpoint)
         .config("spark.hadoop.fs.s3a.access.key", cfg.s3_access_key)
         .config("spark.hadoop.fs.s3a.secret.key", cfg.s3_secret_key)
         .config("spark.hadoop.fs.s3a.path.style.access", "true")
         .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
         .config("spark.sql.catalog.clickhouse", "com.clickhouse.spark.ClickHouseCatalog")
         .config("spark.sql.catalog.clickhouse.host", cfg.clickhouse_host)
         .config("spark.sql.catalog.clickhouse.protocol", "http")
         .config("spark.sql.catalog.clickhouse.http_port", cfg.clickhouse_port)
         .config("spark.sql.catalog.clickhouse.user", cfg.clickhouse_user)
         .config("spark.sql.catalog.clickhouse.password", cfg.clickhouse_password)
         .config("spark.sql.catalog.clickhouse.database", cfg.clickhouse_db))
    return b.getOrCreate()


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.depuis_env()
    modeles = mdl.Modeles.depuis_env()
    try:
        modeles.verifier()  # arrêt au démarrage si un run désigné est illisible
    except mdl.ModeleError as e:
        log.error("%s", e)
        raise SystemExit(2) from None
    log.warning("scoreur=%s", scoring.libelle_scoreur(modeles))
    spark = creer_session(cfg)
    spark.sparkContext.setLogLevel("WARN")
    ici = os.path.dirname(os.path.abspath(__file__))
    for module in ("pii.py", "scoring.py", "modeles.py"):  # importables dans les workers Python
        spark.sparkContext.addPyFile(os.path.join(ici, module))
    requete = (construire_flux(spark, cfg).writeStream
               .foreachBatch(ecrire_micro_lot(cfg, modeles))
               .option("checkpointLocation", chemin_checkpoint(cfg))
               .trigger(processingTime=f"{cfg.trigger_seconds} seconds")
               .start())
    try:
        requete.awaitTermination()
    except Exception as exc:
        traiter_arret(exc, lambda: reinitialiser_checkpoint(spark, chemin_checkpoint(cfg)))


if __name__ == "__main__":
    main()
