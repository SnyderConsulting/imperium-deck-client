#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from evdev import AbsInfo, UInput, ecodes

OUT_PATH = Path("/tmp/sd_kmsgrab_latest.png")


def capture_once(timeout_seconds: float) -> dict[str, object]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "kmsgrab",
        "-device",
        "/dev/dri/card0",
        "-i",
        "-",
        "-vf",
        "hwmap=derive_device=vaapi,hwdownload,format=bgr0",
        "-frames:v",
        "1",
        str(OUT_PATH),
    ]
    started = time.time()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(1.0, timeout_seconds),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"ffmpeg exited {proc.returncode}")
    if not OUT_PATH.exists():
        raise RuntimeError("ffmpeg reported success but output image is missing")

    raw = OUT_PATH.read_bytes()
    return {
        "ok": True,
        "provider": "kmsgrab_helper",
        "path": str(OUT_PATH),
        "bytes": len(raw),
        "captured_at": time.time(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "data_url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
    }


def _keycode_for(name: str) -> int:
    key = str(name or "").strip()
    if not key:
        raise ValueError("empty key")
    upper = key.upper()
    aliases = {
        "ESC": "KEY_ESC",
        "ESCAPE": "KEY_ESC",
        "RETURN": "KEY_ENTER",
        "ENTER": "KEY_ENTER",
        "TAB": "KEY_TAB",
        "SPACE": "KEY_SPACE",
        "BACKSPACE": "KEY_BACKSPACE",
        "LEFT": "KEY_LEFT",
        "RIGHT": "KEY_RIGHT",
        "UP": "KEY_UP",
        "DOWN": "KEY_DOWN",
    }
    key_name = aliases.get(upper)
    if key_name is None:
        if len(key) == 1 and key.isalpha():
            key_name = f"KEY_{key.upper()}"
        elif len(key) == 1 and key.isdigit():
            key_name = f"KEY_{key}"
        elif upper.startswith("KEY_"):
            key_name = upper
        else:
            key_name = f"KEY_{upper}"
    code = getattr(ecodes, key_name, None)
    if code is None:
        raise ValueError(f"unknown key: {name}")
    return int(code)


class InputInjector:
    def __init__(self) -> None:
        key_codes = [getattr(ecodes, f"KEY_{c}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        key_codes.extend(getattr(ecodes, f"KEY_{d}") for d in "0123456789")
        key_codes.extend(
            [
                ecodes.KEY_ESC,
                ecodes.KEY_ENTER,
                ecodes.KEY_TAB,
                ecodes.KEY_SPACE,
                ecodes.KEY_BACKSPACE,
                ecodes.KEY_LEFT,
                ecodes.KEY_RIGHT,
                ecodes.KEY_UP,
                ecodes.KEY_DOWN,
                ecodes.KEY_LEFTSHIFT,
                ecodes.KEY_RIGHTSHIFT,
                ecodes.KEY_LEFTCTRL,
                ecodes.KEY_RIGHTCTRL,
                ecodes.KEY_LEFTALT,
                ecodes.KEY_RIGHTALT,
            ]
        )
        self.keyboard = UInput({ecodes.EV_KEY: sorted(set(int(x) for x in key_codes))}, name="sdremap-keyboard")
        self.pointer = UInput(
            {
                ecodes.EV_KEY: [
                    ecodes.BTN_LEFT,
                    ecodes.BTN_RIGHT,
                    ecodes.BTN_MIDDLE,
                ],
                ecodes.EV_REL: [
                    ecodes.REL_X,
                    ecodes.REL_Y,
                ],
            },
            name="sdremap-pointer",
        )
        self.cursor_width = int(float(__import__("os").environ.get("SDR_CURSOR_WIDTH", "1280")))
        self.cursor_height = int(float(__import__("os").environ.get("SDR_CURSOR_HEIGHT", "800")))
        self.touch = UInput(
            {
                ecodes.EV_KEY: [
                    ecodes.BTN_TOUCH,
                    ecodes.BTN_TOOL_FINGER,
                ],
                ecodes.EV_ABS: [
                    (ecodes.ABS_X, AbsInfo(value=0, min=0, max=32767, fuzz=0, flat=0, resolution=0)),
                    (ecodes.ABS_Y, AbsInfo(value=0, min=0, max=32767, fuzz=0, flat=0, resolution=0)),
                    (ecodes.ABS_MT_SLOT, AbsInfo(value=0, min=0, max=9, fuzz=0, flat=0, resolution=0)),
                    (ecodes.ABS_MT_POSITION_X, AbsInfo(value=0, min=0, max=32767, fuzz=0, flat=0, resolution=0)),
                    (ecodes.ABS_MT_POSITION_Y, AbsInfo(value=0, min=0, max=32767, fuzz=0, flat=0, resolution=0)),
                    (ecodes.ABS_MT_TRACKING_ID, AbsInfo(value=0, min=0, max=65535, fuzz=0, flat=0, resolution=0)),
                    (ecodes.ABS_MT_PRESSURE, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                ],
            },
            name="sdremap-touchscreen",
            input_props=[ecodes.INPUT_PROP_DIRECT],
        )

    def emit_key(self, key_name: str) -> None:
        upper = str(key_name or "").strip().upper()
        if upper in ("LMB", "RMB"):
            btn = ecodes.BTN_LEFT if upper == "LMB" else ecodes.BTN_RIGHT
            self.pointer.write(ecodes.EV_KEY, btn, 1)
            self.pointer.syn()
            time.sleep(0.01)
            self.pointer.write(ecodes.EV_KEY, btn, 0)
            self.pointer.syn()
            return
        code = _keycode_for(key_name)
        self.keyboard.write(ecodes.EV_KEY, code, 1)
        self.keyboard.syn()
        time.sleep(0.01)
        self.keyboard.write(ecodes.EV_KEY, code, 0)
        self.keyboard.syn()

    def emit_click(self, x_norm: float, y_norm: float, button: str = "left") -> None:
        # Steam Deck touch input space is rotated and vertically inverted
        # relative to screenshot space: touch_x = 1 - screenshot_y,
        # touch_y = screenshot_x.
        x = int(max(0.0, min(1.0, 1.0 - float(y_norm))) * 32767)
        y = int(max(0.0, min(1.0, float(x_norm))) * 32767)

        # Primary path: synthesize a touchscreen tap at normalized coordinates.
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, 0)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, 1)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_X, x)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_Y, y)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_PRESSURE, 80)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
        self.touch.write(ecodes.EV_KEY, ecodes.BTN_TOOL_FINGER, 1)
        self.touch.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
        self.touch.syn()
        time.sleep(0.02)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, -1)
        self.touch.write(ecodes.EV_ABS, ecodes.ABS_MT_PRESSURE, 0)
        self.touch.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
        self.touch.write(ecodes.EV_KEY, ecodes.BTN_TOOL_FINGER, 0)
        self.touch.syn()

        # Secondary path: emit a pointer click at current cursor.
        btn = {"left": ecodes.BTN_LEFT, "middle": ecodes.BTN_MIDDLE, "right": ecodes.BTN_RIGHT}.get(
            str(button or "left").lower(),
            ecodes.BTN_LEFT,
        )
        self.pointer.write(ecodes.EV_KEY, btn, 1)
        self.pointer.syn()
        time.sleep(0.01)
        self.pointer.write(ecodes.EV_KEY, btn, 0)
        self.pointer.syn()

    def move_cursor(self, x_norm: float, y_norm: float) -> None:
        x_norm = max(0.0, min(1.0, float(x_norm)))
        y_norm = max(0.0, min(1.0, float(y_norm)))
        # Convert normalized target into logical cursor pixels.
        tx = int(round(x_norm * max(1, self.cursor_width - 1)))
        ty = int(round(y_norm * max(1, self.cursor_height - 1)))

        # REL events are relative-only; first "home" hard to top-left so we can
        # then move by absolute-looking offsets and avoid accumulated drift.
        self.pointer.write(ecodes.EV_REL, ecodes.REL_X, -32767)
        self.pointer.write(ecodes.EV_REL, ecodes.REL_Y, -32767)
        self.pointer.syn()
        time.sleep(0.001)

        if tx != 0:
            self.pointer.write(ecodes.EV_REL, ecodes.REL_X, tx)
        if ty != 0:
            self.pointer.write(ecodes.EV_REL, ecodes.REL_Y, ty)
        self.pointer.syn()


