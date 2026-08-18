"""Instructor config and live overlay (rororosi / Fap Instructor task packs)."""
from __future__ import annotations

import json

ALL_TASKS = [
    "doubleStrokes",
    "halvedStrokes",
    "teasingStrokes",
    "accelerationCycles",
    "randomBeat",
    "randomStrokeSpeed",
    "redLightGreenLight",
    "clusterStrokes",
    "gripChallenge",
    "dominant",
    "nondominant",
    "headOnly",
    "shaftOnly",
    "overhandGrip",
    "bothHands",
    "handsOff",
    "bindCockBalls",
    "rubberBands",
    "ballSlaps",
    "squeezeBalls",
    "headPalming",
    "icyHot",
    "toothpaste",
    "breathPlay",
    "scratching",
    "flicking",
    "cbtIce",
    "clothespins",
    "precum",
    "buttplug",
    "rubNipples",
    "nipplesAndStroke",
]
TASK_SET = set(ALL_TASKS)
DEFAULT_TASKS = ["doubleStrokes", "halvedStrokes", "teasingStrokes", "dominant"]
MEDIA_KINDS = ["picture", "gif", "video"]
STYLES = {"dominant", "nondominant", "headOnly", "shaftOnly", "overhandGrip", "bothHands", "handsOff"}
DEFAULT_PACKS = {
    "speed": True,
    "edge": True,
    "grip": True,
    "hands_off": True,
    "cei": False,
    "anal": False,
}
PACK_TO_TASKS = {
    "speed": ["doubleStrokes", "halvedStrokes", "teasingStrokes", "randomStrokeSpeed", "accelerationCycles"],
    "edge": ["redLightGreenLight", "clusterStrokes"],
    "grip": ["gripChallenge"],
    "hands_off": ["handsOff"],
    "cei": ["precum"],
    "anal": ["buttplug"],
}

DEFAULT_CONFIG = {
    "locked": False,
    "duration_min": 5,
    "duration_max": 15,
    "warmup_min": 2,
    "slide_duration": 10,
    "action_frequency": 30,
    "stroke_min": 0.25,
    "stroke_max": 4.0,
    "bpm_min": 15,
    "bpm_max": 240,
    "orgasm": "permit",
    "finale_orgasm": 100,
    "finale_denied": 0,
    "finale_ruined": 0,
    "post_orgasm_torture": False,
    "pot_min": 10,
    "pot_max": 90,
    "ruins_min": 0,
    "ruins_max": 0,
    "edge_cooldown": 10,
    "ruin_cooldown": 20,
    "minimum_edges": 0,
    "edge_frequency": 10,
    "orgasms_min": 1,
    "orgasms_max": 1,
    "grip_adjustments": True,
    "initial_grip": 3,
    "default_style": "dominant",
    "media_kinds": list(MEDIA_KINDS),
    "tasks": list(DEFAULT_TASKS),
    "packs": dict(DEFAULT_PACKS),
    "playlists": [],
    "include_chat_vault": False,
}

DEFAULT_LIVE = {
    "paused": False,
    "red_light": False,
    "lock_input": False,
    "force_end": False,
    "mute": False,
    "session_id": "",
    "media_keys": [],
    "media_index": 0,
    "media_seq": 0,
    "media_until": 0,
    "beat_speed": 1.0,
    "playing": False,
    "sub_ready": False,
    "command": None,
    "command_event": None,
    "want_camera": False,
    "want_dom_camera": False,
    "camera_device_id": "",
    "cameras": [],
    "recording": "off",
    "beat_epoch_ms": 0,
}

