"""Keyholder chastity / gift goal requirements and progress."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityBreakType,
    ChastityLockup,
    Dynamic,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    PartnerRole,
    Task,
    TaskCompletion,
)
from .tracking_events import (
    has_denial_tag,
    has_full_orgasm_tag,
    has_ruined_orgasm_tag,
    is_orgasm_event,
    is_play_event,
)
from .tags import tags_to_list

REQUIREMENT_TYPES = {
    "days_since_full_orgasm": {
        "title": "Days since last full orgasm",
        "kind": "duration",
        "hint": "Time since the sub’s last full-orgasm tag / Released!",
    },
    "days_since_lockup": {
        "title": "Days in current / last lockup",
        "kind": "duration",
        "hint": "Elapsed locked time since lockup start (active preferred).",
    },
    "tasks_completed": {
        "title": "Tasks completed",
        "kind": "count",
        "hint": "Approved tasks completed since the goal was (re)set. Optional tag filter counts only matching category tags.",
    },
    "orgasms_to_dominant": {
        "title": "Orgasms provided to keyholder",
        "kind": "count",
        "hint": "Orgasm entries logged for the dominant since goal reset.",
    },
    "ruins": {
        "title": "Ruined orgasms",
        "kind": "count",
        "hint": "Ruined-orgasm tags + authorized ruin breaks since reset.",
    },
    "denials": {
        "title": "Denials",
        "kind": "count",
        "hint": "No-orgasm (play) logs for the sub, Denied tags, plus denial unlocks.",
    },
    "sleep_in_chastity": {
        "title": "Sleep in chastity",
        "kind": "duration",
        "hint": "Hours locked since tracking started. Breaks under 20 minutes still count. A longer unlock does not. 24 hours is one full day.",
    },
}

GOAL_KINDS = {
    "orgasm_grant": {"title": "Orgasm / unlock grant", "tone": "primary"},
    "ruin_gift": {"title": "Ruin gift", "tone": "gift"},
    "misc_gift": {"title": "Misc gift", "tone": "gift"},
    "switch_gift": {"title": "Switch gift", "tone": "gift"},
}

DEFAULT_MAX_SOFT = 2


ARCHIVE_REASONS = {
    "completed": "Completed / granted",
    "replaced": "Replaced by a new goal",
}

START_MODES = {
    "now": {
        "title": "Start now",
        "hint": "Ignore prior events — tracking window begins when this goal is created or repeated.",
    },
    "rolling": {
        "title": "Since last full orgasm",
        "hint": "Tracking window starts at the last full orgasm.",
    },
    "rolling_ruin": {
        "title": "Since last ruin",
        "hint": "Tracking window starts at the last ruined orgasm.",
    },
}


def _defaults() -> dict:
    return {"goals": [], "header_hidden": True}


def _clean_every_minutes(raw) -> int | None:
    if raw in (None, "", 0, "0"):
        return None
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    if minutes < 15 or minutes > 7 * 24 * 60:
        return None
    return minutes


def _clean_cycle_extras(raw) -> list[dict]:
    """One-cycle requirements tied to a confession. Cleared when the gift is granted."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rtype = item.get("type")
        if rtype not in REQUIREMENT_TYPES:
            continue
        try:
            value = float(item.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        extra = {"type": rtype, "value": value}
        confession_id = str(item.get("confession_id") or "").strip()
        if confession_id:
            extra["confession_id"] = confession_id[:36]
        tag = str(item.get("tag") or "").strip()
        if tag:
            extra["tag"] = tag[:80]
        cleaned.append(extra)
    return cleaned[:8]


def _parse_optional_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_goals(raw: str | None) -> dict:
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
    goals = data.get("goals")
    if isinstance(goals, list):
        cleaned = []
        for g in goals:
            if not isinstance(g, dict):
                continue
            kind = g.get("kind") if g.get("kind") in GOAL_KINDS else "orgasm_grant"
            reqs = []
            for r in g.get("requirements") or []:
                if not isinstance(r, dict):
                    continue
                rtype = r.get("type")
                if rtype not in REQUIREMENT_TYPES:
                    continue
                try:
                    value = float(r.get("value") or 0)
                except (TypeError, ValueError):
                    continue
                if value <= 0:
                    continue
                item = {"type": rtype, "value": value}
                tag = str(r.get("tag") or "").strip()
                if tag:
                    item["tag"] = tag[:80]
                reqs.append(item)
            start_mode = g.get("start_mode") if g.get("start_mode") in START_MODES else "rolling"
            archive_reason = g.get("archive_reason")
            if archive_reason not in ARCHIVE_REASONS:
                archive_reason = None
            active = bool(g.get("active", True))
            if archive_reason and active:
                # Archived goals are never active
                active = False
            cleaned.append(
                {
                    "id": str(g.get("id") or uuid.uuid4()),
                    "kind": kind,
                    "title": (g.get("title") or GOAL_KINDS[kind]["title"])[:80],
                    "for_membership_id": g.get("for_membership_id") or None,
                    "requirements": reqs,
                    "reset_at": g.get("reset_at") or None,
                    "created_at": g.get("created_at") or g.get("reset_at") or None,
                    "start_mode": start_mode,
                    "active": active,
                    "archived_at": g.get("archived_at") or None,
                    "archive_reason": archive_reason,
                    "repeat_count": int(g.get("repeat_count") or 0),
                    "history": _clean_history(g.get("history")),
                    "last_met_at": g.get("last_met_at") or None,
                    "bank_spent": _clean_spent(g.get("bank_spent")),
                    "ready_remind_at": g.get("ready_remind_at") or None,
                    "ready_remind_every_minutes": _clean_every_minutes(g.get("ready_remind_every_minutes")),
                    "ready_pushed_for": g.get("ready_pushed_for") or None,
                    "cycle_extras": _clean_cycle_extras(g.get("cycle_extras")),
                    "switch_style": "scene" if g.get("switch_style") == "scene" else "goal",
                }
            )
        base["goals"] = cleaned
    base["header_hidden"] = bool(data.get("header_hidden", True))
    return base


def serialize_goals(data: dict) -> str:
    parsed = parse_goals(json.dumps(data) if isinstance(data, dict) else (data or ""))
    return json.dumps(parsed)

def _sub_memberships(db: Session, dynamic_id: str) -> list[Membership]:
    return (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.submissive)
        .all()
    )


