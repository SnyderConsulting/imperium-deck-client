#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_FILE="${HOME}/.config/systemd/user/${SERVICE_NAME}"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
  systemctl --user daemon-reload
fi

rm -f "${SERVICE_FILE}"

if [[ -d "${INSTALL_DIR}" ]]; then
  rm -rf "${INSTALL_DIR}"
fi

echo "Uninstalled ${APP_NAME}."
