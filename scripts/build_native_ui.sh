#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
NATIVE_DIR="${INSTALL_DIR}/native-ui"
APPIMAGE_OUT="${NATIVE_DIR}/ImperiumDeckClient.AppImage"
DESKTOP_FILE="${HOME}/Desktop/Imperium Deck Client.desktop"

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "Install directory not found: ${INSTALL_DIR}" >&2
  echo "Run scripts/install.sh first." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build native UI." >&2
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  if command -v rustup >/dev/null 2>&1; then
    rustup default stable
  else
    echo "Rust toolchain missing. Install rustup first:" >&2
    echo "  curl https://sh.rustup.rs -sSf | sh -s -- -y" >&2
    exit 1
  fi
fi

cd "${NATIVE_DIR}"
npm install
npm run build

APPIMAGE_BUILT=$(find src-tauri/target/release/bundle/appimage -maxdepth 1 -type f -name '*.AppImage' | head -n 1)
if [[ -z "${APPIMAGE_BUILT}" ]]; then
  echo "AppImage build artifact not found." >&2
  exit 1
fi

cp "${APPIMAGE_BUILT}" "${APPIMAGE_OUT}"
chmod +x "${APPIMAGE_OUT}"

cat > "${DESKTOP_FILE}" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Imperium Deck Client
Comment=Native launcher for Imperium Deck Client
Exec=bash -lc '${INSTALL_DIR}/scripts/launch_native_ui.sh'
Icon=applications-internet
Terminal=false
Categories=Utility;Game;
StartupNotify=true
DESKTOP
chmod +x "${DESKTOP_FILE}"

echo "Native UI built: ${APPIMAGE_OUT}"
echo "Desktop launcher updated: ${DESKTOP_FILE}"
