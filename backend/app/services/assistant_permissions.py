"""Keyholder grants for Assistant Domme mutations (ask / session / always / deny)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import HTTPException, status

from ..models import Dynamic

CAPABILITIES = {
    "create_task": {
        "label": "Assign tasks",
        "hint": "Create an assigned task from a suggestion card.",
        "types": ("create_task",),
        "default": "ask",
    },
    "adjust_standing_target": {
        "label": "Adjust standing targets",
        "hint": "Create or change Goals & balance targets.",
        "types": ("adjust_target", "create_standing_target"),
        "default": "ask",
    },
    "adjust_gift_goal": {
        "label": "Edit gift goals",
        "hint": "Bump or retitle a chastity gift goal.",
        "types": ("adjust_gift_goal",),
        "default": "ask",
    },
    "toggle_feature": {
        "label": "Turn features on or off",
        "hint": "Optional Application features only — not core menus.",
        "types": ("toggle_feature",),
        "default": "ask",
    },
    "assign_punishment_task": {
        "label": "Assign punishment tasks",
        "hint": "Create a Punishment-tagged task and optionally cover a confession.",
        "types": ("assign_punishment_task",),
        "default": "ask",
    },
    "open_path": {
        "label": "Open screens",
        "hint": "Jump to a page or scene builder. Does not change data.",
        "types": ("open_path", "open_scene"),
        "default": "always",
    },
}

LEVELS = ("ask", "session", "always", "deny")
GRANT_CHOICES = ("once", "session", "always", "deny")
TYPE_TO_CAPABILITY = {
    kind: cap_id
    for cap_id, meta in CAPABILITIES.items()
    for kind in meta["types"]
}
SESSION_HOURS = 12
NAV_TYPES = {"open_path", "open_scene"}


def _defaults() -> dict:
    return {
        "grants": {cap_id: meta["default"] for cap_id, meta in CAPABILITIES.items()},
        "session": {},
    }


def parse_permissions(raw: str | None) -> dict:
    base = _defaults()
    text = (raw or "").strip()
    if not text:
        return base
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return base
    if not isinstance(data, dict):
        return base
    grants = data.get("grants") if isinstance(data.get("grants"), dict) else {}
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    cleaned_grants = dict(base["grants"])
    for cap_id in CAPABILITIES:
        level = str(grants.get(cap_id) or cleaned_grants[cap_id]).strip().lower()
        if level not in LEVELS:
            level = CAPABILITIES[cap_id]["default"]
        cleaned_grants[cap_id] = level
    cleaned_session = {}
    for cap_id, until in session.items():
        if cap_id not in CAPABILITIES:
            continue
        stamp = str(until or "").strip()
        if stamp:
            cleaned_session[cap_id] = stamp
    return {"grants": cleaned_grants, "session": cleaned_session}


def serialize_permissions(data: dict) -> str:
    parsed = parse_permissions(json.dumps(data if isinstance(data, dict) else {}))
    return json.dumps(parsed)


def capability_for_type(kind: str) -> str | None:
    return TYPE_TO_CAPABILITY.get(str(kind or "").strip())


def _session_valid(until: str | None, now: datetime) -> bool:
    if not until:
        return False
    try:
        when = datetime.fromisoformat(until.replace("Z", ""))
    except ValueError:
        return False
    return when > now


def public_permissions(dynamic: Dynamic) -> dict:
    data = parse_permissions(getattr(dynamic, "assistant_permissions", None))
    now = datetime.utcnow()
    caps = []
    for cap_id, meta in CAPABILITIES.items():
        level = data["grants"].get(cap_id, meta["default"])
        until = data["session"].get(cap_id) or ""
        session_on = level == "session" and _session_valid(until, now)
        caps.append(
            {
                "id": cap_id,
                "label": meta["label"],
                "hint": meta["hint"],
                "level": level,
                "session_until": until if session_on else "",
                "session_active": session_on,
            }
        )
    return {"capabilities": caps, "session_hours": SESSION_HOURS}


def set_grant(dynamic: Dynamic, capability: str, level: str) -> dict:
    if capability not in CAPABILITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown capability")
    if level not in LEVELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown grant level")
    data = parse_permissions(getattr(dynamic, "assistant_permissions", None))
    data["grants"][capability] = level
    if level != "session":
        data["session"].pop(capability, None)
    elif not _session_valid(data["session"].get(capability), datetime.utcnow()):
        data["session"][capability] = (datetime.utcnow() + timedelta(hours=SESSION_HOURS)).isoformat()
    dynamic.assistant_permissions = serialize_permissions(data)
    return public_permissions(dynamic)


def end_sessions(dynamic: Dynamic) -> dict:
    data = parse_permissions(getattr(dynamic, "assistant_permissions", None))
    data["session"] = {}
    for cap_id, level in list(data["grants"].items()):
        if level == "session":
            data["grants"][cap_id] = "ask"
    dynamic.assistant_permissions = serialize_permissions(data)
    return public_permissions(dynamic)


def authorize_suggestion(dynamic: Dynamic, kind: str, grant: str | None) -> dict:
    """Return {ok, needs_permission, denied, capability} and persist grant choices."""
    cap = capability_for_type(kind)
    if not cap:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown suggestion type")
    if kind in NAV_TYPES:
        return {"ok": True, "capability": cap, "needs_permission": False, "denied": False}

    data = parse_permissions(getattr(dynamic, "assistant_permissions", None))
    now = datetime.utcnow()
    level = data["grants"].get(cap, CAPABILITIES[cap]["default"])
    session_on = _session_valid(data["session"].get(cap), now)
    if level == "session" and not session_on:
        level = "ask"
        data["grants"][cap] = "ask"
        data["session"].pop(cap, None)
        dynamic.assistant_permissions = serialize_permissions(data)

    choice = str(grant or "").strip().lower() or None
    if choice and choice not in GRANT_CHOICES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown grant choice")

    if choice == "deny":
        data["grants"][cap] = "deny"
        data["session"].pop(cap, None)
        dynamic.assistant_permissions = serialize_permissions(data)
        return {"ok": False, "capability": cap, "needs_permission": False, "denied": True}

    if choice == "always":
        data["grants"][cap] = "always"
        data["session"].pop(cap, None)
        dynamic.assistant_permissions = serialize_permissions(data)
        return {"ok": True, "capability": cap, "needs_permission": False, "denied": False}

    if choice == "session":
        data["grants"][cap] = "session"
        data["session"][cap] = (now + timedelta(hours=SESSION_HOURS)).isoformat()
        dynamic.assistant_permissions = serialize_permissions(data)
        return {"ok": True, "capability": cap, "needs_permission": False, "denied": False}

    if choice == "once":
        return {"ok": True, "capability": cap, "needs_permission": False, "denied": False}

    if level == "deny":
        return {"ok": False, "capability": cap, "needs_permission": False, "denied": True}
    if level == "always" or (level == "session" and session_on):
        return {"ok": True, "capability": cap, "needs_permission": False, "denied": False}

    return {
        "ok": False,
        "capability": cap,
        "needs_permission": True,
        "denied": False,
        "label": CAPABILITIES[cap]["label"],
    }