ORGASM_MODES = {"deny", "ruin", "permit", "random"}


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _float(value, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def _tasks_from_packs(packs: dict) -> list[str]:
    out: list[str] = []
    for name, enabled in (packs or {}).items():
        if enabled:
            out.extend(PACK_TO_TASKS.get(name, []))
    seen: set[str] = set()
    uniq = []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq or list(DEFAULT_TASKS)


def parse_config(raw: str | None) -> dict:
    data = dict(DEFAULT_CONFIG)
    data["packs"] = dict(DEFAULT_PACKS)
    data["tasks"] = list(DEFAULT_TASKS)
    data["media_kinds"] = list(MEDIA_KINDS)
    try:
        parsed = json.loads(raw or "") if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        return data
    if isinstance(parsed.get("locked"), bool):
        data["locked"] = parsed["locked"]
    for key in (
        "duration_min",
        "duration_max",
        "warmup_min",
        "slide_duration",
        "action_frequency",
        "finale_orgasm",
        "finale_denied",
        "finale_ruined",
        "pot_min",
        "pot_max",
        "ruins_min",
        "ruins_max",
        "edge_cooldown",
        "ruin_cooldown",
        "minimum_edges",
        "edge_frequency",
        "orgasms_min",
        "orgasms_max",
        "initial_grip",
        "bpm_min",
        "bpm_max",
    ):
        if parsed.get(key) is not None:
            data[key] = parsed[key]
    for key in ("stroke_min", "stroke_max"):
        if parsed.get(key) is not None:
            data[key] = parsed[key]
    orgasm = str(parsed.get("orgasm") or data["orgasm"]).strip().lower()
    if orgasm in ORGASM_MODES:
        data["orgasm"] = orgasm
    style = str(parsed.get("default_style") or data["default_style"]).strip()
    if style in STYLES:
        data["default_style"] = style
    for key in ("grip_adjustments", "post_orgasm_torture", "include_chat_vault"):
        if isinstance(parsed.get(key), bool):
            data[key] = parsed[key]
    packs = parsed.get("packs")
    if isinstance(packs, dict):
        for name in DEFAULT_PACKS:
            if isinstance(packs.get(name), bool):
                data["packs"][name] = packs[name]
    tasks = parsed.get("tasks")
    if isinstance(tasks, list):
        data["tasks"] = [str(item) for item in tasks if str(item) in TASK_SET][:80]
    elif packs:
        data["tasks"] = _tasks_from_packs(data["packs"])
    kinds = parsed.get("media_kinds")
    if isinstance(kinds, list):
        data["media_kinds"] = [k for k in kinds if k in MEDIA_KINDS][:3] or list(MEDIA_KINDS)
    lists = parsed.get("playlists")
    if isinstance(lists, list):
        data["playlists"] = [str(item).strip() for item in lists if str(item).strip()][:80]

    data["duration_min"] = _int(data["duration_min"], 5, 1, 180)
    data["duration_max"] = _int(data.get("duration_max", data["duration_min"]), 15, data["duration_min"], 180)
    data["warmup_min"] = _int(data["warmup_min"], 2, 0, 30)
    data["slide_duration"] = _int(data["slide_duration"], 10, 3, 120)
    data["action_frequency"] = _int(data["action_frequency"], 30, 0, 600)
    data["edge_cooldown"] = _int(data["edge_cooldown"], 10, 0, 600)
    data["ruin_cooldown"] = _int(data["ruin_cooldown"], 20, 0, 600)
    data["minimum_edges"] = _int(data["minimum_edges"], 0, 0, 100)
    data["edge_frequency"] = _int(data["edge_frequency"], 10, 0, 100)
    data["ruins_min"] = _int(data["ruins_min"], 0, 0, 20)
    data["ruins_max"] = _int(data["ruins_max"], 0, data["ruins_min"], 20)
    data["pot_min"] = _int(data["pot_min"], 10, 0, 600)
    data["pot_max"] = _int(data["pot_max"], 90, data["pot_min"], 600)
    data["orgasms_min"] = _int(data["orgasms_min"], 1, 0, 10)
    data["orgasms_max"] = _int(data["orgasms_max"], 1, data["orgasms_min"], 10)
    data["initial_grip"] = _int(data["initial_grip"], 3, 0, 6)
    data["finale_orgasm"] = _int(data["finale_orgasm"], 100, 0, 100)
    data["finale_denied"] = _int(data["finale_denied"], 0, 0, 100)
    data["finale_ruined"] = _int(data["finale_ruined"], 0, 0, 100)
    finale_in_payload = any(key in parsed for key in ("finale_orgasm", "finale_denied", "finale_ruined"))
    if not finale_in_payload:
        if data["orgasm"] == "deny":
            data["finale_orgasm"], data["finale_denied"], data["finale_ruined"] = 0, 100, 0
        elif data["orgasm"] == "ruin":
            data["finale_orgasm"], data["finale_denied"], data["finale_ruined"] = 0, 0, 100
        elif data["orgasm"] == "permit":
            data["finale_orgasm"], data["finale_denied"], data["finale_ruined"] = 100, 0, 0
        elif data["orgasm"] == "random":
            data["finale_orgasm"], data["finale_denied"], data["finale_ruined"] = 34, 33, 33
    total = data["finale_orgasm"] + data["finale_denied"] + data["finale_ruined"]
    if total != 100 and finale_in_payload:
        # keep entered values scaled
        if total <= 0:
            data["finale_orgasm"], data["finale_denied"], data["finale_ruined"] = 100, 0, 0
        else:
            data["finale_orgasm"] = int(round(100 * data["finale_orgasm"] / total))
            data["finale_denied"] = int(round(100 * data["finale_denied"] / total))
            data["finale_ruined"] = max(0, 100 - data["finale_orgasm"] - data["finale_denied"])

    if parsed.get("stroke_min") is None and parsed.get("bpm_min") is not None:
        data["stroke_min"] = _int(parsed["bpm_min"], 40, 20, 200) / 60.0
    if parsed.get("stroke_max") is None and parsed.get("bpm_max") is not None:
        data["stroke_max"] = _int(parsed["bpm_max"], 120, 20, 240) / 60.0
    data["stroke_min"] = _float(data["stroke_min"], 0.25, 0.1, 8.0)
    data["stroke_max"] = _float(data["stroke_max"], 4.0, data["stroke_min"], 8.0)
    data["bpm_min"] = max(20, min(240, int(round(data["stroke_min"] * 60))))
    data["bpm_max"] = max(data["bpm_min"], min(240, int(round(data["stroke_max"] * 60))))
    return data


def parse_live(raw: str | None) -> dict:
    data = dict(DEFAULT_LIVE)
    data["media_keys"] = []
    data["cameras"] = []
    try:
        parsed = json.loads(raw or "") if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        return data
    for key in ("paused", "red_light", "lock_input", "force_end", "mute", "playing", "sub_ready"):
        if isinstance(parsed.get(key), bool):
            data[key] = parsed[key]
    if isinstance(parsed.get("session_id"), str):
        data["session_id"] = parsed["session_id"][:64]
    if isinstance(parsed.get("media_keys"), list):
        data["media_keys"] = [str(item)[:240] for item in parsed["media_keys"]][:500]
    for key in ("media_index", "media_seq", "media_until"):
        if parsed.get(key) is not None:
            data[key] = _int(parsed[key], data[key], 0, 10_000_000_000)
    if parsed.get("beat_speed") is not None:
        data["beat_speed"] = _float(parsed["beat_speed"], data["beat_speed"], 0.1, 8.0)
    cmd = parsed.get("command")
    if isinstance(cmd, dict) and cmd.get("type") in {"edge", "ruin"}:
        data["command"] = {
            "type": cmd["type"],
            "id": str(cmd.get("id") or "")[:64],
            "deadline_ms": _int(cmd.get("deadline_ms"), 0, 0, 10_000_000_000_000),
            "issued_ms": _int(cmd.get("issued_ms"), 0, 0, 10_000_000_000_000),
        }
    elif cmd is None:
        data["command"] = None
    evt = parsed.get("command_event")
    if isinstance(evt, dict) and evt.get("type") in {"completed", "failed", "timeout"}:
        data["command_event"] = {
            "type": evt["type"],
            "command_type": str(evt.get("command_type") or "")[:16],
            "at_ms": _int(evt.get("at_ms"), 0, 0, 10_000_000_000_000),
            "message": str(evt.get("message") or "")[:240],
        }
    elif evt is None:
        data["command_event"] = None
    if isinstance(parsed.get("want_camera"), bool):
        data["want_camera"] = parsed["want_camera"]
    if isinstance(parsed.get("want_dom_camera"), bool):
        data["want_dom_camera"] = parsed["want_dom_camera"]
    if isinstance(parsed.get("camera_device_id"), str):
        data["camera_device_id"] = parsed["camera_device_id"][:120]
    rec = str(parsed.get("recording") or "off").strip().lower()
    if rec in {"off", "sub", "domme", "both"}:
        data["recording"] = rec
    if parsed.get("beat_epoch_ms") is not None:
        data["beat_epoch_ms"] = _int(parsed["beat_epoch_ms"], 0, 0, 10_000_000_000_000)
    cams = parsed.get("cameras")
    if isinstance(cams, list):
        cleaned = []
        for item in cams[:12]:
            if isinstance(item, dict) and item.get("id"):
                cleaned.append({
                    "id": str(item.get("id") or "")[:120],
                    "label": str(item.get("label") or "Camera")[:80],
                })
        data["cameras"] = cleaned
    return data


def media_key(item: dict) -> str:
    vault_id = item.get("vault_id")
    if vault_id:
        return f"vault:{vault_id}"
    playlist = str(item.get("playlist") or "")
    name = str(item.get("name") or "")
    return f"{playlist}::{name}"


def init_live_session(
    dynamic,
    *,
    session_id: str,
    media_keys: list[str],
    beat_speed: float,
    slide_duration: int,
) -> dict:
    import time

    now_ms = int(time.time() * 1000)
    slide_ms = max(3000, int(slide_duration) * 1000)
    payload = {
        "paused": False,
        "red_light": False,
        "lock_input": False,
        "force_end": False,
        "mute": False,
        "session_id": session_id,
        "media_keys": media_keys,
        "media_index": 0,
        "media_seq": 1,
        "media_until": now_ms + slide_ms,
        "beat_speed": beat_speed,
        "playing": False,
        "sub_ready": False,
        "command": None,
        "command_event": None,
        "beat_epoch_ms": now_ms,
        "recording": "off",
        "want_camera": False,
        "want_dom_camera": False,
    }
    dynamic.instructor_live = json.dumps(parse_live(json.dumps(payload)))
    return parse_live(dynamic.instructor_live)


def advance_live_media(dynamic, *, now_ms: int | None = None) -> dict:
    import time

    current = parse_live(getattr(dynamic, "instructor_live", None))
    keys = current.get("media_keys") or []
    if not keys:
        return current
    idx = int(current.get("media_index") or 0) + 1
    if idx >= len(keys):
        idx = 0
    current["media_index"] = idx
    current["media_seq"] = int(current.get("media_seq") or 0) + 1
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    current["media_until"] = ts + 10_000
    dynamic.instructor_live = json.dumps(current)
    return current


def merge_live(dynamic, payload: dict) -> dict:
    current = parse_live(getattr(dynamic, "instructor_live", None))
    for key in ("paused", "red_light", "lock_input", "force_end", "mute", "playing", "sub_ready"):
        if payload.get(key) is not None:
            current[key] = bool(payload[key])
    if payload.get("session_id") is not None:
        current["session_id"] = str(payload.get("session_id") or "")[:64]
    if payload.get("beat_speed") is not None:
        current["beat_speed"] = _float(payload["beat_speed"], current["beat_speed"], 0.1, 8.0)
    if payload.get("media_index") is not None:
        keys = current.get("media_keys") or []
        idx = _int(payload["media_index"], 0, 0, max(0, len(keys) - 1))
        if keys:
            current["media_index"] = idx
            current["media_seq"] = int(current.get("media_seq") or 0) + 1
    if payload.get("media_until") is not None:
        current["media_until"] = _int(payload["media_until"], current["media_until"], 0, 10_000_000_000_000)
    if payload.get("advance_media"):
        import time

        current = advance_live_media(dynamic, now_ms=int(time.time() * 1000))
        return current
    if "command" in payload:
        cmd = payload.get("command")
        if cmd is None:
            current["command"] = None
        elif isinstance(cmd, dict) and cmd.get("type") in {"edge", "ruin"}:
            current["command"] = {
                "type": cmd["type"],
                "id": str(cmd.get("id") or "")[:64],
                "deadline_ms": _int(cmd.get("deadline_ms"), 0, 0, 10_000_000_000_000),
                "issued_ms": _int(cmd.get("issued_ms"), 0, 0, 10_000_000_000_000),
            }
            current["command_event"] = None
    if payload.get("command_ack"):
        cmd = current.get("command") or {}
        current["command_event"] = {
            "type": "completed",
            "command_type": str(cmd.get("type") or ""),
            "at_ms": payload.get("at_ms") or 0,
            "message": str(payload.get("message") or "Sub acknowledged.")[:240],
        }
        current["command"] = None
    if payload.get("command_failed"):
        cmd = current.get("command") or {}
        current["command_event"] = {
            "type": "failed" if payload.get("reason") == "timeout" else "failed",
            "command_type": str(cmd.get("type") or ""),
            "at_ms": payload.get("at_ms") or 0,
            "message": str(payload.get("message") or "Sub did not comply in time.")[:240],
        }
        current["command"] = None
    if payload.get("clear_command_event"):
        current["command_event"] = None
    if payload.get("want_camera") is not None:
        current["want_camera"] = bool(payload["want_camera"])
    if payload.get("want_dom_camera") is not None:
        current["want_dom_camera"] = bool(payload["want_dom_camera"])
    if payload.get("camera_device_id") is not None:
        current["camera_device_id"] = str(payload.get("camera_device_id") or "")[:120]
    if payload.get("recording") is not None:
        rec = str(payload.get("recording") or "off").strip().lower()
        current["recording"] = rec if rec in {"off", "sub", "domme", "both"} else "off"
    if payload.get("beat_epoch_ms") is not None:
        current["beat_epoch_ms"] = _int(payload["beat_epoch_ms"], 0, 0, 10_000_000_000_000)
    if payload.get("beat_speed") is not None and payload.get("beat_epoch_ms") is None:
        import time
        current["beat_epoch_ms"] = int(time.time() * 1000)
    if payload.get("cameras") is not None and isinstance(payload.get("cameras"), list):
        cleaned = []
        for item in payload["cameras"][:12]:
            if isinstance(item, dict) and item.get("id"):
                cleaned.append({
                    "id": str(item.get("id") or "")[:120],
                    "label": str(item.get("label") or "Camera")[:80],
                })
        current["cameras"] = cleaned
    dynamic.instructor_live = json.dumps(current)
    return current


def save_live(dynamic, payload: dict) -> dict:
    return merge_live(dynamic, payload)


def save_config(dynamic, payload: dict) -> dict:
    current = parse_config(getattr(dynamic, "instructor_config", None))
    incoming = {k: v for k, v in payload.items() if v is not None}
    packs = incoming.pop("packs", None)
    tasks = incoming.pop("tasks", None)
    kinds = incoming.pop("media_kinds", None)
    current.update(incoming)
    if packs is not None:
        merged = dict(current["packs"])
        for name in DEFAULT_PACKS:
            if isinstance(packs.get(name), bool):
                merged[name] = packs[name]
        current["packs"] = merged
        if tasks is None:
            current["tasks"] = _tasks_from_packs(merged)
    if tasks is not None:
        current["tasks"] = tasks
    if kinds is not None:
        current["media_kinds"] = kinds
    current = parse_config(json.dumps(current))
    dynamic.instructor_config = json.dumps(current)
    return current
