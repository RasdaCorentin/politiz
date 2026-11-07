#!/usr/bin/env python3
"""Contrôle de la pile sae-poc : une ligne OK/KO par vérification, jamais de donnée affichée.

Usage : python3 infra/verifier.py   (stdlib seule ; docker compose requis pour Kafka et MinIO)
"""
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

INFRA = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", str(INFRA / "docker-compose.yml")]
CH = "http://127.0.0.1:18123/"
SPARK = "http://127.0.0.1:18080/json/"

TOPIC = {"retention.ms": "3600000", "segment.ms": "600000",
         "retention.bytes": "1073741824", "cleanup.policy": "delete"}
TABLES = {"cibles_fenetre", "posts_fenetre", "themes_fenetre", "pipeline_fenetre", "croisements_fenetre",
          "adjectifs_fenetre"}

resultats = []


def controle(nom, fn):
    try:
        ok, detail = fn()
    except Exception as exc:  # un contrôle qui plante est un KO, pas un arrêt
        ok, detail = False, type(exc).__name__
    resultats.append(ok)
    print(f"{'OK' if ok else 'KO'}  {nom}" + (f" ({detail})" if detail else ""))


def env():
    valeurs = {}
    for ligne in (INFRA / ".env").read_text().splitlines():
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, val = ligne.split("=", 1)
            valeurs[cle.strip()] = val.strip()
    return valeurs


def docker(*args, entree=None):
    return subprocess.run([*COMPOSE, *args], capture_output=True, text=True, timeout=120, input=entree)