def _dominant(db: Session, dynamic_id: str) -> Membership | None:
    return (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.dominant)
        .first()
    )


def _parse_reset(raw: str | None) -> datetime:
    if not raw:
        return datetime.utcnow() - timedelta(days=3650)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow() - timedelta(days=3650)


def _last_full_orgasm_at(db: Session, dynamic_id: str, sub_id: str) -> datetime | None:
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == sub_id,
            OrgTrackingEntry.event_type.in_([OrgEventType.orgasm, OrgEventType.both]),
        )
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .limit(50)
        .all()
    )
    for entry in entries:
        rows = entry.orgasms or []
        if rows:
            if any(has_full_orgasm_tag(tags_to_list(r.tags)) for r in rows):
                return entry.occurred_at
        elif has_full_orgasm_tag(tags_to_list(entry.tags)):
            return entry.occurred_at
    lockup = (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
            ChastityLockup.ended_kind == "released_orgasm",
        )
        .order_by(ChastityLockup.ended_at.desc())
        .first()
    )
    return lockup.ended_at if lockup and lockup.ended_at else None


def _last_ruin_at(db: Session, dynamic_id: str, sub_id: str) -> datetime | None:
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == sub_id,
            OrgTrackingEntry.event_type.in_([OrgEventType.orgasm, OrgEventType.both]),
        )
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .limit(50)
        .all()
    )
    for entry in entries:
        rows = entry.orgasms or []
        if rows:
            if any(has_ruined_orgasm_tag(tags_to_list(r.tags)) for r in rows):
                return entry.occurred_at
        elif has_ruined_orgasm_tag(tags_to_list(entry.tags)):
            return entry.occurred_at
    return None


def _active_or_last_lockup(db: Session, dynamic_id: str, sub_id: str) -> ChastityLockup | None:
    active = (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
            ChastityLockup.status == LockupStatus.active,
        )
        .order_by(ChastityLockup.started_at.desc())
        .first()
    )
    if active:
        return active
    return (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
        )
        .order_by(ChastityLockup.started_at.desc())
        .first()
    )


def _clean_history(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        outcome = str(item.get("outcome") or "").strip().lower()
        if outcome not in {"met", "gift", "reset", "cheated"}:
            continue
        out.append(
            {
                "at": str(item.get("at") or ""),
                "outcome": outcome,
                "progress": str(item.get("progress") or "")[:200],
            }
        )
    return out[-100:]


def _clean_spent(raw) -> list[float]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            out.append(max(0.0, float(item)))
        except (TypeError, ValueError):
            out.append(0.0)
    return out[:20]


_SHORT_BREAK = timedelta(minutes=20)


def _overlap_seconds(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    start = max(a0, b0)
    end = min(a1, b1)
    if end <= start:
        return 0.0
    return (end - start).total_seconds()


def _locked_hours(db: Session, dynamic_id: str, sub_id: str, since: datetime) -> float:
    """Hours locked since `since`. Breaks under 20 minutes still count as locked."""
    now = datetime.utcnow()
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
        )
        .all()
    )
    total = 0.0
    for lockup in lockups:
        start = lockup.started_at
        end = lockup.ended_at or now
        if start is None or end <= since or start >= now:
            continue
        window0 = max(start, since)
        window1 = min(end, now)
        if window1 <= window0:
            continue
        span = (window1 - window0).total_seconds()
        for brk in lockup.breaks or []:
            b0 = brk.started_at
            b1 = brk.ended_at or now
            if b0 is None or b1 <= b0:
                continue
            if (b1 - b0) < _SHORT_BREAK:
                continue
            span -= _overlap_seconds(window0, window1, b0, b1)
        total += max(0.0, span)
    return total / 3600.0


