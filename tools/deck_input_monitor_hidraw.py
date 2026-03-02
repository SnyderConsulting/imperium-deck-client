#!/usr/bin/env python3
from __future__ import annotations

import curses
import os
import select
import struct
import time
from collections import deque
from pathlib import Path
from typing import Any
import errno
import fcntl

from evdev import InputDevice, ecodes

HID_ID_TARGET = "000028DE:00001205"


def s16(data: bytes, lo: int, hi: int) -> int:
    return struct.unpack('<h', data[lo:hi])[0]


def decode(data: bytes) -> dict[str, int]:
    if len(data) < 56:
        return {}
    out: dict[str, int] = {}
    b8 = data[8]
    out['A'] = int(bool(b8 & (1 << 7)))
    out['B'] = int(bool(b8 & (1 << 5)))
    out['X'] = int(bool(b8 & (1 << 6)))
    out['Y'] = int(bool(b8 & (1 << 4)))
    out['R2'] = int(bool(b8 & (1 << 0)))
    out['L2'] = int(bool(b8 & (1 << 1)))
    out['R1'] = int(bool(b8 & (1 << 2)))
    out['L1'] = int(bool(b8 & (1 << 3)))

    b9 = data[9]
    out['DPAD_UP'] = int(bool(b9 & (1 << 0)))
    out['DPAD_RIGHT'] = int(bool(b9 & (1 << 1)))
    out['DPAD_LEFT'] = int(bool(b9 & (1 << 2)))
    out['DPAD_DOWN'] = int(bool(b9 & (1 << 3)))
    out['QAM'] = int(bool(b9 & (1 << 4)))
    out['STEAM'] = int(bool(b9 & (1 << 5)))
    out['MENU'] = int(bool(b9 & (1 << 6)))
    out['L5'] = int(bool(b9 & (1 << 7)))

    b10 = data[10]
    out['R5'] = int(bool(b10 & (1 << 0)))
    out['LEFT_PAD_PRESS'] = int(bool(b10 & (1 << 1)))
    out['RIGHT_PAD_PRESS'] = int(bool(b10 & (1 << 2)))
    out['LEFT_PAD_TOUCH'] = int(bool(b10 & (1 << 3)))
    out['RIGHT_PAD_TOUCH'] = int(bool(b10 & (1 << 4)))
    out['L3'] = int(bool(b10 & (1 << 6)))

    b11 = data[11]
    out['R3'] = int(bool(b11 & (1 << 2)))

    b13 = data[13]
    out['L4'] = int(bool(b13 & (1 << 1)))
    out['R4'] = int(bool(b13 & (1 << 2)))
    out['LEFT_STICK_TOUCH'] = int(bool(b13 & (1 << 6)))
    out['RIGHT_STICK_TOUCH'] = int(bool(b13 & (1 << 7)))

    out['LEFT_STICK_X'] = s16(data, 48, 50)
    out['LEFT_STICK_Y'] = s16(data, 50, 52)
    out['RIGHT_STICK_X'] = s16(data, 52, 54)
    out['RIGHT_STICK_Y'] = s16(data, 54, 56)
    out['LEFT_PAD_X'] = s16(data, 16, 18)
    out['LEFT_PAD_Y'] = s16(data, 18, 20)
    out['RIGHT_PAD_X'] = s16(data, 20, 22)
    out['RIGHT_PAD_Y'] = s16(data, 22, 24)
    return out


def discover_hidraw_paths() -> list[str]:
    preferred: list[str] = []
    others: list[str] = []
    for p in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        dev = p.name
        uevent = p / "device" / "uevent"
        props: dict[str, str] = {}
        try:
            for line in uevent.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v
        except Exception:
            continue
        hid_id = props.get("HID_ID", "")
        phys = props.get("HID_PHYS", "")
        if HID_ID_TARGET not in hid_id:
            continue
        path = f"/dev/{dev}"
        if phys.endswith("input2"):
            preferred.append(path)
        else:
            others.append(path)
    return preferred + others


def discover_evdev_paths() -> list[str]:
    out: list[str] = []
    for p in sorted(Path("/dev/input").glob("event*")):
        try:
            d = InputDevice(str(p))
            name = (d.name or "").lower()
            d.close()
        except Exception:
            continue
        if "steam deck controller" in name or "x-box 360 pad" in name:
            out.append(str(p))
    return out


