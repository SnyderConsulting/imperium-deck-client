#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
APPIMAGE_PATH="${INSTALL_DIR}/native-ui/ImperiumDeckClient.AppImage"

systemctl --user start "${SERVICE_NAME}" >/dev/null 2>&1 || true

if [[ -x "${APPIMAGE_PATH}" ]]; then
  exec "${APPIMAGE_PATH}"
fi

exec xdg-open "http://127.0.0.1:8765"
