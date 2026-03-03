# Imperium Deck Client

Imperium Deck Client is an open-source Steam Deck runtime service for controller remapping and scene-aware input behavior.

## What It Does

- Reads Steam Deck controller input (`evdev`/`hidraw`)
- Applies remaps and click-point rules
- Applies runtime navigation graph behavior
- Exposes a local API for external tools (for example a CMS)

## Quick Start (Steam Deck)

Run these commands in Desktop Mode on a fresh Steam Deck:

```bash
sudo steamos-readonly disable
sudo pacman-key --init
sudo pacman-key --populate archlinux
sudo pacman -Syu --noconfirm git python python-pip base-devel

mkdir -p ~/apps
cd ~/apps
git clone https://github.com/SnyderConsulting/imperium-deck-client.git
cd imperium-deck-client
./scripts/install.sh
```

The installer will:
- Install app files to `~/apps/imperium-deck-client`
- Create `.venv` and install dependencies
- Install and enable `~/.config/systemd/user/imperium-deck-client.service`

## Service Commands

Check status:

```bash
systemctl --user status imperium-deck-client.service
```

Follow logs:

```bash
journalctl --user -u imperium-deck-client.service -f
```

Update:

```bash
cd ~/apps/imperium-deck-client
./scripts/update.sh
```

Uninstall:

```bash
cd ~/apps/imperium-deck-client
./scripts/uninstall.sh
```

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.server:app --host 0.0.0.0 --port 8765
```

## Cloud Profile Source

Deck client pulls cloud profiles from:

- `SDR_PROFILE_SOURCE_URL` (default: `https://www.imperium-gaming.com`)

Example:

```bash
SDR_PROFILE_SOURCE_URL=https://www.imperium-gaming.com \
uvicorn app.server:app --host 0.0.0.0 --port 8765
```

React UI endpoints used for sync:

- `GET /api/sync/projects`
- `POST /api/sync/projects/{project_id}/pull` (saves locally and applies)

## React UI Development

The client UI is a React app in `frontend/`, built into `web/` for runtime serving.

```bash
cd frontend
npm install
npm run build
```

## Native UI (Desktop Wrapper)

This repo includes a native wrapper app under `native-ui/` that embeds the local client UI (`http://127.0.0.1:8765`) in a native window.

On Steam Deck:

```bash
cd ~/apps/imperium-deck-client
./scripts/build_native_ui.sh
```

Then launch via desktop shortcut:

- `~/Desktop/Imperium Deck Client.desktop`

Build behavior:
- First tries a Tauri AppImage build.
- If Tauri build dependencies are not available on the Deck image, automatically falls back to a native Electron wrapper (`nativefier`).
- If neither native artifact is available, launcher falls back to opening the browser UI.

## API Endpoint

By default the service runs on:

- `http://0.0.0.0:8765` (Deck local runtime)

On your LAN, access via:

- `http://<steam-deck-ip>:8765`

## Project Status

- Standalone runtime is the supported direction.
- Decky integration is currently out of scope.

## Contributing

Issues and pull requests are welcome.

## License

License file not added yet. Add an OSI-approved `LICENSE` file before broad public release.
