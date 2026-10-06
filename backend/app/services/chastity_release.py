"""Orgasm release kind, goal_unmet snapshots, and auto re-lock."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import (
    ChastityLockup,
    ChastityRecordType,
    Dynamic,
    LockupStatus,
    Membership,
)
from .chastity import active_lockup
from .tracking_events import has_cheated_tag, has_full_orgasm_tag, has_ruined_orgasm_tag

DEFAULT_UNLOCK_PRESETS = [
    {"name": "Sleep", "break_type": "authorized_sleep", "start": "23:00", "end": "07:00"},
]


def orgasm_end_kind(tags: list[str]) -> str | None:
    """Full orgasm ends as released_orgasm. Ruined ends only when also cheated."""
    ruined = has_ruined_orgasm_tag(tags)
    full = has_full_orgasm_tag(tags)
    cheated = has_cheated_tag(tags)
    if ruined and cheated:
        return "cheated_orgasm"
    if full and not ruined:
        return "released_orgasm"
    return None


def event_goal_kind(tags: list[str]) -> str | None:
    if has_cheated_tag(tags):
        return "cheated"
    if has_ruined_orgasm_tag(tags):
        return "ruin"
    if has_full_orgasm_tag(tags):
        return "full"
    return None


def effective_unlock_presets(dynamic: Dynamic | None) -> list[dict]:
    raw = getattr(dynamic, "chastity_unlock_presets", None) if dynamic else None
    text = (raw or "").strip()
    if not text:
        return [dict(item) for item in DEFAULT_UNLOCK_PRESETS]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [dict(item) for item in DEFAULT_UNLOCK_PRESETS]
    if not isinstance(data, list) or not data:
        return [dict(item) for item in DEFAULT_UNLOCK_PRESETS]
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:40]
        break_type = str(item.get("break_type") or "").strip()[:40]
        start = str(item.get("start") or "").strip()[:5]
        end = str(item.get("end") or "").strip()[:5]
        if not name or not break_type or len(start) < 4 or len(end) < 4:
            continue
        out.append({"name": name, "break_type": break_type, "start": start, "end": end})
    return out or [dict(item) for item in DEFAULT_UNLOCK_PRESETS]


def serialize_unlock_presets(values) -> str:
    cleaned = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:40]
        break_type = str(item.get("break_type") or "").strip()[:40]
        start = str(item.get("start") or "").strip()[:5]
        end = str(item.get("end") or "").strip()[:5]
        if name and break_type and start and end:
            cleaned.append({"name": name, "break_type": break_type, "start": start, "end": end})
    return json.dumps(cleaned)


def maybe_relock_after_orgasm(db: Session, lockup: ChastityLockup) -> ChastityLockup | None:
    kind = getattr(lockup, "ended_kind", "") or ""
    if kind not in {"released_orgasm", "cheated_orgasm"}:
        return None
    dynamic = db.get(Dynamic, lockup.dynamic_id)
    if dynamic is None or not bool(getattr(dynamic, "chastity_auto_relock_after_orgasm", True)):
        return None
    target = db.get(Membership, lockup.for_membership_id)
    if target is None or not target.chastity_enabled:
        return None
    if active_lockup(db, lockup.dynamic_id, lockup.for_membership_id):
        return None
    start = lockup.ended_at or datetime.utcnow()
    fresh = ChastityLockup(
        dynamic_id=lockup.dynamic_id,
        for_membership_id=lockup.for_membership_id,
        started_by_membership_id=lockup.started_by_membership_id,
        started_at=start,
        device_notes=(lockup.device_notes or "")[:500],
        tags=lockup.tags or "",
        record_type=ChastityRecordType.normal,
        status=LockupStatus.active,
        ended_kind="",
    )
    db.add(fresh)
    db.flush()
    return fresh
