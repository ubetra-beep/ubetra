"""Keyholder chastity / gift goal requirements and progress."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

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
    TaskApprovalStatus,
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
}

GOAL_KINDS = {
    "orgasm_grant": {"title": "Orgasm / unlock grant", "tone": "primary"},
    "ruin_gift": {"title": "Ruin gift", "tone": "gift"},
    "misc_gift": {"title": "Misc gift", "tone": "gift"},
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
        "title": "Rolling (from last full orgasm)",
        "hint": "Use current rolling metrics. By default the window starts at the last full orgasm.",
    },
}


def _defaults() -> dict:
    return {"goals": [], "header_hidden": True}


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
                reqs.append({"type": rtype, "value": value})
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


def _count_tasks_completed(
    db: Session,
    dynamic_id: str,
    sub_id: str,
    since: datetime,
    *,
    tag: str | None = None,
) -> int:
    from ..models import TaskList
    from ..services.tags import tags_to_list

    rows = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(
            TaskList.dynamic_id == dynamic_id,
            Task.completed_at.isnot(None),
            Task.completed_at >= since,
            Task.approval_status == TaskApprovalStatus.approved,
        )
        .all()
    )
    if not tag:
        return len(rows)
    needle = tag.strip().lower()
    count = 0
    for task in rows:
        tags = [t.lower() for t in tags_to_list(task.tags or "")]
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

    met = current >= target
    remaining = max(0.0, target - current)
    return {
        "type": rtype,
        "title": meta["title"],
        "kind": meta["kind"],
        "hint": meta["hint"],
        "target": target,
        "current": round(current, 2) if unit == "days" else int(current),
        "remaining": round(remaining, 2) if unit == "days" else int(remaining),
        "met": met,
        "unit": unit,
        "eta_at": eta_at.isoformat() + "Z" if eta_at and not met and unit == "days" else None,
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
    reqs = [
        evaluate_requirement(
            db,
            dynamic_id=dynamic.id,
            sub_id=sub_id,
            dominant_id=dom.id if dom else None,
            req=r,
            reset_at=reset_at,
        )
        for r in goal.get("requirements") or []
    ]
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
        "countdown_at": (countdown_at.isoformat() + "Z") if countdown_at and not all_met else None,
        "requirement_count": len(reqs),
        "complex": len(reqs) > DEFAULT_MAX_SOFT,
        "active": bool(goal.get("active", True)),
        "created_at": goal.get("created_at"),
        "reset_at": goal.get("reset_at"),
        "start_mode": goal.get("start_mode") or "rolling",
        "archived_at": goal.get("archived_at"),
        "archive_reason": goal.get("archive_reason"),
        "repeat_count": int(goal.get("repeat_count") or 0),
    }


def build_goals_progress(db: Session, dynamic: Dynamic) -> dict:
    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    subs = _sub_memberships(db, dynamic.id)
    dom = _dominant(db, dynamic.id)
    default_sub = subs[0].id if len(subs) == 1 else None
    active_goals = []
    archived_goals = []
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
        if goal.get("active", True):
            active_goals.append(row)
        else:
            archived_goals.append(row)

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
