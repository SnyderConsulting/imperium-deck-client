from __future__ import annotations

import asyncio
import base64
import glob
import io
import json
import mimetypes
import os
import re
import select
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from evdev import InputDevice, categorize, ecodes

    EVDEV_AVAILABLE = True
    EVDEV_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - platform specific
    InputDevice = None  # type: ignore[assignment]
    categorize = None  # type: ignore[assignment]
    ecodes = None  # type: ignore[assignment]
    EVDEV_AVAILABLE = False
    EVDEV_IMPORT_ERROR = str(exc)

try:
    import numpy as np
    from PIL import Image

    IMAGE_DETECT_AVAILABLE = True
    IMAGE_DETECT_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - platform specific
    np = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    IMAGE_DETECT_AVAILABLE = False
    IMAGE_DETECT_IMPORT_ERROR = str(exc)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"
CMS_DIR = PROJECT_ROOT / "cms_projects"
CMS_DIR.mkdir(parents=True, exist_ok=True)
REMOTE_DECK_BASE_URL = os.environ.get("SDR_REMOTE_DECK_BASE_URL", "").strip().rstrip("/")
REMOTE_CMS_PROXY_ENABLED = bool(REMOTE_DECK_BASE_URL)
REMOTE_PROFILE_SOURCE_URL = (
    os.environ.get("SDR_PROFILE_SOURCE_URL", "https://www.imperium-gaming.com").strip().rstrip("/")
)
CONTROL_KEYS = {
    "A",
    "B",
    "X",
    "Y",
    "L1",
    "R1",
    "L2",
    "R2",
    "L3",
    "R3",
    "L4",
    "R4",
    "L5",
    "R5",
    "MENU",
    "STEAM",
    "QAM",
    "DPAD_UP",
    "DPAD_RIGHT",
    "DPAD_DOWN",
    "DPAD_LEFT",
}


def _http_json(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method.upper(),
    )
    try:
        with urlrequest.urlopen(req, timeout=max(1.0, timeout)) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = str(exc)
        raise HTTPException(status_code=502, detail=f"Remote Deck HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Remote Deck request failed: {exc}") from exc
    if not isinstance(out, dict):
        raise HTTPException(status_code=502, detail=f"Remote Deck returned non-JSON object: {type(out).__name__}")
    return out


async def _remote_api_get(path: str, timeout: float = 8.0) -> dict[str, Any]:
    if not REMOTE_CMS_PROXY_ENABLED:
        raise HTTPException(status_code=500, detail="Remote Deck mode not enabled")
    return await asyncio.to_thread(_http_json, "GET", f"{REMOTE_DECK_BASE_URL}{path}", None, timeout)


async def _remote_api_post(path: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    if not REMOTE_CMS_PROXY_ENABLED:
        raise HTTPException(status_code=500, detail="Remote Deck mode not enabled")
    return await asyncio.to_thread(_http_json, "POST", f"{REMOTE_DECK_BASE_URL}{path}", payload, timeout)


async def _remote_profile_get(path: str, timeout: float = 8.0) -> dict[str, Any]:
    if not REMOTE_PROFILE_SOURCE_URL:
        raise HTTPException(status_code=400, detail="Profile source URL is not configured")
    return await asyncio.to_thread(_http_json, "GET", f"{REMOTE_PROFILE_SOURCE_URL}{path}", None, timeout)


class StartRequest(BaseModel):
    device_paths: list[str] = Field(default_factory=list)


class CmsProjectWrite(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class CmsCaptureRequest(BaseModel):
    interactive: bool = False
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)


class CmsSceneLearnRequest(BaseModel):
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)


class CmsDetectSceneRequest(BaseModel):
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)


class CmsSyncPullRequest(BaseModel):
    apply: bool = True


@dataclass
class InputState:
    buttons: dict[str, int] = field(default_factory=dict)
    axes: dict[str, int] = field(default_factory=dict)
    misc: dict[str, int] = field(default_factory=dict)
    hits: dict[str, int] = field(default_factory=dict)


def _canonical_control_key(raw: str) -> str:
    key = str(raw or "").strip().upper()
    aliases = {
        "KEY_304": "A",
        "KEY_305": "B",
        "KEY_307": "X",
        "KEY_308": "Y",
        "KEY_310": "L1",
        "KEY_311": "R1",
        "KEY_312": "L2",
        "KEY_313": "R2",
        "KEY_314": "QAM",
        "KEY_315": "MENU",
        "KEY_316": "STEAM",
        "KEY_317": "L3",
        "KEY_318": "R3",
        "KEY_544": "DPAD_UP",
        "KEY_545": "DPAD_DOWN",
        "KEY_546": "DPAD_LEFT",
        "KEY_547": "DPAD_RIGHT",
        "BTN_SOUTH": "A",
        "BTN_EAST": "B",
        "BTN_NORTH": "X",
        "BTN_WEST": "Y",
        "BTN_TL": "L1",
        "BTN_TR": "R1",
        "BTN_TL2": "L2",
        "BTN_TR2": "R2",
        "R2_BTN": "R2",
        "L2_BTN": "L2",
        "BTN_THUMBL": "L3",
        "BTN_THUMBR": "R3",
        "BTN_DPAD_UP": "DPAD_UP",
        "BTN_DPAD_RIGHT": "DPAD_RIGHT",
        "BTN_DPAD_DOWN": "DPAD_DOWN",
        "BTN_DPAD_LEFT": "DPAD_LEFT",
    }
    return aliases.get(key, key)


def _normalize_emit_key(raw: str) -> str:
    key = str(raw or "").strip()
    upper = key.upper()
    aliases = {
        "ESC": "Escape",
        "ENTER": "Return",
        "TAB": "Tab",
        "SPACE": "space",
        "BACKSPACE": "BackSpace",
        "LEFT": "Left",
        "RIGHT": "Right",
        "UP": "Up",
        "DOWN": "Down",
    }
    if upper in aliases:
        return aliases[upper]
    if len(key) == 1 and key.isalpha():
        return key.lower()
    return key


