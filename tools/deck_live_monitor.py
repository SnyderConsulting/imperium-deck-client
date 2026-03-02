#!/usr/bin/env python3
from __future__ import annotations

import curses
import json
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = "http://127.0.0.1:8765/api/state"

BUTTON_ALIASES: dict[str, list[str]] = {
    "A": ["A", "BTN_SOUTH", "BTN_A"],
    "B": ["B", "BTN_EAST", "BTN_B"],
    "X": ["X", "BTN_WEST", "BTN_X", "BTN_NORTH"],
    "Y": ["Y", "BTN_NORTH", "BTN_Y", "BTN_WEST"],
    "D-UP": ["DPAD_UP"],
    "D-RIGHT": ["DPAD_RIGHT"],
    "D-DOWN": ["DPAD_DOWN"],
    "D-LEFT": ["DPAD_LEFT"],
    "L1": ["L1", "BTN_TL"],
    "R1": ["R1", "BTN_TR"],
    "L2": ["L2_BTN", "L2", "BTN_TL2"],
    "R2": ["R2_BTN", "R2", "BTN_TR2"],
    "L3": ["L3", "BTN_THUMBL"],
    "R3": ["R3", "BTN_THUMBR"],
    "L4": ["L4"],
    "R4": ["R4"],
    "L5": ["L5"],
    "R5": ["R5"],
    "MENU": ["MENU", "BTN_SELECT"],
    "STEAM": ["STEAM", "BTN_MODE"],
    "QAM": ["QAM", "BTN_START"],
    "LPAD": ["LEFT_PAD_PRESS"],
    "RPAD": ["RIGHT_PAD_PRESS"],
    "LTOUCH": ["LEFT_PAD_TOUCH"],
    "RTOUCH": ["RIGHT_PAD_TOUCH"],
}

AXIS_ALIASES: dict[str, list[str]] = {
    "LS_X": ["LEFT_STICK_X", "ABS_X"],
    "LS_Y": ["LEFT_STICK_Y", "ABS_Y"],
    "RS_X": ["RIGHT_STICK_X", "ABS_RX", "ABS_Z"],
    "RS_Y": ["RIGHT_STICK_Y", "ABS_RY", "ABS_RZ"],
    "DPAD_X": ["ABS_HAT0X"],
    "DPAD_Y": ["ABS_HAT0Y"],
    "LPAD_X": ["LEFT_PAD_X"],
    "LPAD_Y": ["LEFT_PAD_Y"],
    "RPAD_X": ["RIGHT_PAD_X"],
    "RPAD_Y": ["RIGHT_PAD_Y"],
}


def fetch_state() -> dict[str, Any]:
    with urllib.request.urlopen(API_URL, timeout=0.2) as r:
        return json.loads(r.read().decode("utf-8"))


def merged_state(state_by_dev: dict[str, Any]) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    buttons: dict[str, int] = {}
    axes: dict[str, int] = {}
    hits: dict[str, int] = {}

    for dev in state_by_dev.values():
        for k, v in (dev.get("buttons") or {}).items():
            if int(v) != 0:
                buttons[k] = int(v)
            elif k not in buttons:
                buttons[k] = 0
        for k, v in (dev.get("axes") or {}).items():
            v = int(v)
            if k not in axes or abs(v) > abs(axes[k]):
                axes[k] = v
        for k, v in (dev.get("hits") or {}).items():
            hits[k] = max(int(v), hits.get(k, 0))
    return buttons, axes, hits


def get_button_value(buttons: dict[str, int], aliases: list[str]) -> int:
    for key in aliases:
        if int(buttons.get(key, 0)) != 0:
            return 1
    return 0


def get_axis_value(axes: dict[str, int], aliases: list[str]) -> int:
    for key in aliases:
        if key in axes:
            return int(axes[key])
    return 0


def run(stdscr: Any) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)

    last_error = ""
    while True:
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            return

        data: dict[str, Any] | None = None
        try:
            data = fetch_state()
            last_error = ""
        except urllib.error.URLError as exc:
            last_error = f"API unreachable: {exc}"
        except Exception as exc:
            last_error = f"Error: {exc}"

        stdscr.erase()
        h, w = stdscr.getmaxyx()

        title = "Steam Deck Live Input (press Q to quit)"
        stdscr.addnstr(0, 0, title, w - 1)
        stdscr.addnstr(1, 0, "-" * max(1, w - 1), w - 1)

        line = 2
        if last_error:
            stdscr.addnstr(line, 0, last_error, w - 1)
            stdscr.refresh()
            time.sleep(0.1)
            continue

        state_by_dev = (data or {}).get("state") or {}
        event_count = int((data or {}).get("event_count", 0))
        buttons, axes, hits = merged_state(state_by_dev)

        stdscr.addnstr(line, 0, f"Devices: {', '.join(state_by_dev.keys())[:w-10]}", w - 1)
        line += 1
        stdscr.addnstr(line, 0, f"Event Count: {event_count}", w - 1)
        line += 1

        btn_parts = []
        for label, aliases in BUTTON_ALIASES.items():
            val = get_button_value(buttons, aliases)
            btn_parts.append(f"{label}:{'1' if val else '0'}")

        stdscr.addnstr(line, 0, "Buttons:", w - 1)
        line += 1
        row = ""
        for part in btn_parts:
            test = (row + "  " + part).strip()
            if len(test) >= w - 1:
                stdscr.addnstr(line, 0, row, w - 1)
                line += 1
                row = part
            else:
                row = test
        if row:
            stdscr.addnstr(line, 0, row, w - 1)
            line += 1

        stdscr.addnstr(line, 0, "Axes:", w - 1)
        line += 1
        for label, aliases in AXIS_ALIASES.items():
            val = get_axis_value(axes, aliases)
            stdscr.addnstr(line, 0, f"{label:8} {val:6}", w - 1)
            line += 1
            if line >= h - 2:
                break

        if line < h - 2:
            line += 1
            top_hits = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)[:8]
            stdscr.addnstr(line, 0, "Top Hit Counters:", w - 1)
            line += 1
            for k, v in top_hits:
                stdscr.addnstr(line, 0, f"{k}: {v}", w - 1)
                line += 1
                if line >= h - 1:
                    break

        stdscr.refresh()


def main() -> int:
    curses.wrapper(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
