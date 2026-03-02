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
