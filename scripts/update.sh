#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
DESKTOP_SRC_REL="deploy/imperium-deck-client.desktop"
DESKTOP_DEST_DIR="${HOME}/Desktop"
DESKTOP_DEST="${DESKTOP_DEST_DIR}/Imperium Deck Client.desktop"

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
if ! python -m pip install -r requirements.txt; then
  echo "Primary dependency install failed; retrying with evdev-binary fallback."
  TMP_REQ="$(mktemp)"
  grep -v '^evdev' requirements.txt > "${TMP_REQ}"
  python -m pip install -r "${TMP_REQ}"
  python -m pip install evdev-binary
  rm -f "${TMP_REQ}"
fi

mkdir -p "${DESKTOP_DEST_DIR}"
cp "${DESKTOP_SRC_REL}" "${DESKTOP_DEST}"
chmod +x "${DESKTOP_DEST}"

systemctl --user daemon-reload
systemctl --user restart "${SERVICE_NAME}"

echo "Updated ${APP_NAME}."
echo "Status: systemctl --user status ${SERVICE_NAME}"
