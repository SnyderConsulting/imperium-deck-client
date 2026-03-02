#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import select
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaptureStats:
    samples: list[bytes]


def read_reports(fd: int, duration: float, report_len: int = 64) -> CaptureStats:
    end = time.time() + duration
    out: list[bytes] = []
    while time.time() < end:
        timeout = max(0.0, end - time.time())
        r, _, _ = select.select([fd], [], [], min(0.2, timeout))
        if not r:
            continue
        data = os.read(fd, report_len)
        if len(data) >= report_len:
            out.append(data[:report_len])
    return CaptureStats(samples=out)


def bit_prob(samples: list[bytes], byte_idx: int, bit_idx: int) -> float:
    if not samples:
        return 0.0
    mask = 1 << bit_idx
    return sum(1 for s in samples if s[byte_idx] & mask) / len(samples)


def byte_mean(samples: list[bytes], byte_idx: int) -> float:
    if not samples:
        return 0.0
    return statistics.fmean(s[byte_idx] for s in samples)


def s16_mean(samples: list[bytes], lo: int) -> float:
    if not samples:
        return 0.0
    vals = []
    for s in samples:
        v = int.from_bytes(s[lo:lo + 2], byteorder="little", signed=True)
        vals.append(v)
    return statistics.fmean(vals)


def analyze(baseline: list[bytes], hold: list[bytes]) -> dict:
    bit_changes = []
    for bi in range(64):
        for bt in range(8):
            p0 = bit_prob(baseline, bi, bt)
            p1 = bit_prob(hold, bi, bt)
            d = p1 - p0
            if abs(d) >= 0.20:
                bit_changes.append(
                    {
                        "byte": bi,
                        "bit": bt,
                        "delta": round(d, 3),
                        "baseline_p1": round(p0, 3),
                        "hold_p1": round(p1, 3),
                    }
                )
    bit_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

    byte_changes = []
    for bi in range(64):
        m0 = byte_mean(baseline, bi)
        m1 = byte_mean(hold, bi)
        d = m1 - m0
        if abs(d) >= 2.0:
            byte_changes.append(
                {
                    "byte": bi,
                    "delta_mean": round(d, 2),
                    "baseline_mean": round(m0, 2),
                    "hold_mean": round(m1, 2),
                }
            )
    byte_changes.sort(key=lambda x: abs(x["delta_mean"]), reverse=True)

    s16_changes = []
    for lo in range(0, 63, 2):
        m0 = s16_mean(baseline, lo)
        m1 = s16_mean(hold, lo)
        d = m1 - m0
        if abs(d) >= 40:
            s16_changes.append(
                {
                    "lo": lo,
                    "hi": lo + 1,
                    "delta_mean": round(d, 1),
                    "baseline_mean": round(m0, 1),
                    "hold_mean": round(m1, 1),
                }
            )
    s16_changes.sort(key=lambda x: abs(x["delta_mean"]), reverse=True)

    return {
        "bit_changes": bit_changes[:16],
        "byte_changes": byte_changes[:16],
        "s16_changes": s16_changes[:16],
    }


def prompt(msg: str) -> None:
    print(msg, flush=True)


def wait_countdown(seconds: int) -> None:
    for i in range(seconds, 0, -1):
        print(f"  {i}...", flush=True)
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate Steam Deck HID mapping from hidraw reports.")
    parser.add_argument("--hidraw", default="/dev/hidraw1", help="hidraw device path")
    parser.add_argument("--rest-seconds", type=float, default=1.5)
    parser.add_argument("--hold-seconds", type=float, default=2.5)
    parser.add_argument("--out", default="/tmp/steamdeck_hid_calibration.json")
    args = parser.parse_args()

    if not Path(args.hidraw).exists():
        print(f"Missing hidraw node: {args.hidraw}", file=sys.stderr)
        return 1

    fd = os.open(args.hidraw, os.O_RDONLY | os.O_NONBLOCK)

    controls = [
        "A", "B", "X", "Y",
        "L1", "R1", "L2", "R2",
        "L3", "R3",
        "L4", "R4", "L5", "R5",
        "DPAD_UP", "DPAD_RIGHT", "DPAD_DOWN", "DPAD_LEFT",
        "MENU", "STEAM", "QAM",
        "LEFT_PAD_TOUCH", "RIGHT_PAD_TOUCH",
        "LEFT_PAD_PRESS", "RIGHT_PAD_PRESS",
    ]

    results: dict[str, dict] = {}

    try:
        prompt(f"Using {args.hidraw}. Keep controller connected.\n")
        for c in controls:
            prompt(f"Prepare to test: {c}")
            prompt("Release all controls.")
            wait_countdown(2)

            baseline = read_reports(fd, args.rest_seconds).samples
            prompt(f"HOLD {c} now")
            wait_countdown(1)
            hold = read_reports(fd, args.hold_seconds).samples

            prompt("Release")
            read_reports(fd, 0.4)

            analysis = analyze(baseline, hold)
            results[c] = {
                "baseline_samples": len(baseline),
                "hold_samples": len(hold),
                **analysis,
            }

            top_bit = analysis["bit_changes"][0] if analysis["bit_changes"] else None
            top_s16 = analysis["s16_changes"][0] if analysis["s16_changes"] else None
            print(f"[{c}] top_bit={top_bit} top_s16={top_s16}", flush=True)
            print("-" * 60, flush=True)

    finally:
        os.close(fd)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"Saved calibration: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
