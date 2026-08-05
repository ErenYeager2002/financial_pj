#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/financial-platform}"
APP_USER="${APP_USER:-financial-platform}"
APP_GROUP="${APP_GROUP:-financial-platform}"
DATA_DIR="${DATA_DIR:-/var/lib/financial-platform}"
CONFIG_DIR="${CONFIG_DIR:-/etc/financial-platform}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must run as root." >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "${PYTHON_BIN} is required." >&2
  exit 1
fi

if [[ ! -f "${APP_ROOT}/backend/pyproject.toml" ]]; then
  echo "Project is missing at ${APP_ROOT}." >&2
  exit 1
fi

if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
  groupadd --system "${APP_GROUP}"
fi
if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${APP_GROUP}" \
    --home-dir "${DATA_DIR}" \
    --shell /usr/sbin/nologin \
    "${APP_USER}"
fi

install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${DATA_DIR}"
install -d -o root -g "${APP_GROUP}" -m 0750 "${CONFIG_DIR}"

if [[ ! -f "${CONFIG_DIR}/financial-platform.env" ]]; then
  install \
    -o root \
    -g "${APP_GROUP}" \
    -m 0640 \
    "${APP_ROOT}/deploy/financial-platform.env.example" \
    "${CONFIG_DIR}/financial-platform.env"
fi

"${PYTHON_BIN}" -m venv "${APP_ROOT}/.venv"
"${APP_ROOT}/.venv/bin/python" -m pip install --upgrade pip
"${APP_ROOT}/.venv/bin/python" -m pip install "${APP_ROOT}/backend"
"${APP_ROOT}/.venv/bin/python" -m playwright install chromium

chown -R root:"${APP_GROUP}" "${APP_ROOT}"
chmod -R g-w,o-rwx "${APP_ROOT}"

install -o root -g root -m 0644 \
  "${APP_ROOT}/deploy/systemd/financial-platform-api.service" \
  /etc/systemd/system/financial-platform-api.service
install -o root -g root -m 0644 \
  "${APP_ROOT}/deploy/systemd/financial-platform-worker@.service" \
  /etc/systemd/system/financial-platform-worker@.service

systemctl daemon-reload
systemctl enable --now financial-platform-api.service
for instance in python-1 python-2 http-1 http-2 workflow-1 workflow-2; do
  systemctl enable --now "financial-platform-worker@${instance}.service"
done

echo "Financial platform services installed."
