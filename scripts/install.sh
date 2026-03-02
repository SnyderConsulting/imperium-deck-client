#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_SRC_REL="deploy/${SERVICE_NAME}"
SERVICE_DEST_DIR="${HOME}/.config/systemd/user"
SERVICE_DEST="${SERVICE_DEST_DIR}/${SERVICE_NAME}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install python3 first." >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found. This installer requires systemd user services." >&2
  exit 1
fi

mkdir -p "${HOME}/apps"

if [[ "${REPO_DIR}" != "${INSTALL_DIR}" ]]; then
  if [[ -e "${INSTALL_DIR}" ]]; then
    echo "Install target already exists: ${INSTALL_DIR}" >&2
    echo "Remove it first or run update script from that location." >&2
    exit 1
  fi
  cp -a "${REPO_DIR}" "${INSTALL_DIR}"
fi

cd "${INSTALL_DIR}"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

mkdir -p "${SERVICE_DEST_DIR}"
cp "${SERVICE_SRC_REL}" "${SERVICE_DEST}"

systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE_NAME}"

echo "Installed ${APP_NAME}."
echo "Service: ${SERVICE_NAME}"
echo "Status: systemctl --user status ${SERVICE_NAME}"
echo "Logs: journalctl --user -u ${SERVICE_NAME} -f"
