#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "Install directory not found: ${INSTALL_DIR}" >&2
  echo "Run scripts/install.sh first." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git not found. Install git first." >&2
  exit 1
fi

cd "${INSTALL_DIR}"
git pull --ff-only

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

systemctl --user daemon-reload
systemctl --user restart "${SERVICE_NAME}"

echo "Updated ${APP_NAME}."
echo "Status: systemctl --user status ${SERVICE_NAME}"