def _count_tasks_completed(
    db: Session,
    dynamic_id: str,
    sub_id: str,
    since: datetime,
    *,
    tag: str | None = None,
) -> int:
    rows = (
        db.query(TaskCompletion)
        .join(Task, TaskCompletion.task_id == Task.id)
        .filter(
            TaskCompletion.dynamic_id == dynamic_id,
            TaskCompletion.completed_at >= since,
            or_(
                TaskCompletion.membership_id == sub_id,
                and_(
                    Task.assigned_to_membership_id.is_(None),
                    or_(
                        Task.created_by_membership_id == sub_id,
                        TaskCompletion.membership_id == sub_id,
                    ),
                ),
            ),
        )
        .all()
    )
    if not tag:
        return len(rows)
    needle = tag.strip().lower()
    count = 0
    for row in rows:
        tags = [t.lower() for t in tags_to_list(row.tags or "")]
        if needle in tags:
            count += 1
    return count


def _count_orgasms_for(db: Session, dynamic_id: str, membership_id: str, since: datetime) -> int:
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == membership_id,
            OrgTrackingEntry.occurred_at >= since,
            OrgTrackingEntry.event_type.in_([OrgEventType.orgasm, OrgEventType.both]),
        )
        .all()
    )
    total = 0
    for entry in entries:
        if entry.orgasms:
            total += len(entry.orgasms)
        else:
            total += 1
    return total


def _count_ruins(db: Session, dynamic_id: str, sub_id: str, since: datetime) -> int:
    count = 0
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == sub_id,
            OrgTrackingEntry.occurred_at >= since,
        )
        .all()
    )
    for entry in entries:
        if not is_orgasm_event(entry.event_type):
            continue
        rows = entry.orgasms or []
        if rows:
            count += sum(1 for r in rows if has_ruined_orgasm_tag(tags_to_list(r.tags)))
        elif has_ruined_orgasm_tag(tags_to_list(entry.tags)):
            count += 1
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
        )
        .all()
    )
    for lockup in lockups:
        for brk in lockup.breaks or []:
            if brk.break_type == ChastityBreakType.authorized_ruin and brk.started_at >= since:
                count += 1
    return count


def _count_denials(db: Session, dynamic_id: str, sub_id: str, since: datetime) -> int:
    """Count sub denials: every no-orgasm play log, Denied tags on orgasm logs, denial unlocks."""
    count = 0
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == sub_id,
            OrgTrackingEntry.occurred_at >= since,
        )
        .all()
    )
    for entry in entries:
        # Play / no-orgasm sessions are denials by definition.
        if is_play_event(entry.event_type):
            count += 1
            continue
        if not is_orgasm_event(entry.event_type):
            continue
        rows = list(entry.orgasms or [])
        if rows:
            hits = sum(1 for r in rows if has_denial_tag(tags_to_list(r.tags)))
            if hits:
                count += hits
            elif has_denial_tag(tags_to_list(entry.tags)):
                count += 1
        elif has_denial_tag(tags_to_list(entry.tags)):
            count += 1
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
        )
        .all()
    )
    for lockup in lockups:
        for brk in lockup.breaks or []:
            if brk.break_type == ChastityBreakType.authorized_denial and brk.started_at >= since:
                count += 1
    return count