def clickhouse(sql, user, mdp):
    """Renvoie (code HTTP, corps). Le corps ne sert jamais à l'affichage."""
    req = urllib.request.Request(CH + "?" + urllib.parse.urlencode({"user": user, "password": mdp}),
                                 data=sql.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as rep:
            return rep.status, rep.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


# --- Kafka ---------------------------------------------------------------------------------

def kafka_topic():
    sortie = docker("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server",
                    "localhost:9092", "--describe", "--topic", "raw-posts").stdout
    manque = [f"{k}={v}" for k, v in TOPIC.items() if f"{k}={v}" not in sortie]
    if "PartitionCount: 4" not in sortie or "ReplicationFactor: 1" not in sortie:
        manque.append("partitions=4/réplication=1")
    return not manque, "écart : " + ", ".join(manque) if manque else "4 partitions, réplication 1, 4 paramètres"


def kafka_retention_check():
    sortie = docker("exec", "-T", "kafka", "/opt/kafka/bin/kafka-configs.sh", "--bootstrap-server",
                    "localhost:9092", "--entity-type", "brokers", "--entity-name", "1",
                    "--describe", "--all").stdout
    return "log.retention.check.interval.ms=60000" in sortie, "60000 ms"


# --- MinIO ---------------------------------------------------------------------------------

MC = """set -eu
mc alias set root http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc alias set pip http://minio:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null
mc stat root/scores >/dev/null 2>&1 && echo B_SCORES ok || echo B_SCORES ko
mc stat root/checkpoints >/dev/null 2>&1 && echo B_CKPT ok || echo B_CKPT ko
echo ILM_SCORES $(mc ilm rule ls --json root/scores | tr -d ' \\n')
echo ILM_CKPT $(mc ilm rule ls --json root/checkpoints | tr -d ' \\n')
mc ls pip/scores >/dev/null 2>&1 && echo PIP_SCORES ok || echo PIP_SCORES ko
mc ls pip/checkpoints >/dev/null 2>&1 && echo PIP_CKPT ok || echo PIP_CKPT ko
mc mb pip/intrus >/dev/null 2>&1 && echo PIP_MB oui || echo PIP_MB non
echo test | mc pipe pip/scores/.verif >/dev/null 2>&1 && echo PIP_PUT ok || echo PIP_PUT ko
mc rm root/scores/.verif >/dev/null 2>&1 || true
"""


def mc():
    cmd = [*COMPOSE, "run", "--rm", "-T", "--no-deps", "--entrypoint", "/bin/sh", "minio-init", "-c", MC]
    sortie = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    return {l.split(" ", 1)[0]: l.split(" ", 1)[1] if " " in l else "" for l in sortie.splitlines()}


def compact(texte):
    return texte.replace(" ", "")


def verifier_minio():
    m = mc()
    controle("MinIO : buckets scores et checkpoints",
             lambda: (m.get("B_SCORES", "").strip() == "ok" and m.get("B_CKPT", "").strip() == "ok", ""))
    controle("MinIO : expiration 30 jours sur scores",
             lambda: ('"Days":30' in compact(m.get("ILM_SCORES", "")), ""))
    ck = compact(m.get("ILM_CKPT", ""))
    controle("MinIO : expiration 1 jour sur checkpoints, préfixe streaming/state/",
             lambda: ('"Days":1}' in ck and "streaming/state/" in ck, ""))
    controle("MinIO : compte pipeline accède aux deux buckets",
             lambda: (m.get("PIP_SCORES", "").strip() == "ok" and m.get("PIP_CKPT", "").strip() == "ok"
                      and m.get("PIP_PUT", "").strip() == "ok", ""))
    controle("MinIO : compte pipeline ne crée pas d'autre bucket",
             lambda: (m.get("PIP_MB", "").strip() == "non", ""))


# --- ClickHouse ----------------------------------------------------------------------------

def verifier_clickhouse(e):
    pipe = ("pipeline", e["CLICKHOUSE_PIPELINE_PASSWORD"])
    dash = ("dashboard", e["CLICKHOUSE_DASHBOARD_PASSWORD"])

    def tables():
        code, corps = clickhouse("SELECT name FROM system.tables WHERE database='sae' FORMAT TSV", *pipe)
        return code == 200 and set(corps.split()) == TABLES, "6 tables"

    def refuse(sql, user):
        # Refus = 401/403, ou 500 dont le corps porte le code ClickHouse 497 (droits) ou 164 (readonly).
        code, corps = clickhouse(sql, *user)
        motif = next((c for c in ("Code: 497", "Code: 164", "Code: 516") if c in corps), "")
        return code in (401, 403) or (code == 500 and bool(motif)), f"HTTP {code} {motif}".strip()

    controle("ClickHouse : base sae et 6 tables", tables)
    for table in ("croisements_fenetre", "adjectifs_fenetre"):
        controle(f"ClickHouse : table {table} présente",
                 lambda t=table: (clickhouse(f"EXISTS TABLE sae.{t} FORMAT TSV", *pipe)[1].strip() == "1",
                                  "migration appliquée"))
    controle("ClickHouse : default inaccessible depuis le réseau",
             lambda: refuse("SELECT 1", ("default", "")))
    controle("ClickHouse : pipeline lit sae.*",
             lambda: (clickhouse("SELECT count() FROM sae.posts_fenetre", *pipe)[0] == 200, ""))
    controle("ClickHouse : pipeline insère dans sae.* (lot vide)",
             lambda: (clickhouse("INSERT INTO sae.posts_fenetre SELECT * FROM sae.posts_fenetre WHERE 0", *pipe)[0] == 200, ""))
    controle("ClickHouse : pipeline ne supprime pas de table",
             lambda: refuse("DROP TABLE sae.posts_fenetre", pipe))
    controle("ClickHouse : dashboard lit sae.*",
             lambda: (clickhouse("SELECT count() FROM sae.posts_fenetre", *dash)[0] == 200, ""))
    controle("ClickHouse : dashboard ne peut pas insérer",
             lambda: refuse("INSERT INTO sae.posts_fenetre SELECT * FROM sae.posts_fenetre WHERE 0", dash))
    controle("ClickHouse : dashboard ne lit pas system.users",
             lambda: refuse("SELECT count() FROM system.users", dash))


# --- Spark ---------------------------------------------------------------------------------

def spark_cluster():
    with urllib.request.urlopen(SPARK, timeout=10) as rep:
        etat = json.load(rep)
    vivants = [w for w in etat["workers"] if w["state"] == "ALIVE"]
    cores = sum(w["cores"] for w in vivants)
    return len(vivants) == 2 and cores == 4, f"{len(vivants)} workers vivants, {cores} cœurs"


def dashboard_api():
    # Relais nginx (routes du dashboard dans le contrat) : /api/sante passe par le port hôte 8501.
    with urllib.request.urlopen("http://127.0.0.1:8501/api/sante", timeout=10) as rep:
        return rep.status == 200, "HTTP 200 via nginx"


def main():
    e = env()
    controle("Kafka : topic raw-posts (partitions et paramètres du contrat)", kafka_topic)
    controle("Kafka : vérification de rétention toutes les 60 s", kafka_retention_check)
    verifier_minio()
    verifier_clickhouse(e)
    controle("Spark : master avec 2 workers, 4 cœurs", spark_cluster)
    # Contrôle du dashboard seulement si le profil pipeline tourne : sinon il est sauté, hors compte.
    actifs = docker("--profile", "pipeline", "ps", "--status", "running", "--services").stdout.split()
    if "dashboard-api" in actifs:
        controle("Dashboard : /api/sante répond 200 via nginx", dashboard_api)
    else:
        print("--  Dashboard : profil pipeline inactif, contrôle sauté")
    ko = resultats.count(False)
    print(f"\n{len(resultats) - ko}/{len(resultats)} contrôles OK")
    return 1 if ko else 0


if __name__ == "__main__":
    sys.exit(main())
