#!/usr/bin/env python3
"""Lance la vérification de connectivité Spark (Kafka, MinIO, ClickHouse) sur la pile démarrée.

Prépare un topic et une table jetables, soumet spark_connectivity.py au cluster, nettoie.
Usage : python3 infra/checks/connectivite.py   (stdlib seule)
"""
import subprocess
import sys
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", str(INFRA / "docker-compose.yml")]
KAFKA = "/opt/kafka/bin/"


def sh(*args, entree=None, check=True):
    return subprocess.run([*COMPOSE, *args], text=True, input=entree, check=check)


def main():
    sh("exec", "-T", "kafka", KAFKA + "kafka-topics.sh", "--bootstrap-server", "localhost:9092",
       "--create", "--if-not-exists", "--topic", "test-connectivite", "--partitions", "4",
       "--replication-factor", "1")
    messages = "".join(f'{{"message_test":{i}}}\n' for i in range(20))
    sh("exec", "-T", "kafka", KAFKA + "kafka-console-producer.sh", "--bootstrap-server",
       "localhost:9092", "--topic", "test-connectivite", entree=messages)
    sh("exec", "-T", "clickhouse", "clickhouse-client", "-q", "DROP TABLE IF EXISTS sae.test_connectivite")
    sh("exec", "-T", "clickhouse", "clickhouse-client", "-q",
       "CREATE TABLE sae.test_connectivite (id Int32, nom String) ENGINE = MergeTree ORDER BY id")
    soumission = (
        "exec /opt/spark/bin/spark-submit --master spark://spark-master:7077 --deploy-mode client "
        "--conf spark.executor.cores=2 --conf spark.cores.max=4 --conf spark.executor.memory=$EXECUTOR_MEMORY "
        "--conf spark.driver.memory=512m --conf spark.driver.host=$(hostname) "
        "--conf spark.driver.bindAddress=0.0.0.0 --conf spark.ui.enabled=false "
        "--conf spark.hadoop.fs.s3a.access.key=$S3_ACCESS_KEY --conf spark.hadoop.fs.s3a.secret.key=$S3_SECRET_KEY "
        "--conf spark.sql.catalog.clickhouse.user=$CLICKHOUSE_USER "
        "--conf spark.sql.catalog.clickhouse.password=$CLICKHOUSE_PASSWORD "
        "/opt/checks/spark_connectivity.py")
    try:
        code = sh("run", "--rm", "--no-deps", "-T", "-v", f"{INFRA / 'checks'}:/opt/checks:ro",
                  "streaming", "/bin/sh", "-c", soumission, check=False).returncode
    finally:
        sh("exec", "-T", "clickhouse", "clickhouse-client", "-q", "DROP TABLE IF EXISTS sae.test_connectivite", check=False)
        sh("exec", "-T", "kafka", KAFKA + "kafka-topics.sh", "--bootstrap-server", "localhost:9092",
           "--delete", "--topic", "test-connectivite", check=False)
    print("Connectivité :", "OK" if code == 0 else "KO")
    return code


if __name__ == "__main__":
    sys.exit(main())