def evaluate_requirement(
    db: Session,
    *,
    dynamic_id: str,
    sub_id: str,
    dominant_id: str | None,
    req: dict,
    reset_at: datetime,
    spent: float = 0.0,
) -> dict[str, Any]:
    rtype = req["type"]
    target = float(req["value"])
    meta = REQUIREMENT_TYPES[rtype]
    now = datetime.utcnow()
    current = 0.0
    eta_at = None
    unit = "count"

    if rtype == "days_since_full_orgasm":
        unit = "days"
        last_any = _last_full_orgasm_at(db, dynamic_id, sub_id)
        last = last_any if last_any and last_any >= reset_at else None
        if last_any is None:
            # Never had a full orgasm at all → treat duration gate as satisfied
            current = target
            eta_at = now
        elif last is None:
            # Prior O existed but before this goal's tracking window (start now)
            current = max(0.0, (now - reset_at).total_seconds() / 86400)
            need = target - current
            eta_at = now + timedelta(days=max(0, need)) if need > 0 else now
        else:
            current = (now - last).total_seconds() / 86400
            need = target - current
            eta_at = now + timedelta(days=max(0, need)) if need > 0 else now
    elif rtype == "days_since_lockup":
        unit = "days"
        lockup = _active_or_last_lockup(db, dynamic_id, sub_id)
        if lockup is None:
            current = 0
            eta_at = now + timedelta(days=target)
        else:
            anchor = max(lockup.started_at, reset_at)
            current = max(0.0, (now - anchor).total_seconds() / 86400)
            need = target - current
            eta_at = now + timedelta(days=max(0, need)) if need > 0 else now
    elif rtype == "tasks_completed":
        tag = (req.get("tag") or "").strip() or None
        current = float(
            _count_tasks_completed(db, dynamic_id, sub_id, reset_at, tag=tag)
        )
    elif rtype == "orgasms_to_dominant":
        if dominant_id:
            current = float(_count_orgasms_for(db, dynamic_id, dominant_id, reset_at))
    elif rtype == "ruins":
        current = float(_count_ruins(db, dynamic_id, sub_id, reset_at))
    elif rtype == "denials":
        current = float(_count_denials(db, dynamic_id, sub_id, reset_at))
    elif rtype == "sleep_in_chastity":
        unit = "hours"
        current = _locked_hours(db, dynamic_id, sub_id, reset_at)
        need = target - current
        eta_at = now + timedelta(hours=max(0, need)) if need > 0 else now

    if spent:
        current = max(0.0, current - float(spent))
    met = current >= target
    if unit == "days" and not met:
        eta_at = now + timedelta(days=max(0.0, target - current))
    elif unit == "hours" and not met:
        eta_at = now + timedelta(hours=max(0.0, target - current))
    remaining = max(0.0, target - current)
    shown = round(current, 1) if unit in {"days", "hours"} else int(current)
    remain_shown = round(remaining, 1) if unit in {"days", "hours"} else int(remaining)
    return {
        "type": rtype,
        "title": meta["title"],
        "kind": meta["kind"],
        "hint": meta["hint"],
        "tag": (req.get("tag") or "").strip(),
        "target": target,
        "current": shown,
        "remaining": remain_shown,
        "met": met,
        "unit": unit,
        "eta_at": eta_at.isoformat() + "Z" if eta_at and not met and unit in {"days", "hours"} else None,
    }


def resolve_tracking_start(
    db: Session,
    *,
    dynamic_id: str,
    sub_id: str | None,
    start_mode: str,
) -> tuple[datetime, str]:
    """Return (reset_at, label) for a new/repeated goal."""
    now = datetime.utcnow().replace(microsecond=0)
    if start_mode == "now" or not sub_id:
        return now, "now"
    if start_mode == "rolling_ruin":
        last_ruin = _last_ruin_at(db, dynamic_id, sub_id)
        if last_ruin is None:
            return now, "now (no prior ruin)"
        return last_ruin.replace(microsecond=0), "last ruin"
    last = _last_full_orgasm_at(db, dynamic_id, sub_id)
    if last is None:
        return now, "now (no prior full orgasm)"
    return last.replace(microsecond=0), "last full orgasm"


def build_metric_baselines(
    db: Session,
    *,
    dynamic_id: str,
    sub_id: str,
    dominant_id: str | None,
    start_mode: str = "rolling",
) -> dict:
    """Snapshot of where metrics stand for the chosen start mode."""
    reset_at, since_label = resolve_tracking_start(
        db, dynamic_id=dynamic_id, sub_id=sub_id, start_mode=start_mode
    )
    metrics = []
    for rtype, meta in REQUIREMENT_TYPES.items():
        evaluated = evaluate_requirement(
            db,
            dynamic_id=dynamic_id,
            sub_id=sub_id,
            dominant_id=dominant_id,
            req={"type": rtype, "value": 1},
            reset_at=reset_at,
        )
        metrics.append(
            {
                "type": rtype,
                "title": meta["title"],
                "kind": meta["kind"],
                "current": evaluated["current"],
                "unit": evaluated["unit"],
            }
        )
    return {
        "start_mode": start_mode,
        "since": reset_at.isoformat() + "Z",
        "since_label": since_label,
        "metrics": metrics,
    }


