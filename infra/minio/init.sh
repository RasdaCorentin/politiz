#!/bin/sh
# Initialisation idempotente de MinIO (buckets et expiration fixés par le contrat MinIO). Exécuté par le service minio-init.
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

mc mb --ignore-existing local/scores
mc mb --ignore-existing local/checkpoints
mc mb --ignore-existing local/modeles

# Cycle de vie : on repart d'une liste vide pour que les règles ne se cumulent pas.
mc ilm rule rm --all --force local/scores >/dev/null 2>&1 || true
mc ilm rule rm --all --force local/checkpoints >/dev/null 2>&1 || true
mc ilm rule add --expire-days 30 local/scores
mc ilm rule add --prefix streaming/state/ --expire-days 1 local/checkpoints

# Compte de service pipeline, limité aux deux buckets.
mc admin user svcacct rm local "$S3_ACCESS_KEY" >/dev/null 2>&1 || true
mc admin user svcacct add local "$MINIO_ROOT_USER" \
  --access-key "$S3_ACCESS_KEY" --secret-key "$S3_SECRET_KEY" \
  --policy /init/politique-pipeline.json >/dev/null
echo "minio-init : buckets, cycle de vie et compte pipeline en place"