INJECTOR = InputInjector()


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"ok": True, "service": "sd-kmsgrab-helper"})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/capture", "/emit/key", "/emit/click", "/emit/move"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {}

        if self.path == "/emit/key":
            try:
                key = str(data.get("key", "")).strip()
                INJECTOR.emit_key(key)
                self._json(200, {"ok": True, "emitted": "key", "key": key})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if self.path == "/emit/click":
            try:
                x = float(data.get("x", 0.0))
                y = float(data.get("y", 0.0))
                button = str(data.get("button", "left"))
                INJECTOR.emit_click(x_norm=x, y_norm=y, button=button)
                self._json(200, {"ok": True, "emitted": "click", "x": x, "y": y, "button": button})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if self.path == "/emit/move":
            try:
                x = float(data.get("x", 0.0))
                y = float(data.get("y", 0.0))
                INJECTOR.move_cursor(x_norm=x, y_norm=y)
                self._json(200, {"ok": True, "emitted": "move", "x": x, "y": y})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        timeout_seconds = 8.0
        timeout_seconds = float(data.get("timeout_seconds", timeout_seconds))
        try:
            out = capture_once(timeout_seconds=timeout_seconds)
            self._json(200, out)
        except subprocess.TimeoutExpired:
            self._json(504, {"ok": False, "error": "kmsgrab timed out"})
        except Exception as exc:
            self._json(500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18765)
    args = p.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
