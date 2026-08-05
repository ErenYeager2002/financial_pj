#!/usr/bin/env bash
set -euo pipefail

instance="${1:-}"
if [[ ! "${instance}" =~ ^(python|http|workflow)-[1-9][0-9]*$ ]]; then
  echo "Invalid worker instance: ${instance}" >&2
  exit 2
fi

pool="${instance%%-*}"
exec /opt/financial-platform/.venv/bin/python \
  -m app.worker \
  --pools "${pool}" \
  --worker-id "${instance}"
