from __future__ import annotations

import json

from app.server import discover_devices, default_device_paths


if __name__ == "__main__":
    print(json.dumps({"default": default_device_paths(), "devices": discover_devices()}, indent=2))
