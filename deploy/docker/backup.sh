#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/srv/financial-platform/deploy/docker}"
DATA_DIR="${DATA_DIR:-${DEPLOY_ROOT}/runtime/data}"
BACKUP_DIR="${BACKUP_DIR:-/srv/financial-platform/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
CONTAINER="${CONTAINER:-financial-platform-api}"

stamp="$(date +%Y%m%d-%H%M%S)"
snapshot_name=".financial-db-${stamp}.snapshot"
snapshot_host="${DATA_DIR}/${snapshot_name}"
archive_tmp="${BACKUP_DIR}/financial-platform-${stamp}.tar.gz.tmp"
archive="${BACKUP_DIR}/financial-platform-${stamp}.tar.gz"

install -d -m 0700 "${BACKUP_DIR}"

cleanup() {
  rm -f -- "${snapshot_host}" "${archive_tmp}"
}
trap cleanup EXIT

docker exec -i "${CONTAINER}" python - "${snapshot_name}" <<'PY'
import sqlite3
import sys
from pathlib import Path

data_dir = Path("/var/lib/financial-platform")
source = sqlite3.connect(data_dir / "financial.db")
target = sqlite3.connect(data_dir / sys.argv[1])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY

tar \
  --create \
  --gzip \
  --file "${archive_tmp}" \
  --directory "${DATA_DIR}" \
  --exclude "./financial.db" \
  --exclude "./financial.db-shm" \
  --exclude "./financial.db-wal" \
  --exclude "./.cache" \
  --transform "s|^\./${snapshot_name}$|./financial.db|" \
  .

mv -- "${archive_tmp}" "${archive}"
rm -f -- "${snapshot_host}"
find "${BACKUP_DIR}" \
  -maxdepth 1 \
  -type f \
  -name 'financial-platform-*.tar.gz' \
  -mtime "+${RETENTION_DAYS}" \
  -delete

trap - EXIT
printf '%s\n' "${archive}"
