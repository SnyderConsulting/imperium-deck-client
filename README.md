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

## Decky Direction

This codebase is the source target for a Decky Loader plugin wrapper.