class RemapEngine:
    def __init__(self) -> None:
        self.active_project_id = ""
        self.active_scene_id = ""
        self.remap_rules: dict[str, str] = {}
        self.click_rules: dict[str, dict[str, Any]] = {}
        self.nav_dpad_edges: dict[str, dict[str, str]] = {}
        self.nav_linear: dict[str, dict[str, Any]] = {}
        self.nav_points: dict[str, dict[str, Any]] = {}
        self.nav_point_order: list[str] = []
        self.nav_tracked_keys: set[str] = set()
        self.nav_state: dict[str, Any] = {"dpad_current": "", "TRIGGERS_idx": None, "BUMPERS_idx": None}
        self.cursor_move_bias_x = float(os.environ.get("SDR_DPAD_CURSOR_BIAS_X", "0.02"))
        self.cursor_move_bias_y = float(os.environ.get("SDR_DPAD_CURSOR_BIAS_Y", "-0.02"))
        self._pressed: dict[str, int] = {}
        self._last_trigger: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.last_error = ""

    async def apply_project(self, project_id: str, data: dict[str, Any]) -> None:
        remap_rules: dict[str, str] = {}
        click_rules: dict[str, dict[str, Any]] = {}
        nav_dpad_edges: dict[str, dict[str, str]] = {}
        nav_linear: dict[str, dict[str, Any]] = {}
        nav_tracked_keys: set[str] = set()
        active_scene_id = str(data.get("active_scene_id", "")).strip()

        points_source = data.get("points", []) or []
        click_rules_source = data.get("click_point_rules", []) or []
        nav_groups_source = []
        scenes = data.get("scenes", []) or []
        if active_scene_id and isinstance(scenes, list):
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                if str(scene.get("id", "")).strip() != active_scene_id:
                    continue
                if isinstance(scene.get("points"), list):
                    points_source = scene.get("points", []) or []
                if isinstance(scene.get("click_point_rules"), list):
                    click_rules_source = scene.get("click_point_rules", []) or []
                if isinstance(scene.get("nav_groups"), list):
                    nav_groups_source = scene.get("nav_groups", []) or []
                break

        points_by_id: dict[str, dict[str, Any]] = {}
        point_order: list[str] = []
        for p in points_source:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id", "")).strip()
            try:
                x = float(p.get("x", 0))
                y = float(p.get("y", 0))
            except Exception:
                continue
            if not pid:
                continue
            points_by_id[pid] = {"x": max(0.0, min(1.0, x)), "y": max(0.0, min(1.0, y))}
            point_order.append(pid)

        for r in data.get("remap_key_rules", []) or []:
            if not isinstance(r, dict):
                continue
            from_key = _canonical_control_key(str(r.get("from_key", "")).strip())
            to_key = _normalize_emit_key(str(r.get("to_key", "")).strip())
            if from_key in CONTROL_KEYS and to_key:
                remap_rules[from_key] = to_key

        for r in click_rules_source:
            if not isinstance(r, dict):
                continue
            on_key = _canonical_control_key(str(r.get("on_key", "")).strip())
            point_id = str(r.get("point_id", "")).strip()
            point = points_by_id.get(point_id)
            if on_key in CONTROL_KEYS and point is not None:
                click_rules[on_key] = {
                    "point_id": point_id,
                    "x": float(point["x"]),
                    "y": float(point["y"]),
                    "button": str(r.get("button", "left")).lower() or "left",
                }

        if isinstance(nav_groups_source, list):
            for group in nav_groups_source:
                if not isinstance(group, dict):
                    continue
                kind = str(group.get("kind", "")).strip().upper()
                if kind == "D_PAD" and not nav_dpad_edges:
                    edges_in = group.get("edges")
                    if isinstance(edges_in, dict):
                        out: dict[str, dict[str, str]] = {}
                        for node_id, edge in edges_in.items():
                            nid = str(node_id).strip()
                            if nid not in points_by_id or not isinstance(edge, dict):
                                continue
                            out[nid] = {
                                "up": str(edge.get("up", "")).strip(),
                                "down": str(edge.get("down", "")).strip(),
                                "left": str(edge.get("left", "")).strip(),
                                "right": str(edge.get("right", "")).strip(),
                            }
                        nav_dpad_edges = out
                elif kind in ("TRIGGERS", "BUMPERS") and kind not in nav_linear:
                    order_in = group.get("order")
                    order: list[str] = []
                    if isinstance(order_in, list):
                        for node_id in order_in:
                            nid = str(node_id).strip()
                            if nid and nid in points_by_id and nid not in order:
                                order.append(nid)
                    nav_linear[kind] = {
                        "order": order,
                        "cycle": bool(group.get("cycle", False)),
                    }

        if nav_dpad_edges:
            nav_tracked_keys.update({"DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"})
        if "TRIGGERS" in nav_linear:
            nav_tracked_keys.update({"L2", "R2"})
        if "BUMPERS" in nav_linear:
            nav_tracked_keys.update({"L1", "R1"})

        async with self._lock:
            prev_nav_state = dict(self.nav_state)
            self.active_project_id = project_id
            self.active_scene_id = active_scene_id
            self.remap_rules = remap_rules
            self.click_rules = click_rules
            self.nav_dpad_edges = nav_dpad_edges
            self.nav_linear = nav_linear
            self.nav_points = points_by_id
            self.nav_point_order = point_order
            self.nav_tracked_keys = nav_tracked_keys

            dpad_current = str(prev_nav_state.get("dpad_current", "") or "")
            if dpad_current not in points_by_id:
                dpad_current = point_order[0] if point_order else ""
            trig_idx = prev_nav_state.get("TRIGGERS_idx")
            bump_idx = prev_nav_state.get("BUMPERS_idx")
            trig_order = nav_linear.get("TRIGGERS", {}).get("order", [])
            bump_order = nav_linear.get("BUMPERS", {}).get("order", [])
            if not isinstance(trig_idx, int) or trig_idx < 0 or trig_idx >= len(trig_order):
                trig_idx = None
            if not isinstance(bump_idx, int) or bump_idx < 0 or bump_idx >= len(bump_order):
                bump_idx = None
            self.nav_state = {
                "dpad_current": dpad_current,
                "TRIGGERS_idx": trig_idx,
                "BUMPERS_idx": bump_idx,
            }

            tracked = set(remap_rules.keys()) | set(click_rules.keys()) | set(nav_tracked_keys)
            self._pressed = {k: self._pressed.get(k, 0) for k in tracked}
            self._last_trigger = {k: self._last_trigger.get(k, 0.0) for k in tracked}
            self.last_error = ""

    async def process(self, state_by_device: dict[str, InputState]) -> None:
        async with self._lock:
            tracked = set(self.remap_rules.keys()) | set(self.click_rules.keys()) | set(self.nav_tracked_keys)
            if not tracked:
                return
            remap_snapshot = dict(self.remap_rules)
            click_snapshot = dict(self.click_rules)
            nav_dpad_edges = dict(self.nav_dpad_edges)
            nav_linear = dict(self.nav_linear)
            nav_points = dict(self.nav_points)
            nav_point_order = list(self.nav_point_order)
            nav_state = dict(self.nav_state)
            pressed_snapshot = dict(self._pressed)
            trigger_snapshot = dict(self._last_trigger)

        aggregated = {k: 0 for k in tracked}
        for dev_state in state_by_device.values():
            for raw_key, raw_value in dev_state.buttons.items():
                key = _canonical_control_key(raw_key)
                if key in aggregated and int(raw_value) == 1:
                    aggregated[key] = 1

        now = time.time()
        actions: list[tuple[str, dict[str, Any] | str]] = []

        def _step_linear(kind: str, direction: int) -> None:
            cfg = nav_linear.get(kind)
            if not isinstance(cfg, dict):
                return
            order = cfg.get("order")
            if not isinstance(order, list) or not order:
                return
            idx_key = f"{kind}_idx"
            idx = nav_state.get(idx_key)
            idx_int = int(idx) if isinstance(idx, int) else None
            if idx_int is None or idx_int < 0 or idx_int >= len(order):
                next_idx = 0 if direction > 0 else (len(order) - 1)
            else:
                next_idx = idx_int + direction
                if next_idx < 0 or next_idx >= len(order):
                    if bool(cfg.get("cycle", False)):
                        next_idx = next_idx % len(order)
                    else:
                        return
            target_id = str(order[next_idx]).strip()
            point = nav_points.get(target_id)
            if point is None:
                return
            nav_state[idx_key] = next_idx
            actions.append(
                (
                    "click",
                    {
                        "point_id": target_id,
                        "x": float(point["x"]),
                        "y": float(point["y"]),
                        "button": "left",
                    },
                )
            )

        for key in tracked:
            curr = int(aggregated.get(key, 0))
            prev = int(pressed_snapshot.get(key, 0))
            if curr == 1 and prev != 1:
                last_ts = float(trigger_snapshot.get(key, 0.0))
                if now - last_ts >= 0.05:
                    if key in remap_snapshot:
                        actions.append(("remap", remap_snapshot[key]))
                    if key in click_snapshot:
                        actions.append(("click", click_snapshot[key]))

                    if key in ("DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT") and nav_dpad_edges:
                        direction = {
                            "DPAD_UP": "up",
                            "DPAD_DOWN": "down",
                            "DPAD_LEFT": "left",
                            "DPAD_RIGHT": "right",
                        }[key]
                        current = str(nav_state.get("dpad_current", "") or "")
                        if current not in nav_points:
                            current = nav_point_order[0] if nav_point_order else ""
                        next_id = ""
                        if current:
                            edge = nav_dpad_edges.get(current, {})
                            cand = str(edge.get(direction, "")).strip()
                            if cand in nav_points:
                                next_id = cand
                        if next_id:
                            nav_state["dpad_current"] = next_id
                            point = nav_points[next_id]
                            mx = max(0.0, min(1.0, float(point["x"]) + float(self.cursor_move_bias_x)))
                            my = max(0.0, min(1.0, float(point["y"]) + float(self.cursor_move_bias_y)))
                            actions.append(
                                (
                                    "move",
                                    {
                                        "point_id": next_id,
                                        "x": mx,
                                        "y": my,
                                    },
                                )
                            )
                    elif key == "R2":
                        _step_linear("TRIGGERS", 1)
                    elif key == "L2":
                        _step_linear("TRIGGERS", -1)
                    elif key == "R1":
                        _step_linear("BUMPERS", 1)
                    elif key == "L1":
                        _step_linear("BUMPERS", -1)

                    trigger_snapshot[key] = now
            pressed_snapshot[key] = curr

        async with self._lock:
            self._pressed = pressed_snapshot
            self._last_trigger = trigger_snapshot
            self.nav_state = nav_state

        for kind, payload in actions:
            if kind == "remap":
                asyncio.create_task(self._emit_key(str(payload)))
            elif kind == "click":
                asyncio.create_task(self._emit_click(dict(payload)))
            elif kind == "move":
                asyncio.create_task(self._emit_move(dict(payload)))

    async def status(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "active_project_id": self.active_project_id,
                "active_scene_id": self.active_scene_id,
                "remap_rule_count": len(self.remap_rules),
                "click_rule_count": len(self.click_rules),
                "nav_group_count": int(bool(self.nav_dpad_edges)) + int("TRIGGERS" in self.nav_linear) + int("BUMPERS" in self.nav_linear),
                "nav_enabled": bool(self.nav_dpad_edges or self.nav_linear),
                "tracked_keys": sorted(set(self.remap_rules.keys()) | set(self.click_rules.keys()) | set(self.nav_tracked_keys)),
                "last_error": self.last_error,
            }

    async def _emit_key(self, key: str) -> None:
        try:
            await self._helper_emit("/emit/key", {"key": key})
        except Exception as exc:
            await self._set_error(f"emit key failed: {exc}")

    async def _emit_click(self, rule: dict[str, Any]) -> None:
        try:
            await self._helper_emit(
                "/emit/click",
                {
                    "x": float(rule.get("x", 0.0)),
                    "y": float(rule.get("y", 0.0)),
                    "button": str(rule.get("button", "left")).lower(),
                },
            )
        except Exception as exc:
            await self._set_error(f"emit click failed: {exc}")

    async def _emit_move(self, rule: dict[str, Any]) -> None:
        try:
            await self._helper_emit(
                "/emit/move",
                {
                    "x": float(rule.get("x", 0.0)),
                    "y": float(rule.get("y", 0.0)),
                },
            )
        except Exception as exc:
            await self._set_error(f"emit move failed: {exc}")

    async def _helper_emit(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        def call_helper() -> dict[str, Any]:
            req = urlrequest.Request(
                f"http://127.0.0.1:18765{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlrequest.urlopen(req, timeout=3.0) as resp:
                    out = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                raise RuntimeError(f"helper request failed: {exc}") from exc
            if not isinstance(out, dict) or not out.get("ok"):
                raise RuntimeError(f"helper error: {out}")
            return out

        return await asyncio.to_thread(call_helper)

    async def _set_error(self, text: str) -> None:
        async with self._lock:
            self.last_error = text


class EventHub:
    def __init__(self, remapper: RemapEngine | None = None) -> None:
        self.ws_clients: set[WebSocket] = set()
        self.state_by_device: dict[str, InputState] = {}
        self.event_count = 0
        self._lock = asyncio.Lock()
        self._hid_button_filter: dict[str, dict[str, dict[str, int]]] = {}
        self.remapper = remapper

    async def add_client(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.ws_clients.add(ws)

    async def remove_client(self, ws: WebSocket) -> None:
        async with self._lock:
            self.ws_clients.discard(ws)

    async def publish(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("event_type_name", "")
        code_name = payload.get("code_name", "")
        value = int(payload.get("value", 0))
        device_path = str(payload.get("device_path", "unknown"))

        state = self.state_by_device.setdefault(device_path, InputState())
        if event_type == "EV_KEY":
            self._set_button(state, code_name, value)
        elif event_type == "EV_ABS":
            state.axes[code_name] = value
            self._apply_hat_to_dpad(state, code_name, value)
        elif event_type == "HIDRAW":
            decoded = payload.get("decoded") or {}
            if isinstance(decoded, dict):
                for k, v in decoded.items():
                    if k.endswith("_X") or k.endswith("_Y"):
                        state.axes[str(k)] = int(v)
                    elif "PAD_" in str(k) or "STICK_" in str(k):
                        if str(k).endswith("_PRESS") or str(k).endswith("_TOUCH"):
                            self._set_hid_button_filtered(device_path, state, str(k), int(v))
                        else:
                            state.axes[str(k)] = int(v)
                    else:
                        self._set_hid_button_filtered(device_path, state, str(k), int(v))
        else:
            state.misc[code_name] = value

        if self.remapper is not None:
            await self.remapper.process(self.state_by_device)

        self.event_count += 1

        text = json.dumps(payload)
        async with self._lock:
            clients = list(self.ws_clients)

        stale: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_text(text)
            except Exception:
                stale.append(client)

        if stale:
            async with self._lock:
                for client in stale:
                    self.ws_clients.discard(client)

    def _set_button(self, state: InputState, key: str, value: int) -> None:
        prev = int(state.buttons.get(key, 0))
        state.buttons[key] = int(value)
        if int(value) == 1 and prev != 1:
            state.hits[key] = state.hits.get(key, 0) + 1

    def _set_hid_button_filtered(self, device_path: str, state: InputState, key: str, value: int) -> None:
        per_device = self._hid_button_filter.setdefault(device_path, {})
        filt = per_device.get(key)
        if filt is None:
            filt = {"last_raw": int(value), "count": 1, "emitted": int(state.buttons.get(key, 0))}
            per_device[key] = filt
        else:
            if int(value) == int(filt["last_raw"]):
                filt["count"] = int(filt["count"]) + 1
            else:
                filt["last_raw"] = int(value)
                filt["count"] = 1

        # Require a tiny amount of temporal consistency to suppress single-packet flaps.
        if int(filt["count"]) >= 2 and int(filt["emitted"]) != int(value):
            prev = int(filt["emitted"])
            filt["emitted"] = int(value)
            state.buttons[key] = int(value)
            if int(value) == 1 and prev != 1:
                state.hits[key] = state.hits.get(key, 0) + 1

    def _apply_hat_to_dpad(self, state: InputState, code_name: str, value: int) -> None:
        if code_name == "ABS_HAT0X":
            self._set_button(state, "DPAD_LEFT", 1 if value < 0 else 0)
            self._set_button(state, "DPAD_RIGHT", 1 if value > 0 else 0)
        elif code_name == "ABS_HAT0Y":
            self._set_button(state, "DPAD_UP", 1 if value < 0 else 0)
            self._set_button(state, "DPAD_DOWN", 1 if value > 0 else 0)


class InputManager:
    def __init__(self, hub: EventHub) -> None:
        self.hub = hub
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()
        self.exclusive_grab = True
        self.last_warnings: list[str] = []
        self._hidraw_last_state: dict[str, dict[str, int]] = {}

    async def stop(self) -> None:
        self._stop_event.set()
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._stop_event = asyncio.Event()

    async def start(self, device_paths: list[str]) -> None:
        if not EVDEV_AVAILABLE:
            raise HTTPException(
                status_code=500,
                detail=f"evdev unavailable on this platform: {EVDEV_IMPORT_ERROR}",
            )
        await self.stop()

        if not device_paths:
            device_paths = default_device_paths()

        invalid = [p for p in device_paths if not Path(p).exists()]
        valid = [p for p in device_paths if Path(p).exists()]
        if invalid:
            self.last_warnings = [f"Missing devices ignored: {invalid}"]
        else:
            self.last_warnings = []
        if not valid:
            raise HTTPException(status_code=400, detail=f"Missing devices: {invalid}")

        for path in valid:
            if path.startswith("/dev/hidraw"):
                task = asyncio.create_task(self._read_hidraw(path), name=f"read:{path}")
            else:
                task = asyncio.create_task(self._read_device(path), name=f"read:{path}")
            self._tasks[path] = task

    async def _read_device(self, path: str) -> None:
        if InputDevice is None or ecodes is None:
            return
        device = InputDevice(path)
        device_name = device.name
        device_phys = device.phys
        grabbed = False
        try:
            if self.exclusive_grab:
                try:
                    device.grab()
                    grabbed = True
                except Exception as exc:
                    await self.hub.publish(
                        {
                            "timestamp": time.time(),
                            "device_path": path,
                            "device_name": device_name,
                            "event_type_name": "WARN",
                            "code_name": "grab_failed",
                            "value": 1,
                            "text": str(exc),
                        }
                    )
            async for event in device.async_read_loop():
                if self._stop_event.is_set():
                    break

                type_name = ecodes.EV.get(event.type, f"EV_{event.type}")
                code_name = _code_name(event.type, event.code)
                payload: dict[str, Any] = {
                    "timestamp": time.time(),
                    "device_path": path,
                    "device_name": device_name,
                    "device_phys": device_phys,
                    "event_type": event.type,
                    "event_type_name": type_name,
                    "code": event.code,
                    "code_name": code_name,
                    "value": event.value,
                }

                try:
                    interpreted = categorize(event) if categorize is not None else ""
                    payload["text"] = str(interpreted)
                except Exception:
                    payload["text"] = ""

                await self.hub.publish(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.hub.publish(
                {
                    "timestamp": time.time(),
                    "device_path": path,
                    "device_name": device_name,
                    "event_type_name": "ERROR",
                    "code_name": "read_error",
                    "value": 1,
                    "text": str(exc),
                }
            )
        finally:
            if grabbed:
                try:
                    device.ungrab()
                except Exception:
                    pass
            device.close()

    async def _read_hidraw(self, path: str) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        packet_counter = 0
        try:
            while not self._stop_event.is_set():
                ready = await asyncio.to_thread(select.select, [fd], [], [], 0.2)
                if not ready[0]:
                    continue
                try:
                    data = os.read(fd, 256)
                except BlockingIOError:
                    continue
                if not data:
                    continue
                report_id = data[0] if data else 0
                packet_counter += 1
                decoded = decode_steamdeck_hid_report(data)
                prev = self._hidraw_last_state.get(path, {})
                changed = {k: v for k, v in decoded.items() if prev.get(k) != v}
                if changed:
                    self._hidraw_last_state[path] = dict(decoded)
                payload: dict[str, Any] = {
                    "timestamp": time.time(),
                    "device_path": path,
                    "device_name": "hidraw",
                    "event_type_name": "HIDRAW",
                    "code_name": f"REPORT_{report_id:02x}",
                    "value": len(data),
                    "text": data.hex(),
                    "decoded": changed,
                    "packet_counter": packet_counter,
                }
                if changed or packet_counter % 120 == 0:
                    await self.hub.publish(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.hub.publish(
                {
                    "timestamp": time.time(),
                    "device_path": path,
                    "device_name": "hidraw",
                    "event_type_name": "ERROR",
                    "code_name": "read_error",
                    "value": 1,
                    "text": str(exc),
                }
            )
        finally:
            try:
                os.close(fd)
            except Exception:
                pass

    def active_devices(self) -> list[str]:
        return sorted(self._tasks.keys())


def _code_name(ev_type: int, code: int) -> str:
    if ecodes is None:
        return str(code)
    try:
        if ev_type == ecodes.EV_KEY:
            key_name = ecodes.KEY.get(code, f"KEY_{code}")
            if key_name == "BTN_DPAD_UP":
                return "DPAD_UP"
            if key_name == "BTN_DPAD_RIGHT":
                return "DPAD_RIGHT"
            if key_name == "BTN_DPAD_DOWN":
                return "DPAD_DOWN"
            if key_name == "BTN_DPAD_LEFT":
                return "DPAD_LEFT"
            return key_name
        if ev_type == ecodes.EV_ABS:
            return ecodes.ABS.get(code, f"ABS_{code}")
        if ev_type == ecodes.EV_REL:
            return ecodes.REL.get(code, f"REL_{code}")
        if ev_type == ecodes.EV_MSC:
            return ecodes.MSC.get(code, f"MSC_{code}")
    except Exception:
        pass
    return str(code)


def discover_devices() -> list[dict[str, Any]]:
    if not EVDEV_AVAILABLE:
        return [{"error": f"evdev unavailable: {EVDEV_IMPORT_ERROR}"}]

    devices: list[dict[str, Any]] = []
    for path in sorted(Path("/dev/input").glob("event*")):
        try:
            dev = InputDevice(str(path))
            caps = dev.capabilities(verbose=True)
            cap_names: list[str] = []
            for key in caps.keys():
                if isinstance(key, tuple):
                    cap_names.append(str(key[0]))
                else:
                    cap_names.append(str(key))
            devices.append(
                {
                    "path": str(path),
                    "name": dev.name,
                    "phys": dev.phys,
                    "uniq": dev.uniq,
                    "capabilities": sorted(set(cap_names)),
                }
            )
            dev.close()
        except Exception as exc:
            devices.append({"path": str(path), "error": str(exc)})
    devices.extend(discover_hidraw())
    return devices


def discover_hidraw() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        dev = p.name
        dev_path = f"/dev/{dev}"
        uevent = p / "device" / "uevent"
        props: dict[str, str] = {}
        try:
            for line in uevent.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v
        except Exception:
            continue
        out.append(
            {
                "path": dev_path,
                "name": props.get("HID_NAME", "hidraw"),
                "phys": props.get("HID_PHYS", ""),
                "uniq": props.get("HID_UNIQ", ""),
                "capabilities": ["HIDRAW"],
                "hid_id": props.get("HID_ID", ""),
                "driver": props.get("DRIVER", ""),
            }
        )
    return out


def default_device_paths() -> list[str]:
    if not EVDEV_AVAILABLE:
        return []

    preferred: list[str] = []
    virtual: list[str] = []
    for dev in discover_devices():
        name = str(dev.get("name", ""))
        path = dev.get("path")
        if not path:
            continue
        if "Steam Deck Motion Sensors" in name:
            preferred.append(str(path))
        elif name == "Steam Deck":
            preferred.append(str(path))
        elif "Valve Software Steam Deck Controller" in name:
            preferred.append(str(path))
        elif "x-box 360 pad" in name.lower() or (
            "pad" in name.lower() and "EV_ABS" in [str(c) for c in dev.get("capabilities", [])]
        ):
            virtual.append(str(path))
    if preferred:
        hid = default_hidraw_paths()
        return preferred + virtual + hid

    fallback = [d["path"] for d in discover_devices() if "path" in d]
    return fallback[:4]


def default_hidraw_paths() -> list[str]:
    preferred: list[str] = []
    others: list[str] = []
    for d in discover_hidraw():
        hid_id = str(d.get("hid_id", ""))
        phys = str(d.get("phys", ""))
        p = str(d.get("path", ""))
        if "000028DE:00001205" not in hid_id:
            continue
        if phys.endswith("input2"):
            preferred.append(p)
        else:
            others.append(p)
    return preferred + others[:1]


def decode_steamdeck_hid_report(data: bytes) -> dict[str, int]:
    if len(data) < 56:
        return {}

    out: dict[str, int] = {}
    b8 = data[8]
    out["R2_BTN"] = int(bool(b8 & (1 << 0)))
    out["L2_BTN"] = int(bool(b8 & (1 << 1)))
    out["R1"] = int(bool(b8 & (1 << 2)))
    out["L1"] = int(bool(b8 & (1 << 3)))
    out["Y"] = int(bool(b8 & (1 << 4)))
    out["B"] = int(bool(b8 & (1 << 5)))
    out["X"] = int(bool(b8 & (1 << 6)))
    out["A"] = int(bool(b8 & (1 << 7)))

    b9 = data[9]
    out["DPAD_UP"] = int(bool(b9 & (1 << 0)))
    out["DPAD_RIGHT"] = int(bool(b9 & (1 << 1)))
    out["DPAD_LEFT"] = int(bool(b9 & (1 << 2)))
    out["DPAD_DOWN"] = int(bool(b9 & (1 << 3)))
    out["QAM"] = int(bool(b9 & (1 << 4)))
    out["STEAM"] = int(bool(b9 & (1 << 5)))
    out["MENU"] = int(bool(b9 & (1 << 6)))
    out["L5"] = int(bool(b9 & (1 << 7)))

    b10 = data[10]
    out["R5"] = int(bool(b10 & (1 << 0)))
    out["LEFT_PAD_PRESS"] = int(bool(b10 & (1 << 1)))
    out["RIGHT_PAD_PRESS"] = int(bool(b10 & (1 << 2)))
    out["LEFT_PAD_TOUCH"] = int(bool(b10 & (1 << 3)))
    out["RIGHT_PAD_TOUCH"] = int(bool(b10 & (1 << 4)))
    out["L3"] = int(bool(b10 & (1 << 6)))

    b11 = data[11]
    out["R3"] = int(bool(b11 & (1 << 2)))

    b13 = data[13]
    out["L4"] = int(bool(b13 & (1 << 1)))
    out["R4"] = int(bool(b13 & (1 << 2)))
    out["LEFT_STICK_TOUCH"] = int(bool(b13 & (1 << 6)))
    out["RIGHT_STICK_TOUCH"] = int(bool(b13 & (1 << 7)))

    def s16(lo: int, hi: int) -> int:
        return struct.unpack("<h", data[lo:hi])[0]

    out["LEFT_PAD_X"] = s16(16, 18)
    out["LEFT_PAD_Y"] = s16(18, 20)
    out["RIGHT_PAD_X"] = s16(20, 22)
    out["RIGHT_PAD_Y"] = s16(22, 24)
    out["LEFT_STICK_X"] = s16(48, 50)
    out["LEFT_STICK_Y"] = s16(50, 52)
    out["RIGHT_STICK_X"] = s16(52, 54)
    out["RIGHT_STICK_Y"] = s16(54, 56)
    return out


app = FastAPI(title="Imperium Deck Client")
remapper = RemapEngine()
hub = EventHub(remapper=remapper)
manager = InputManager(hub)


@app.on_event("startup")
async def startup() -> None:
    if REMOTE_CMS_PROXY_ENABLED:
        return
    if EVDEV_AVAILABLE:
        await manager.start(default_device_paths())


@app.on_event("shutdown")
async def shutdown() -> None:
    await manager.stop()


@app.get("/api/devices")
async def api_devices() -> JSONResponse:
    return JSONResponse({"devices": discover_devices(), "default": default_device_paths()})


@app.get("/api/state")
async def api_state() -> JSONResponse:
    return JSONResponse(
        {
            "active_devices": manager.active_devices(),
            "event_count": hub.event_count,
            "exclusive_grab": manager.exclusive_grab,
            "warnings": manager.last_warnings,
            "state": {
                device: {
                    "buttons": data.buttons,
                    "axes": data.axes,
                    "misc": data.misc,
                    "hits": data.hits,
                }
                for device, data in hub.state_by_device.items()
            },
        }
    )


@app.post("/api/start")
async def api_start(req: StartRequest) -> JSONResponse:
    await manager.start(req.device_paths)
    return JSONResponse({"ok": True, "active_devices": manager.active_devices()})


@app.post("/api/stop")
async def api_stop() -> JSONResponse:
    await manager.stop()
    return JSONResponse({"ok": True})


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    await hub.add_client(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.remove_client(ws)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


def _cms_project_path(project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project id")
    return CMS_DIR / f"{project_id}.json"


async def _run_cmd(*args: str, timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Missing required command: {args[0]}") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"Timed out running: {' '.join(args)}")
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _portal_handle_from_gdbus(stdout: str) -> str:
    m = re.search(r"objectpath\s+'([^']+)'", stdout)
    if not m:
        raise HTTPException(status_code=500, detail=f"Portal did not return handle: {stdout.strip()}")
    return m.group(1)


async def _portal_interfaces(timeout_seconds: float) -> set[str]:
    rc, out, err = await _run_cmd(
        "gdbus",
        "introspect",
        "--session",
        "--dest",
        "org.freedesktop.portal.Desktop",
        "--object-path",
        "/org/freedesktop/portal/desktop",
        timeout=timeout_seconds,
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Portal introspection failed: {err.strip() or out.strip()}")
    return set(re.findall(r"interface ([A-Za-z0-9_.]+) \\{", out))


def _portal_uri_from_monitor(output: str) -> str:
    if "uint32 2" in output:
        raise HTTPException(status_code=409, detail="Portal screenshot request was canceled")
    if "uint32 1" in output:
        raise HTTPException(status_code=500, detail="Portal screenshot request failed")
    m = re.search(r'string "uri"\s+variant\s+string "([^"]+)"', output, re.MULTILINE)
    if not m:
        raise HTTPException(status_code=500, detail=f"Portal response missing uri: {output.strip()[:300]}")
    return m.group(1)


async def _capture_via_screenshot_portal(interactive: bool, timeout_seconds: float) -> dict[str, Any]:
    token = f"sdremap_{int(time.time() * 1000)}"
    options = f"{{'handle_token': <'{token}'>, 'interactive': <{str(bool(interactive)).lower()}>}}"
    rc, out, err = await _run_cmd(
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.portal.Desktop",
        "--object-path",
        "/org/freedesktop/portal/desktop",
        "--method",
        "org.freedesktop.portal.Screenshot.Screenshot",
        "",
        options,
        timeout=timeout_seconds,
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Portal call failed: {err.strip() or out.strip()}")

    handle = _portal_handle_from_gdbus(out)
    filter_arg = (
        f"type='signal',interface='org.freedesktop.portal.Request',"
        f"member='Response',path='{handle}'"
    )
    rc2, mon_out, mon_err = await _run_cmd(
        "dbus-monitor",
        "--session",
        filter_arg,
        timeout=timeout_seconds,
    )
    if rc2 != 0 and not mon_out:
        raise HTTPException(status_code=500, detail=f"Portal monitor failed: {mon_err.strip()}")

    uri = _portal_uri_from_monitor(mon_out)
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise HTTPException(status_code=500, detail=f"Unsupported screenshot URI scheme: {parsed.scheme}")
    path = Path(unquote(parsed.path))
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Screenshot file not found: {path}")

    return _read_image_result(path=path, provider="portal", extra={"uri": uri})


def _read_image_result(path: Path, provider: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    out: dict[str, Any] = {
        "ok": True,
        "provider": provider,
        "path": str(path),
        "mime_type": mime,
        "data_url": data_url,
        "bytes": len(raw),
    }
    if extra:
        out.update(extra)
    return out


def _latest_match(patterns: list[str], min_mtime: float) -> Path | None:
    newest: Path | None = None
    newest_mtime = min_mtime
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            path = Path(p)
            try:
                st = path.stat()
            except Exception:
                continue
            if st.st_mtime > newest_mtime:
                newest_mtime = st.st_mtime
                newest = path
    return newest


def _latest_gamescope_screenshot(min_mtime: float) -> Path | None:
    return _latest_match(
        patterns=[
        "/tmp/gamescope_*.png",
        "/tmp/*gamescope*.png",
        "/home/deck/Pictures/Screenshots/*.png",
        "/home/deck/Pictures/*.png",
        ],
        min_mtime=min_mtime,
    )


async def _trigger_gamescope_hotkey() -> None:
    xauth = "/home/deck/.Xauthority"
    for display in (":0", ":1"):
        env_prefix = ["env", f"DISPLAY={display}"]
        if Path(xauth).exists():
            env_prefix.append(f"XAUTHORITY={xauth}")
        await _run_cmd(
            *env_prefix,
            "xdotool",
            "key",
            "--clearmodifiers",
            "super+s",
            timeout=1.5,
        )


async def _capture_via_gamescope(timeout_seconds: float) -> dict[str, Any]:
    started = time.time()
    baseline = _latest_gamescope_screenshot(min_mtime=started - 1.0)
    baseline_path = str(baseline) if baseline else ""

    try:
        await _trigger_gamescope_hotkey()
    except Exception:
        pass

    deadline = time.time() + max(1.0, timeout_seconds)
    path: Path | None = None
    while time.time() < deadline:
        path = _latest_gamescope_screenshot(min_mtime=started)
        if path is not None and str(path) != baseline_path:
            break
        await asyncio.sleep(0.15)

    if path is None:
        raise HTTPException(
            status_code=500,
            detail="Gamescope screenshot was not created; Super+S capture unavailable in current session",
        )

    return _read_image_result(path=path, provider="gamescope")


def _steam_screenshot_patterns() -> list[str]:
    homes = ["/home/deck"]
    patterns: list[str] = []
    for home in homes:
        patterns.extend(
            [
                f"{home}/.steam/steam/userdata/*/760/remote/*/screenshots/*.png",
                f"{home}/.local/share/Steam/userdata/*/760/remote/*/screenshots/*.png",
                f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata/*/760/remote/*/screenshots/*.png",
                f"{home}/Pictures/Screenshots/*.png",
            ]
        )
    return patterns


def _latest_steam_screenshot(min_mtime: float) -> Path | None:
    return _latest_match(patterns=_steam_screenshot_patterns(), min_mtime=min_mtime)


async def _trigger_steam_screenshot_hotkey() -> None:
    xauth = "/home/deck/.Xauthority"
    for display in (":0", ":1"):
        env_prefix = ["env", f"DISPLAY={display}"]
        if Path(xauth).exists():
            env_prefix.append(f"XAUTHORITY={xauth}")
        await _run_cmd(
            *env_prefix,
            "xdotool",
            "key",
            "--clearmodifiers",
            "F12",
            timeout=1.5,
        )


async def _capture_via_steam_screenshot(timeout_seconds: float) -> dict[str, Any]:
    started = time.time()
    baseline = _latest_steam_screenshot(min_mtime=started - 1.0)
    baseline_path = str(baseline) if baseline else ""

    try:
        await _trigger_steam_screenshot_hotkey()
    except Exception:
        pass

    deadline = time.time() + max(1.0, timeout_seconds)
    path: Path | None = None
    while time.time() < deadline:
        path = _latest_steam_screenshot(min_mtime=started)
        if path is not None and str(path) != baseline_path:
            break
        await asyncio.sleep(0.2)

    if path is None:
        raise HTTPException(
            status_code=500,
            detail="Steam screenshot file not detected; F12 capture unavailable in current session",
        )
    return _read_image_result(path=path, provider="steam")


async def _capture_via_kmsgrab_helper(timeout_seconds: float) -> dict[str, Any]:
    if REMOTE_CMS_PROXY_ENABLED:
        out = await _remote_api_post(
            "/api/cms/capture",
            {"interactive": False, "timeout_seconds": timeout_seconds},
            timeout=max(2.0, timeout_seconds + 2.0),
        )
        if not out.get("ok") and "data_url" not in out:
            raise HTTPException(status_code=502, detail=f"Remote Deck capture failed: {out}")
        return out

    def call_helper() -> dict[str, Any]:
        req = urlrequest.Request(
            "http://127.0.0.1:18765/capture",
            data=json.dumps({"timeout_seconds": timeout_seconds}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=max(2.0, timeout_seconds + 2.0)) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                body = str(exc)
            raise HTTPException(status_code=500, detail=f"kmsgrab helper HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"kmsgrab helper request failed: {exc}") from exc
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise HTTPException(status_code=500, detail=f"kmsgrab helper invalid response: {payload}")
        return payload

    return await asyncio.to_thread(call_helper)


def _decode_data_url_image(data_url: str) -> "Image.Image":
    if not IMAGE_DETECT_AVAILABLE or Image is None:
        raise HTTPException(status_code=500, detail=f"Image detection dependencies unavailable: {IMAGE_DETECT_IMPORT_ERROR}")
    if not data_url.startswith("data:"):
        raise HTTPException(status_code=500, detail="Capture data_url missing")
    comma = data_url.find(",")
    if comma < 0:
        raise HTTPException(status_code=500, detail="Capture data_url invalid")
    raw = base64.b64decode(data_url[comma + 1 :])
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _scene_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = data.get("scenes")
    return scenes if isinstance(scenes, list) else []


def _find_scene(data: dict[str, Any], scene_id: str) -> dict[str, Any]:
    for s in _scene_list(data):
        if isinstance(s, dict) and str(s.get("id", "")) == scene_id:
            return s
    raise HTTPException(status_code=404, detail="Scene not found")


def _dhash_hex(img: "Image.Image") -> str:
    if np is None:
        raise HTTPException(status_code=500, detail=f"numpy unavailable: {IMAGE_DETECT_IMPORT_ERROR}")
    gray = img.convert("L").resize((9, 8))
    arr = np.asarray(gray, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    bits = 0
    for i, b in enumerate(diff.flatten()):
        bits |= (1 if bool(b) else 0) << i
    return f"{bits:016x}"


def _hamming_similarity(hex_a: str, hex_b: str) -> float:
    try:
        a = int(hex_a, 16)
        b = int(hex_b, 16)
    except Exception:
        return 0.0
    x = a ^ b
    try:
        d = x.bit_count()
    except AttributeError:
        d = bin(x).count("1")
    return max(0.0, 1.0 - (d / 64.0))


def _hist_vec(img: "Image.Image", bins: int = 8) -> list[float]:
    if np is None:
        raise HTTPException(status_code=500, detail=f"numpy unavailable: {IMAGE_DETECT_IMPORT_ERROR}")
    arr = np.asarray(img, dtype=np.uint8)
    parts: list[np.ndarray[Any, Any]] = []
    for ch in range(3):
        hist, _ = np.histogram(arr[:, :, ch], bins=bins, range=(0, 256))
        parts.append(hist.astype(np.float64))
    vec = np.concatenate(parts)
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-12:
        return [0.0] * int(vec.shape[0])
    vec = vec / norm
    return [float(x) for x in vec.tolist()]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if np is None:
        return 0.0
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _scene_features(img: "Image.Image") -> dict[str, Any]:
    return {"dhash": _dhash_hex(img), "hist": _hist_vec(img, bins=8)}


def _scene_score(curr: dict[str, Any], ref: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    hash_sim = _hamming_similarity(str(curr.get("dhash", "")), str(ref.get("dhash", "")))
    hist_sim = _cosine_sim(list(curr.get("hist", [])), list(ref.get("hist", [])))
    score = (0.55 * hash_sim) + (0.45 * hist_sim)
    return score, {"hash_sim": hash_sim, "hist_sim": hist_sim, "score": score}


@app.get("/cms")
async def cms_index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/cms/projects")
async def cms_list_projects() -> JSONResponse:
    projects: list[dict[str, Any]] = []
    for p in sorted(CMS_DIR.glob("*.json")):
        try:
            st = p.stat()
            projects.append(
                {
                    "project_id": p.stem,
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                }
            )
        except Exception:
            continue
    return JSONResponse({"projects": projects})


@app.get("/api/sync/config")
async def sync_config() -> JSONResponse:
    return JSONResponse({"profile_source_url": REMOTE_PROFILE_SOURCE_URL})


@app.get("/api/sync/projects")
async def sync_list_projects() -> JSONResponse:
    try:
        out = await _remote_profile_get("/api/cms/projects", timeout=10.0)
    except HTTPException as exc:
        raise HTTPException(status_code=502, detail=f"Remote project list failed: {exc.detail}") from exc
    projects = out.get("projects", [])
    if not isinstance(projects, list):
        projects = []
    return JSONResponse({"projects": projects, "source": REMOTE_PROFILE_SOURCE_URL})


@app.post("/api/sync/projects/{project_id}/pull")
async def sync_pull_project(project_id: str, body: CmsSyncPullRequest) -> JSONResponse:
    path = _cms_project_path(project_id)
    try:
        out = await _remote_profile_get(f"/api/cms/projects/{project_id}", timeout=15.0)
    except HTTPException as exc:
        raise HTTPException(status_code=502, detail=f"Remote project pull failed: {exc.detail}") from exc
    data = out.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Remote project payload missing data object")

    data.setdefault("schema_version", 1)
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2))

    applied = False
    if body.apply:
        await remapper.apply_project(project_id=project_id, data=data)
        applied = True

    return JSONResponse(
        {
            "ok": True,
            "project_id": project_id,
            "saved_local": True,
            "applied": applied,
            "source": REMOTE_PROFILE_SOURCE_URL,
            "remapper": await remapper.status(),
        }
    )


@app.get("/api/cms/projects/{project_id}")
async def cms_get_project(project_id: str) -> JSONResponse:
    path = _cms_project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Project read failed: {exc}") from exc
    return JSONResponse({"project_id": project_id, "data": data})


@app.post("/api/cms/projects/{project_id}/scenes/{scene_id}/learn")
async def cms_learn_scene(project_id: str, scene_id: str, req: CmsSceneLearnRequest) -> JSONResponse:
    path = _cms_project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Project read failed: {exc}") from exc

    scene = _find_scene(data, scene_id)
    cap = await _capture_via_kmsgrab_helper(timeout_seconds=req.timeout_seconds)
    frame = _decode_data_url_image(str(cap.get("data_url", "")))
    img_w, img_h = frame.size
    scene["ref"] = _scene_features(frame)
    learned = 1

    path.write_text(json.dumps(data, indent=2))
    return JSONResponse(
        {
            "ok": True,
            "project_id": project_id,
            "scene_id": scene_id,
            "learned_areas": learned,
            "frame": {"width": img_w, "height": img_h, "provider": cap.get("provider", "")},
        }
    )


@app.post("/api/cms/projects/{project_id}/detect_scene")
async def cms_detect_scene(project_id: str, req: CmsDetectSceneRequest) -> JSONResponse:
    path = _cms_project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Project read failed: {exc}") from exc

    scenes = _scene_list(data)
    if not scenes:
        raise HTTPException(status_code=400, detail="No scenes configured")

    cap = await _capture_via_kmsgrab_helper(timeout_seconds=req.timeout_seconds)
    frame = _decode_data_url_image(str(cap.get("data_url", "")))
    img_w, img_h = frame.size

    frame_feat = _scene_features(frame)
    results: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("id", "")).strip()
        if not scene_id:
            continue
        ref = scene.get("ref")
        if not isinstance(ref, dict):
            continue
        scene_score, details = _scene_score(frame_feat, ref)
        scene_threshold = float(scene.get("scene_threshold", 0.78))
        is_match = bool(scene_score >= scene_threshold)
        out = {
            "scene_id": scene_id,
            "label": str(scene.get("label", scene_id)),
            "score": scene_score,
            "match_ratio": 1.0 if is_match else 0.0,
            "is_match": is_match,
            "area_count": 1,
            "areas": [
                {
                    "id": "full_frame",
                    "score": scene_score,
                    "threshold": scene_threshold,
                    "weight": 1.0,
                    "matched": is_match,
                    "details": details,
                }
            ],
        }
        results.append(out)
        if best is None or float(out["score"]) > float(best["score"]):
            best = out

    if best is None:
        raise HTTPException(status_code=400, detail="No learned scenes found (missing scene.ref)")

    active = best if bool(best.get("is_match")) else None
    return JSONResponse(
        {
            "ok": True,
            "project_id": project_id,
            "provider": cap.get("provider", ""),
            "frame": {"width": img_w, "height": img_h},
            "active_scene_id": (active or {}).get("scene_id"),
            "active_scene_label": (active or {}).get("label"),
            "best_scene": best,
            "scenes": sorted(results, key=lambda x: float(x.get("score", 0.0)), reverse=True),
        }
    )


@app.post("/api/cms/projects/{project_id}")
async def cms_save_project(project_id: str, body: CmsProjectWrite) -> JSONResponse:
    path = _cms_project_path(project_id)
    data = dict(body.data)
    data.setdefault("schema_version", 1)
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2))
    if REMOTE_CMS_PROXY_ENABLED:
        remote = await _remote_api_post(f"/api/cms/projects/{project_id}", {"data": data}, timeout=8.0)
        return JSONResponse(
            {
                "ok": True,
                "project_id": project_id,
                "applied": bool(remote.get("applied", True)),
                "remote_proxy": True,
                "remote": remote,
            }
        )
    await remapper.apply_project(project_id=project_id, data=data)
    remap_status = await remapper.status()
    return JSONResponse({"ok": True, "project_id": project_id, "applied": True, "remapper": remap_status})


@app.post("/api/cms/projects/{project_id}/apply")
async def cms_apply_project(project_id: str) -> JSONResponse:
    path = _cms_project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Project read failed: {exc}") from exc
    if REMOTE_CMS_PROXY_ENABLED:
        remote = await _remote_api_post(f"/api/cms/projects/{project_id}", {"data": data}, timeout=8.0)
        return JSONResponse(
            {
                "ok": True,
                "project_id": project_id,
                "applied": bool(remote.get("applied", True)),
                "remote_proxy": True,
                "remote": remote,
            }
        )
    await remapper.apply_project(project_id=project_id, data=data)
    remap_status = await remapper.status()
    return JSONResponse({"ok": True, "project_id": project_id, "applied": True, "remapper": remap_status})


@app.delete("/api/cms/projects/{project_id}")
async def cms_delete_project(project_id: str) -> JSONResponse:
    path = _cms_project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    path.unlink()
    return JSONResponse({"ok": True, "project_id": project_id})


@app.get("/api/cms/active_project")
async def cms_active_project() -> JSONResponse:
    if REMOTE_CMS_PROXY_ENABLED:
        remote = await _remote_api_get("/api/cms/active_project", timeout=5.0)
        return JSONResponse({"ok": True, "remote_proxy": True, "remote": remote})
    return JSONResponse({"ok": True, "remapper": await remapper.status()})


@app.post("/api/cms/capture")
async def cms_capture(req: CmsCaptureRequest) -> JSONResponse:
    if REMOTE_CMS_PROXY_ENABLED:
        remote = await _remote_api_post(
            "/api/cms/capture",
            {"interactive": req.interactive, "timeout_seconds": req.timeout_seconds},
            timeout=max(2.0, req.timeout_seconds + 2.0),
        )
        remote["remote_proxy"] = True
        return JSONResponse(remote)

    attempts: list[str] = []
    portal_ifaces: set[str] = set()

    try:
        result = await _capture_via_kmsgrab_helper(timeout_seconds=req.timeout_seconds)
        result["portal_interfaces"] = []
        return JSONResponse(result)
    except HTTPException as exc:
        attempts.append(f"kmsgrab_helper: {exc.detail}")

    try:
        portal_ifaces = await _portal_interfaces(timeout_seconds=min(req.timeout_seconds, 4.0))
    except HTTPException as exc:
        attempts.append(f"portal_introspect: {exc.detail}")

    if "org.freedesktop.portal.Screenshot" in portal_ifaces:
        try:
            result = await _capture_via_screenshot_portal(
                interactive=req.interactive,
                timeout_seconds=req.timeout_seconds,
            )
            result["portal_interfaces"] = sorted(portal_ifaces)
            return JSONResponse(result)
        except HTTPException as exc:
            attempts.append(f"screenshot_portal: {exc.detail}")
    else:
        attempts.append("screenshot_portal: interface unavailable")

    try:
        result = await _capture_via_steam_screenshot(timeout_seconds=req.timeout_seconds)
        result["portal_interfaces"] = sorted(portal_ifaces)
        if attempts:
            result["fallback_from"] = attempts
        return JSONResponse(result)
    except HTTPException as exc:
        attempts.append(f"steam_screenshot: {exc.detail}")

    try:
        result = await _capture_via_gamescope(timeout_seconds=req.timeout_seconds)
        result["portal_interfaces"] = sorted(portal_ifaces)
        if attempts:
            result["fallback_from"] = attempts
        return JSONResponse(result)
    except HTTPException as exc:
        attempts.append(f"gamescope: {exc.detail}")

    raise HTTPException(status_code=500, detail={"capture_failed": attempts, "portal_interfaces": sorted(portal_ifaces)})


app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")
