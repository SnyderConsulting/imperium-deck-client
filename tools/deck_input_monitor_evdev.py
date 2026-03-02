#!/usr/bin/env python3
from __future__ import annotations

import curses
import select
import time
from collections import deque
from typing import Any

from evdev import InputDevice, ecodes, list_devices

BUTTON_ALIASES: dict[str, list[str]] = {
    "A": ["BTN_SOUTH", "BTN_A"],
    "B": ["BTN_EAST", "BTN_B"],
    "X": ["BTN_WEST", "BTN_X"],
    "Y": ["BTN_NORTH", "BTN_Y"],
    "L1": ["BTN_TL"],
    "R1": ["BTN_TR"],
    "L2": ["BTN_TL2"],
    "R2": ["BTN_TR2"],
    "L3": ["BTN_THUMBL"],
    "R3": ["BTN_THUMBR"],
    "START": ["BTN_START"],
    "SELECT": ["BTN_SELECT"],
    "MODE": ["BTN_MODE"],
}

AXES = [
    "ABS_X", "ABS_Y", "ABS_RX", "ABS_RY", "ABS_Z", "ABS_RZ", "ABS_HAT0X", "ABS_HAT0Y",
]


def pick_devices() -> list[InputDevice]:
    devs: list[InputDevice] = []
    for p in list_devices():
        try:
            d = InputDevice(p)
        except Exception:
            continue
        name = (d.name or "").lower()
        if "x-box 360 pad" in name:
            devs.append(d)
        elif "steam deck controller" in name:
            devs.append(d)
    if devs:
        return devs

    fallback: list[InputDevice] = []
    for p in list_devices():
        try:
            d = InputDevice(p)
            caps = d.capabilities()
            if ecodes.EV_KEY in caps and ecodes.EV_ABS in caps:
                fallback.append(d)
            else:
                d.close()
        except Exception:
            continue
    return fallback


def key_name(code: int) -> str:
    return ecodes.BTN.get(code) or ecodes.KEY.get(code) or f"KEY_{code}"


def abs_name(code: int) -> str:
    return ecodes.ABS.get(code) or f"ABS_{code}"


def run(stdscr: Any) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)

    devices = pick_devices()
    if not devices:
        stdscr.addstr(0, 0, "No controller-like input devices found. Press Q to quit.")
        stdscr.refresh()
        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                return
            time.sleep(0.05)

    key_state: dict[str, int] = {}
    hit_count: dict[str, int] = {}
    axis_state: dict[str, int] = {}
    recent: deque[str] = deque(maxlen=14)

    for d in devices:
        d.grab_context = None

    while True:
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break

        r, _, _ = select.select(devices, [], [], 0.05)
        for dev in r:
            try:
                for ev in dev.read():
                    if ev.type == ecodes.EV_KEY:
                        kn = key_name(ev.code)
                        key_state[kn] = int(ev.value)
                        if int(ev.value) == 1:
                            hit_count[kn] = hit_count.get(kn, 0) + 1
                            recent.appendleft(f"{time.strftime('%H:%M:%S')} {dev.name}: {kn} DOWN")
                    elif ev.type == ecodes.EV_ABS:
                        an = abs_name(ev.code)
                        axis_state[an] = int(ev.value)
                        if an == "ABS_HAT0X":
                            key_state["DPAD_LEFT"] = 1 if ev.value < 0 else 0
                            key_state["DPAD_RIGHT"] = 1 if ev.value > 0 else 0
                        elif an == "ABS_HAT0Y":
                            key_state["DPAD_UP"] = 1 if ev.value < 0 else 0
                            key_state["DPAD_DOWN"] = 1 if ev.value > 0 else 0
            except BlockingIOError:
                pass
            except OSError:
                pass

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        line = 0

        title = "Deck Input Monitor (EVDEV) - Press Q to quit"
        stdscr.addnstr(line, 0, title, w - 1)
        line += 1
        stdscr.addnstr(line, 0, "Devices: " + ", ".join(f"{d.path} {d.name}" for d in devices), w - 1)
        line += 2

        stdscr.addnstr(line, 0, "Canonical Buttons:", w - 1)
        line += 1
        row = []
        for lbl, aliases in BUTTON_ALIASES.items():
            v = 1 if any(key_state.get(a, 0) for a in aliases) else 0
            row.append(f"{lbl}:{v}")
        for dpad in ["DPAD_UP", "DPAD_RIGHT", "DPAD_DOWN", "DPAD_LEFT"]:
            row.append(f"{dpad.replace('DPAD_', 'D-')}:{1 if key_state.get(dpad,0) else 0}")
        rowtxt = "  ".join(row)
        stdscr.addnstr(line, 0, rowtxt, w - 1)
        line += 2

        stdscr.addnstr(line, 0, "Axes:", w - 1)
        line += 1
        for a in AXES:
            if line >= h - 8:
                break
            stdscr.addnstr(line, 0, f"{a:10} {axis_state.get(a, 0):6}", w - 1)
            line += 1

        line += 1
        active = [k for k, v in key_state.items() if v]
        stdscr.addnstr(line, 0, "Raw Active Keys: " + (", ".join(active) if active else "-"), w - 1)
        line += 1

        top_hits = sorted(hit_count.items(), key=lambda kv: kv[1], reverse=True)[:6]
        stdscr.addnstr(line, 0, "Top Hit Counters: " + (", ".join(f"{k}:{v}" for k, v in top_hits) if top_hits else "-"), w - 1)
        line += 2

        stdscr.addnstr(line, 0, "Recent DOWN events:", w - 1)
        line += 1
        for item in recent:
            if line >= h - 1:
                break
            stdscr.addnstr(line, 0, item, w - 1)
            line += 1

        stdscr.refresh()

    for d in devices:
        try:
            d.close()
        except Exception:
            pass


def main() -> int:
    curses.wrapper(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