def run(stdscr: Any) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)

    paths = discover_hidraw_paths()
    fds: dict[int, str] = {}
    for p in paths:
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = p
        except Exception:
            pass

    if not fds:
        stdscr.addstr(0, 0, f'Cannot open Steam Deck hidraw devices (target {HID_ID_TARGET})')
        stdscr.addstr(1, 0, 'Press Q to quit')
        stdscr.refresh()
        while True:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q')):
                return
            time.sleep(0.05)

    evdev_paths = discover_evdev_paths()
    evdev_devs: list[InputDevice] = []
    for p in evdev_paths:
        try:
            d = InputDevice(p)
            flags = fcntl.fcntl(d.fd, fcntl.F_GETFL)
            fcntl.fcntl(d.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            evdev_devs.append(d)
        except Exception:
            pass

    state_by_path: dict[str, dict[str, int]] = {}
    state: dict[str, int] = {}
    hits: dict[str, int] = {}
    recent = deque(maxlen=12)
    last_raw_by_path: dict[str, bytes] = {}
    changed_bytes = deque(maxlen=10)

    try:
        while True:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q')):
                break

            read_fds: list[Any] = list(fds.keys()) + evdev_devs
            r, _, _ = select.select(read_fds, [], [], 0.02)
            if r:
                # Drain queued reports so UI reflects current state instead of seconds-old backlog.
                for item in r:
                    if isinstance(item, int):
                        fd = item
                        path = fds[fd]
                        while True:
                            try:
                                data = os.read(fd, 256)
                            except OSError as exc:
                                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                                    break
                                raise
                            if not data:
                                break
                            last_raw = last_raw_by_path.get(path)
                            if last_raw is not None:
                                changed = [i for i, (a, b) in enumerate(zip(last_raw, data)) if a != b]
                                if changed:
                                    changed_bytes.appendleft(f"{Path(path).name}: " + ' '.join(str(i) for i in changed[:14]))
                            last_raw_by_path[path] = data
                            state_by_path[path] = decode(data)
                    else:
                        d = item
                        try:
                            for ev in d.read():
                                if ev.type != ecodes.EV_KEY:
                                    continue
                                name = ecodes.BTN.get(ev.code) or ecodes.KEY.get(ev.code) or str(ev.code)
                                v = int(ev.value)
                                state[name] = v
                                if name == "BTN_LEFT":
                                    state["LEFT_PAD_PRESS"] = 1 if v else 0
                                elif name == "BTN_RIGHT":
                                    state["RIGHT_PAD_PRESS"] = 1 if v else 0
                                elif name == "BTN_MIDDLE":
                                    state["LEFT_PAD_PRESS"] = 1 if v else 0
                                    state["RIGHT_PAD_PRESS"] = 1 if v else 0
                        except BlockingIOError:
                            pass
                        except OSError:
                            pass

                # Merge decoded states from all hidraw endpoints.
                merged: dict[str, int] = {}
                for _path, st in state_by_path.items():
                    for k, v in st.items():
                        if k.endswith("_X") or k.endswith("_Y"):
                            cur = merged.get(k, 0)
                            if abs(v) > abs(cur):
                                merged[k] = v
                        else:
                            merged[k] = 1 if int(v) or int(merged.get(k, 0)) else 0

                for k, v in merged.items():
                    prev = state.get(k, 0)
                    state[k] = v
                    if isinstance(v, int) and k.isupper() and v == 1 and prev != 1:
                        hits[k] = hits.get(k, 0) + 1
                        recent.appendleft(f"{time.strftime('%H:%M:%S')} {k} DOWN")

            stdscr.erase()
            h, w = stdscr.getmaxyx()
            line = 0
            stdscr.addnstr(line, 0, f"Deck Monitor hidraw[{', '.join(paths)}] evdev[{', '.join(evdev_paths)}] - Q to quit", w - 1)
            line += 1
            stdscr.addnstr(line, 0, '-' * max(1, w - 1), w - 1)
            line += 1

            buttons = ['A','B','X','Y','L1','R1','L2','R2','L3','R3','L4','R4','L5','R5','MENU','STEAM','QAM','DPAD_UP','DPAD_RIGHT','DPAD_DOWN','DPAD_LEFT','LEFT_PAD_PRESS','RIGHT_PAD_PRESS','LEFT_PAD_TOUCH','RIGHT_PAD_TOUCH']
            row = []
            for b in buttons:
                row.append(f"{b}:{state.get(b,0)}")
            txt = '  '.join(row)
            stdscr.addnstr(line, 0, txt, w - 1)
            line += 2

            axes = ['LEFT_STICK_X','LEFT_STICK_Y','RIGHT_STICK_X','RIGHT_STICK_Y','LEFT_PAD_X','LEFT_PAD_Y','RIGHT_PAD_X','RIGHT_PAD_Y']
            stdscr.addnstr(line, 0, 'Axes:', w - 1)
            line += 1
            for a in axes:
                stdscr.addnstr(line, 0, f"{a:14} {state.get(a,0):6}", w - 1)
                line += 1
                if line >= h - 8:
                    break

            if line < h - 6:
                line += 1
                top = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)[:8]
                stdscr.addnstr(line, 0, 'Hit counters: ' + (', '.join(f'{k}:{v}' for k, v in top) if top else '-'), w - 1)
                line += 1
                stdscr.addnstr(line, 0, 'Recent DOWN:', w - 1)
                line += 1
                for item in recent:
                    if line >= h - 1:
                        break
                    stdscr.addnstr(line, 0, item, w - 1)
                    line += 1

            if line < h - 1:
                stdscr.addnstr(line, 0, 'Changed byte indexes (raw):', w - 1)
                line += 1
                for item in changed_bytes:
                    if line >= h - 1:
                        break
                    stdscr.addnstr(line, 0, item, w - 1)
                    line += 1

            stdscr.refresh()
    finally:
        for fd in list(fds.keys()):
            try:
                os.close(fd)
            except Exception:
                pass
        for d in evdev_devs:
            try:
                d.close()
            except Exception:
                pass


def main() -> int:
    curses.wrapper(run)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
