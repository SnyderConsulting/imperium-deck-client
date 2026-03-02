# Imperium Deck Client

Steam Deck runtime service for Imperium.

## Responsibilities

- Read controller input (`evdev`/`hidraw`)
- Apply key remaps and click point rules
- Apply navigation graph runtime behavior
- Expose runtime APIs used by CMS/proxy flows

## Run

```bash
cd imperium-deck-client
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.server:app --host 0.0.0.0 --port 8765
```

## Install On Steam Deck (Standalone)

From this repo directory:

```bash
cd imperium-deck-client
./scripts/install.sh
```

This installs the app to `~/apps/imperium-deck-client`, creates a venv, installs dependencies, and enables:
- `~/.config/systemd/user/imperium-deck-client.service`

Useful commands:

```bash
systemctl --user status imperium-deck-client.service
journalctl --user -u imperium-deck-client.service -f
```

Update:

```bash
cd imperium-deck-client
./scripts/update.sh
```

Uninstall:

```bash
cd imperium-deck-client
./scripts/uninstall.sh
```

## Decky Direction

This codebase is the source target for a Decky Loader plugin wrapper.
