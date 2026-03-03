#!/usr/bin/env bash
set -euo pipefail

APP_NAME="imperium-deck-client"
INSTALL_DIR="${HOME}/apps/${APP_NAME}"
NATIVE_DIR="${INSTALL_DIR}/native-ui"
APPIMAGE_OUT="${NATIVE_DIR}/ImperiumDeckClient.AppImage"
NATIVEFIER_TMP_DIR="${NATIVE_DIR}/.nativefier-build"
NATIVEFIER_OUT_DIR="${NATIVE_DIR}/ImperiumDeckClient-native"
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

cd "${NATIVE_DIR}"
npm install

TAURI_OK=0
if command -v cargo >/dev/null 2>&1 || command -v rustup >/dev/null 2>&1; then
  if ! command -v cargo >/dev/null 2>&1 && command -v rustup >/dev/null 2>&1; then
    rustup default stable || true
  fi

  if npm run build; then
    APPIMAGE_BUILT=$(find src-tauri/target/release/bundle/appimage -maxdepth 1 -type f -name '*.AppImage' | head -n 1)
    if [[ -n "${APPIMAGE_BUILT}" ]]; then
      cp "${APPIMAGE_BUILT}" "${APPIMAGE_OUT}"
      chmod +x "${APPIMAGE_OUT}"
      TAURI_OK=1
    fi
  fi
fi

if [[ "${TAURI_OK}" -eq 0 ]]; then
  echo "Tauri build unavailable on this system; building Electron native wrapper with nativefier."
  rm -rf "${NATIVEFIER_TMP_DIR}" "${NATIVEFIER_OUT_DIR}"
  mkdir -p "${NATIVEFIER_TMP_DIR}"

  npx --yes nativefier \
    --name "ImperiumDeckClient" \
    --platform "linux" \
    --arch "x64" \
    --single-instance \
    "http://127.0.0.1:8765" \
    "${NATIVEFIER_TMP_DIR}"

  BUILT_DIR=$(find "${NATIVEFIER_TMP_DIR}" -maxdepth 1 -type d -name 'ImperiumDeckClient-linux-*' | head -n 1)
  if [[ -z "${BUILT_DIR}" ]]; then
    echo "nativefier build artifact not found." >&2
    exit 1
  fi

  mv "${BUILT_DIR}" "${NATIVEFIER_OUT_DIR}"
  chmod +x "${NATIVEFIER_OUT_DIR}/ImperiumDeckClient"
fi

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

if [[ "${TAURI_OK}" -eq 1 ]]; then
  echo "Native UI built (Tauri AppImage): ${APPIMAGE_OUT}"
else
  echo "Native UI built (nativefier): ${NATIVEFIER_OUT_DIR}/ImperiumDeckClient"
fi
echo "Desktop launcher updated: ${DESKTOP_FILE}"