def _goal_progress_row(
    db: Session,
    *,
    dynamic: Dynamic,
    goal: dict,
    subs: list[Membership],
    dom: Membership | None,
    default_sub: str | None,
) -> dict | None:
    sub_id = goal.get("for_membership_id") or default_sub
    if not sub_id:
        return None
    reset_at = _parse_reset(goal.get("reset_at"))
    spent_list = goal.get("bank_spent") or []
    reqs = []
    for index, req in enumerate(goal.get("requirements") or []):
        spent = float(spent_list[index]) if index < len(spent_list) else 0.0
        reqs.append(
            evaluate_requirement(
                db,
                dynamic_id=dynamic.id,
                sub_id=sub_id,
                dominant_id=dom.id if dom else None,
                req=req,
                reset_at=reset_at,
                spent=spent,
            )
        )
    for extra in goal.get("cycle_extras") or []:
        evaluated = evaluate_requirement(
            db,
            dynamic_id=dynamic.id,
            sub_id=sub_id,
            dominant_id=dom.id if dom else None,
            req=extra,
            reset_at=reset_at,
            spent=0.0,
        )
        evaluated["temporary"] = True
        evaluated["confession_id"] = extra.get("confession_id")
        evaluated["title"] = f"This time · {evaluated['title']}"
        reqs.append(evaluated)
    all_met = bool(reqs) and all(r["met"] for r in reqs)
    unmet_etas = [
        datetime.fromisoformat(r["eta_at"].replace("Z", ""))
        for r in reqs
        if (not r["met"]) and r.get("eta_at")
    ]
    countdown_at = max(unmet_etas) if unmet_etas else (None if not all_met else datetime.utcnow())
    tone = GOAL_KINDS.get(goal["kind"], GOAL_KINDS["orgasm_grant"])["tone"]
    return {
        "id": goal["id"],
        "kind": goal["kind"],
        "tone": tone,
        "title": goal["title"],
        "for_membership_id": sub_id,
        "for_display_name": next((s.display_name for s in subs if s.id == sub_id), "Sub"),
        "requirements": reqs,
        "ready": all_met and bool(goal.get("active", True)),
        "grants_ready": _grants_ready(reqs) if goal.get("active", True) else 0,
        "countdown_at": (countdown_at.isoformat() + "Z") if countdown_at and not all_met else None,
        "requirement_count": len(reqs),
        "complex": len(reqs) > DEFAULT_MAX_SOFT,
        "active": bool(goal.get("active", True)),
        "created_at": goal.get("created_at"),
        "reset_at": goal.get("reset_at"),
        "start_mode": goal.get("start_mode") or "rolling",
        "switch_style": "scene" if goal.get("switch_style") == "scene" else "goal",
        "archived_at": goal.get("archived_at"),
        "archive_reason": goal.get("archive_reason"),
        "repeat_count": int(goal.get("repeat_count") or 0),
        "history": list(goal.get("history") or []),
        "last_met_at": goal.get("last_met_at"),
        "ready_remind_at": goal.get("ready_remind_at"),
        "cycle_extras": list(goal.get("cycle_extras") or []),
    }


