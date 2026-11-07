"""Preuve de compatibilité des versions : Kafka, S3A/MinIO et ClickHouse depuis le cluster Spark.

Soumis par infra/checks/connectivite.py (qui prépare le topic et la table jetables).
Aucune donnée réelle : le topic de test ne contient que des messages inventés.
"""
import os
import socket
import sys

from pyspark.sql import SparkSession

TOPIC = "test-connectivite"
CHEMIN = "s3a://scores/test-connectivite/"
TABLE = "clickhouse.sae.test_connectivite"
ATTENDU = 20

spark = SparkSession.builder.appName("sae-connectivite").getOrCreate()
sc = spark.sparkContext
echecs = []


def etape(nom, fn):
    try:
        print(f"OK  {nom} ({fn()})")
    except Exception as exc:
        echecs.append(nom)
        lignes = str(exc).splitlines()
        cause = next((l for l in reversed(lignes) if "Exception" in l or "Code:" in l), lignes[0])
        print(f"KO  {nom} ({type(exc).__name__}: {cause.strip()[:300]})")


def kafka():
    df = (spark.read.format("kafka")
          .option("kafka.bootstrap.servers", os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"))
          .option("subscribe", TOPIC).option("startingOffsets", "earliest")
          .option("endingOffsets", "latest").option("minPartitions", 4).load())
    n = df.count()
    assert n == ATTENDU, f"{n} messages au lieu de {ATTENDU}"
    return f"{n} messages sur {df.rdd.getNumPartitions()} partitions"


def parquet():
    df = spark.range(1000).selectExpr("id", "id % 7 AS k")
    df.write.mode("overwrite").parquet(CHEMIN)
    n = spark.read.parquet(CHEMIN).count()
    assert n == 1000, f"{n} lignes relues"
    jvm = spark._jvm
    chemin = jvm.org.apache.hadoop.fs.Path(CHEMIN)
    fs = chemin.getFileSystem(sc._jsc.hadoopConfiguration())
    fs.delete(chemin, True)
    return f"{n} lignes écrites, relues, supprimées"


def clickhouse():
    df = spark.createDataFrame([(i, f"ligne-{i}") for i in range(10)], "id int, nom string")
    df.writeTo(TABLE).append()
    n = spark.table(TABLE).count()
    assert n == 10, f"{n} lignes relues"
    return f"{n} lignes insérées et relues via clickhouse-spark"


def workers():
    hotes = (sc.parallelize(range(8), 8).map(lambda _: socket.gethostname()).distinct().collect())
    assert len(hotes) == 2, f"{len(hotes)} hôte(s) d'executor"
    return f"{len(hotes)} executors distincts"


etape("Kafka (spark-sql-kafka, lecture batch)", kafka)
etape("MinIO (S3A, Parquet écriture/relecture)", parquet)
etape("ClickHouse (clickhouse-spark, compte pipeline)", clickhouse)
etape("Cluster (tâches réparties sur les workers)", workers)
print(f"Master : {sc.master}, executors : {len(sc._jsc.sc().statusTracker().getExecutorInfos()) - 1}")
spark.stop()
sys.exit(1 if echecs else 0)