def _grants_ready(reqs: list[dict]) -> int:
    floors = []
    for req in reqs:
        target = float(req.get("target") or 0)
        if target <= 0:
            continue
        floors.append(int(float(req.get("current") or 0) // target))
    return min(floors) if floors else 0


def _consume_grant(goal: dict) -> None:
    reqs = goal.get("requirements") or []
    spent = [float(n) for n in (goal.get("bank_spent") or [])]
    while len(spent) < len(reqs):
        spent.append(0.0)
    for index, req in enumerate(reqs):
        spent[index] += float(req.get("value") or 0)
    goal["bank_spent"] = spent
    goal["last_met_at"] = None
    goal["ready_remind_at"] = None
    goal["ready_remind_every_minutes"] = None
    goal["ready_pushed_for"] = None
    goal["cycle_extras"] = []


def _notify_goals_ready(
    db: Session,
    dynamic: Dynamic,
    ready_rows: list[dict],
    all_rows: list[dict],
    *,
    reminder: bool = False,
) -> None:
    from .push import notify_task_push

    if not ready_rows:
        return
    lines = []
    for row in all_rows:
        if not row.get("active", True):
            continue
        bits = ", ".join(
            f"{req.get('title')} {req.get('current')}/{req.get('target')}"
            for req in (row.get("requirements") or [])
        )
        state = "ready" if row.get("ready") else "working towards"
        lines.append(f"{row.get('title')}: {bits} ({state})")
    first = ready_rows[0]
    grants = int(first.get("grants_ready") or 1)
    head = f"{first.get('title') or 'Goal'} is ready"
    if grants > 1:
        head += f" ({grants} gifts)"
    if len(ready_rows) > 1:
        head = f"{len(ready_rows)} gifts are ready"
    stamp = str(first.get("last_met_at") or "")[-6:]
    prefix = "wait" if reminder else "earn"
    notify_task_push(
        db,
        dynamic_id=dynamic.id,
        title="Gift still waiting" if reminder else "Gift earned",
        body=(head + "\n" + "\n".join(lines[:8]))[:500],
        url=f"/dynamic/{dynamic.id}/tasks?goal={first.get('id')}",
        tag=f"{prefix}-{str(first.get('id') or '')[:12]}-{stamp}"[:32],
        keyholders_only=True,
    )


def _progress_text(row: dict | None) -> str:
    if not row:
        return ""
    return "; ".join(
        f"{r.get('current')}/{r.get('target')}" for r in (row.get("requirements") or [])
    )[:200]


def _stamp_met(goal: dict, row: dict | None) -> bool:
    if not row or not row.get("ready") or not goal.get("active", True):
        return False
    reset = str(goal.get("reset_at") or "")
    last = str(goal.get("last_met_at") or "")
    if last and (not reset or last >= reset):
        return False
    now = datetime.utcnow().replace(microsecond=0)
    hist = list(goal.get("history") or [])
    hist.append({"at": now.isoformat() + "Z", "outcome": "met", "progress": _progress_text(row)})
    goal["history"] = hist[-100:]
    goal["last_met_at"] = now.isoformat() + "Z"
    return True


def goal_unmet_for_event(db: Session, dynamic: Dynamic, sub_id: str, kind: str) -> bool:
    """True when an active goal of the matching gift type is not ready yet."""
    if kind not in {"full", "ruin", "cheated"}:
        return False
    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    subs = _sub_memberships(db, dynamic.id)
    dom = _dominant(db, dynamic.id)
    default_sub = subs[0].id if len(subs) == 1 else None
    for goal in data["goals"]:
        if not goal.get("active", True):
            continue
        owner = goal.get("for_membership_id") or default_sub
        if owner and owner != sub_id:
            continue
        gk = goal.get("kind")
        if kind == "full" and gk != "orgasm_grant":
            continue
        if kind == "ruin" and gk != "ruin_gift":
            continue
        if kind == "cheated" and gk not in {"orgasm_grant", "ruin_gift"}:
            continue
        row = _goal_progress_row(
            db, dynamic=dynamic, goal=goal, subs=subs, dom=dom, default_sub=default_sub
        )
        if row and row.get("requirements") and not row.get("ready"):
            return True
    return False


def note_orgasm_gift(
    db: Session,
    dynamic: Dynamic,
    *,
    sub_id: str,
    occurred_at: datetime,
    tags: list[str],
    orgasm_counts: dict | None = None,
) -> None:
    """Append goal history and consume one ready gift per matching orgasm on the log."""
    from .tracking_events import has_cheated_tag

    counts = orgasm_counts or {}
    cheated_n = int(counts.get("cheated") or 0)
    ruin_n = int(counts.get("ruin") or 0)
    full_n = int(counts.get("full") or 0)
    if orgasm_counts is None:
        cheated = has_cheated_tag(tags)
        ruined = has_ruined_orgasm_tag(tags)
        full = has_full_orgasm_tag(tags) and not ruined
        cheated_n = 1 if cheated else 0
        ruin_n = 1 if ruined and not cheated else 0
        full_n = 1 if full else 0
    if cheated_n + ruin_n + full_n <= 0:
        return
    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    subs = _sub_memberships(db, dynamic.id)
    dom = _dominant(db, dynamic.id)
    default_sub = subs[0].id if len(subs) == 1 else None
    changed = False
    when = (occurred_at or datetime.utcnow()).replace(microsecond=0)
    stamp = when.isoformat() + "Z"
    for goal in data["goals"]:
        if not goal.get("active", True):
            continue
        owner = goal.get("for_membership_id") or default_sub
        if owner and owner != sub_id:
            continue
        gk = goal.get("kind")
        applicable = 0
        outcome = None
        if cheated_n and gk == "orgasm_grant":
            outcome = "cheated"
        elif full_n and gk == "orgasm_grant":
            applicable = full_n
            outcome = "pending"
        elif ruin_n and gk == "ruin_gift":
            applicable = ruin_n
            outcome = "pending"
        if outcome is None:
            continue
        row = _goal_progress_row(
            db, dynamic=dynamic, goal=goal, subs=subs, dom=dom, default_sub=default_sub
        )
        taken = 0
        if outcome == "pending":
            ready_n = int(row.get("grants_ready") or 0) if row and row.get("ready") else 0
            taken = min(applicable, ready_n)
            if taken:
                for _ in range(taken):
                    _consume_grant(goal)
                row = _goal_progress_row(
                    db, dynamic=dynamic, goal=goal, subs=subs, dom=dom, default_sub=default_sub
                )
                outcome = "gift"
            else:
                outcome = "reset"
        hist = list(goal.get("history") or [])
        hist.append({"at": stamp, "outcome": outcome, "progress": _progress_text(row)})
        goal["history"] = hist[-100:]
        goal["repeat_count"] = int(goal.get("repeat_count") or 0) + (taken or 1)
        changed = True
    if changed:
        dynamic.chastity_goals = serialize_goals(data)
        db.add(dynamic)


def build_goals_progress(db: Session, dynamic: Dynamic) -> dict:
    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    subs = _sub_memberships(db, dynamic.id)
    dom = _dominant(db, dynamic.id)
    default_sub = subs[0].id if len(subs) == 1 else None
    active_goals = []
    archived_goals = []
    newly_ready = []
    dirty = False
    for goal in data["goals"]:
        row = _goal_progress_row(
            db,
            dynamic=dynamic,
            goal=goal,
            subs=subs,
            dom=dom,
            default_sub=default_sub,
        )
        if row is None:
            continue
        if _stamp_met(goal, row):
            dirty = True
            row["history"] = list(goal.get("history") or [])
            row["last_met_at"] = goal.get("last_met_at")
            newly_ready.append(row)
        if goal.get("active", True):
            active_goals.append(row)
        else:
            archived_goals.append(row)
    if dirty:
        ready_ids = {row["id"] for row in newly_ready}
        for goal in data["goals"]:
            if goal["id"] in ready_ids:
                goal["ready_pushed_for"] = goal.get("last_met_at")
        dynamic.chastity_goals = serialize_goals(data)
        db.add(dynamic)
        db.commit()
        _notify_goals_ready(db, dynamic, newly_ready, active_goals)
    if _sync_goal_reminders(db, dynamic, data, active_goals):
        dynamic.chastity_goals = serialize_goals(data)
        db.add(dynamic)
        db.commit()

    baselines = None
    sid = default_sub or (subs[0].id if subs else None)
    if sid:
        baselines = {
            "rolling": build_metric_baselines(
                db,
                dynamic_id=dynamic.id,
                sub_id=sid,
                dominant_id=dom.id if dom else None,
                start_mode="rolling",
            ),
            "now": build_metric_baselines(
                db,
                dynamic_id=dynamic.id,
                sub_id=sid,
                dominant_id=dom.id if dom else None,
                start_mode="now",
            ),
            "rolling_ruin": build_metric_baselines(
                db,
                dynamic_id=dynamic.id,
                sub_id=sid,
                dominant_id=dom.id if dom else None,
                start_mode="rolling_ruin",
            ),
        }

    return {
        "goals": active_goals,
        "archived_goals": archived_goals,
        "active_count": len(active_goals),
        "archived_count": len(archived_goals),
        "header_hidden": data.get("header_hidden", True),
        "requirement_catalog": [
            {"id": k, "title": v["title"], "kind": v["kind"], "hint": v["hint"]}
            for k, v in REQUIREMENT_TYPES.items()
        ],
        "goal_kinds": [
            {"id": k, "title": v["title"], "tone": v["tone"]} for k, v in GOAL_KINDS.items()
        ],
        "start_modes": [
            {"id": k, "title": v["title"], "hint": v["hint"]} for k, v in START_MODES.items()
        ],
        "archive_reasons": [
            {"id": k, "title": v} for k, v in ARCHIVE_REASONS.items()
        ],
        "soft_max_requirements": DEFAULT_MAX_SOFT,
        "baselines": baselines,
        "config": data,
    }


def _sync_goal_reminders(
    db: Session,
    dynamic: Dynamic,
    data: dict,
    active_goals: list[dict],
) -> bool:
    """Push once per earned cycle, then again at the keyholder's reminder time."""
    now = datetime.utcnow().replace(microsecond=0)
    changed = False
    by_id = {row["id"]: row for row in active_goals}
    catchup: list[dict] = []
    due: list[dict] = []
    for goal in data["goals"]:
        if not goal.get("active", True):
            continue
        row = by_id.get(goal["id"])
        ready = bool(row and row.get("ready"))
        if not ready:
            if goal.get("ready_remind_at") or goal.get("ready_remind_every_minutes") or goal.get("ready_pushed_for"):
                goal["ready_remind_at"] = None
                goal["ready_remind_every_minutes"] = None
                goal["ready_pushed_for"] = None
                changed = True
            continue
        last = str(goal.get("last_met_at") or "")
        if last and str(goal.get("ready_pushed_for") or "") != last:
            catchup.append(row)
            goal["ready_pushed_for"] = last
            changed = True
        remind_at = _parse_optional_iso(goal.get("ready_remind_at"))
        if remind_at is None or remind_at > now:
            continue
        due.append(row)
        every = int(goal.get("ready_remind_every_minutes") or 0)
        if every > 0:
            goal["ready_remind_at"] = (now + timedelta(minutes=every)).isoformat() + "Z"
        else:
            goal["ready_remind_at"] = None
            goal["ready_remind_every_minutes"] = None
        changed = True
    if catchup:
        _notify_goals_ready(db, dynamic, catchup, active_goals)
    if due:
        _notify_goals_ready(db, dynamic, due, active_goals, reminder=True)
    return changed


def set_goal_reminder(
    db: Session,
    dynamic: Dynamic,
    goal_id: str,
    *,
    remind_at: datetime | None,
    every_minutes: int | None,
) -> dict:
    from fastapi import HTTPException, status

    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    goal = next((item for item in data["goals"] if item["id"] == goal_id), None)
    if goal is None or not goal.get("active", True):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    every = _clean_every_minutes(every_minutes) if every_minutes else None
    if every_minutes and every is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick an interval between 15 minutes and 7 days")
    now = datetime.utcnow().replace(microsecond=0)
    when = remind_at.replace(tzinfo=None) if remind_at and remind_at.tzinfo else remind_at
    if when is None and every:
        when = now + timedelta(minutes=every)
    if when is not None and when <= now:
        when = now + timedelta(minutes=1)
    goal["ready_remind_at"] = (when.isoformat() + "Z") if when else None
    goal["ready_remind_every_minutes"] = every
    dynamic.chastity_goals = serialize_goals(data)
    db.add(dynamic)
    db.commit()
    return {
        "ok": True,
        "ready_remind_at": goal["ready_remind_at"],
        "ready_remind_every_minutes": goal["ready_remind_every_minutes"],
    }


def set_cycle_extra(
    db: Session,
    dynamic: Dynamic,
    goal_id: str,
    *,
    confession_id: str | None,
    req_type: str,
    value: float,
    tag: str | None = None,
    remove_index: int | None = None,
) -> dict:
    from fastapi import HTTPException, status

    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    goal = next((item for item in data["goals"] if item["id"] == goal_id and item.get("active", True)), None)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    extras = list(goal.get("cycle_extras") or [])
    if remove_index is not None:
        if remove_index < 0 or remove_index >= len(extras):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That extra requirement is gone")
        extras.pop(remove_index)
    else:
        if req_type not in REQUIREMENT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick a requirement")
        if value <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Requirement needs a number above 0")
        extra = {"type": req_type, "value": float(value)}
        if confession_id:
            extra["confession_id"] = str(confession_id)[:36]
        if tag and str(tag).strip():
            extra["tag"] = str(tag).strip()[:80]
        replaced = False
        for index, existing in enumerate(extras):
            if existing.get("confession_id") == extra.get("confession_id") and existing.get("type") == extra["type"] and existing.get("tag") == extra.get("tag"):
                extras[index] = extra
                replaced = True
                break
        if not replaced:
            extras.append(extra)
        extras = extras[:8]
    goal["cycle_extras"] = extras
    dynamic.chastity_goals = serialize_goals(data)
    db.add(dynamic)
    db.commit()
    progress = build_goals_progress(db, dynamic)
    progress["you_are_dominant"] = True
    return progress


def ready_gift_inbox_items(db: Session, dynamic_id: str, membership: Membership) -> list[dict]:
    """Ungranted gifts for the keyholder. These stay until the gift is recorded."""
    if membership.role != PartnerRole.dominant:
        return []
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        return []
    progress = build_goals_progress(db, dynamic)
    items: list[dict] = []
    for row in progress.get("goals") or []:
        if not row.get("active", True) or not row.get("ready"):
            continue
        remind_at = _parse_optional_iso(row.get("ready_remind_at"))
        if remind_at is not None and remind_at > datetime.utcnow():
            continue
        grants = int(row.get("grants_ready") or 1)
        bits = ", ".join(
            f"{req.get('title')} {req.get('current')}/{req.get('target')}"
            for req in (row.get("requirements") or [])
        )
        name = row.get("title") or "Goal"
        body = f"{name} — {bits}" if bits else name
        items.append(
            {
                "id": f"goal-ready-{row.get('id')}",
                "kind": "goal_ready",
                "title": "Gift earned" if grants <= 1 else f"{grants} gifts earned",
                "body": body[:200],
                "occurred_at": _parse_optional_iso(row.get("last_met_at")) or datetime.utcnow(),
                "path": f"/dynamic/{dynamic_id}/tasks?goal={row.get('id')}",
                "goal_id": row.get("id"),
            }
        )
    return items


def poll_goal_progress(db: Session) -> None:
    """Stamp newly-ready goals and push the keyholder. Safe to call from the task loop."""
    import logging

    log = logging.getLogger(__name__)
    dynamics = db.query(Dynamic).filter(Dynamic.chastity_goals != "").all()
    for dynamic in dynamics:
        try:
            build_goals_progress(db, dynamic)
        except Exception:
            log.exception("goal progress check failed for %s", dynamic.id)
