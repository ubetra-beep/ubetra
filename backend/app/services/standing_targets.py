"""Standing weighted balance targets (current vs target vs trend).

Gift/unlock goals live in chastity_goals. These are ongoing balance KPIs
the Assistant Domme watches: orgasm split, lockup time, open tasks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityLockup,
    Dynamic,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
)
from .chastity import locked_segments
from .tracking_events import is_orgasm_event, orgasm_count

METRICS = {
    "orgasms_to_dominant": {
        "title": "Orgasms to keyholder",
        "unit": "count",
        "hint": "Orgasm logs for the dominant in the lookback window.",
        "default_direction": "at_least",
        "default_target": 2,
        "default_window_days": 14,
    },
    "sub_orgasms": {
        "title": "Sub orgasms",
        "unit": "count",
        "hint": "Orgasm logs for the submissive in the lookback window.",
        "default_direction": "at_most",
        "default_target": 2,
        "default_window_days": 14,
    },
    "orgasm_ratio_dom_over_sub": {
        "title": "Orgasm ratio (keyholder / sub)",
        "unit": "ratio",
        "hint": "Keyholder orgasms divided by sub orgasms in the window. 1.0 is even.",
        "default_direction": "at_least",
        "default_target": 1.0,
        "default_window_days": 14,
    },
    "lockup_hours": {
        "title": "Lockup hours",
        "unit": "hours",
        "hint": "Effective locked hours (breaks subtracted) in the window.",
        "default_direction": "at_least",
        "default_target": 48,
        "default_window_days": 14,
    },
    "percent_locked": {
        "title": "Percent locked",
        "unit": "percent",
        "hint": "Share of the window the sub spent locked.",
        "default_direction": "at_least",
        "default_target": 50,
        "default_window_days": 14,
    },
    "open_tasks": {
        "title": "Open assigned tasks",
        "unit": "count",
        "hint": "Incomplete approved tasks assigned to the sub right now (not windowed).",
        "default_direction": "at_least",
        "default_target": 3,
        "default_window_days": 7,
    },
}

DIRECTIONS = {
    "at_least": "At least the target",
    "at_most": "At most the target",
    "hold": "Hold near the target",
}

NAG_WEIGHT = 3
DEFAULT_WINDOW_DAYS = 14


def _defaults() -> dict:
    return {"targets": []}


def parse_standing_targets(raw: str | None) -> dict:
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
    rows = data.get("targets")
    if not isinstance(rows, list):
        return base
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric = row.get("metric")
        if metric not in METRICS:
            continue
        meta = METRICS[metric]
        try:
            target = float(row.get("target") if row.get("target") is not None else meta["default_target"])
        except (TypeError, ValueError):
            target = float(meta["default_target"])
        try:
            weight = int(row.get("weight") or 3)
        except (TypeError, ValueError):
            weight = 3
        weight = max(1, min(5, weight))
        try:
            window_days = int(row.get("window_days") or meta["default_window_days"])
        except (TypeError, ValueError):
            window_days = int(meta["default_window_days"])
        window_days = max(3, min(90, window_days))
        direction = row.get("direction") if row.get("direction") in DIRECTIONS else meta["default_direction"]
        cleaned.append(
            {
                "id": str(row.get("id") or uuid.uuid4()),
                "metric": metric,
                "title": (row.get("title") or meta["title"])[:80],
                "weight": weight,
                "target": target,
                "window_days": window_days,
                "direction": direction,
                "for_membership_id": row.get("for_membership_id") or None,
            }
        )
    return {"targets": cleaned}


def serialize_standing_targets(data: dict) -> str:
    parsed = parse_standing_targets(json.dumps(data if isinstance(data, dict) else {}))
    return json.dumps(parsed)


def _partners(db: Session, dynamic_id: str) -> tuple[Membership | None, Membership | None]:
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    dominant = next((m for m in memberships if m.role == PartnerRole.dominant), None)
    sub = next((m for m in memberships if m.role == PartnerRole.submissive), None)
    return dominant, sub


def _count_orgasms(db: Session, dynamic_id: str, membership_id: str, start: datetime, end: datetime) -> int:
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == membership_id,
            OrgTrackingEntry.occurred_at >= start,
            OrgTrackingEntry.occurred_at < end,
        )
        .all()
    )
    total = 0
    for entry in entries:
        if is_orgasm_event(entry.event_type) or entry.event_type in (
            OrgEventType.orgasm,
            OrgEventType.both,
        ):
            total += orgasm_count(entry)
    return total


def _locked_seconds_in_window(
    db: Session,
    dynamic_id: str,
    sub_id: str,
    start: datetime,
    end: datetime,
) -> float:
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == sub_id,
            ChastityLockup.started_at < end,
        )
        .all()
    )
    total = 0.0
    for lockup in lockups:
        if lockup.ended_at and lockup.ended_at <= start:
            continue
        for seg_start, seg_end in locked_segments(lockup, until=end):
            clipped_start = max(seg_start, start)
            clipped_end = min(seg_end, end)
            if clipped_end > clipped_start:
                total += (clipped_end - clipped_start).total_seconds()
    return total


def _open_task_count(db: Session, dynamic_id: str, sub_id: str | None) -> int:
    rows = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(
            TaskList.dynamic_id == dynamic_id,
            Task.completed_at.is_(None),
            Task.approval_status == TaskApprovalStatus.approved,
        )
        .all()
    )
    count = 0
    for task in rows:
        if getattr(task, "paused", False):
            continue
        assignee = getattr(task, "assigned_to_membership_id", None)
        if sub_id and assignee and assignee != sub_id:
            continue
        count += 1
    return count


def _last_completed_task_at(db: Session, dynamic_id: str, sub_id: str | None) -> datetime | None:
    query = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(
            TaskList.dynamic_id == dynamic_id,
            Task.completed_at.isnot(None),
            Task.approval_status == TaskApprovalStatus.approved,
        )
        .order_by(Task.completed_at.desc())
    )
    for task in query.limit(40).all():
        assignee = getattr(task, "assigned_to_membership_id", None)
        if sub_id and assignee and assignee != sub_id:
            continue
        return task.completed_at
    return None


def measure_metric(
    db: Session,
    *,
    dynamic_id: str,
    metric: str,
    window_days: int,
    sub_id: str | None,
    dominant_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()
    meta = METRICS[metric]
    window = timedelta(days=max(1, int(window_days)))
    current_start = now - window
    previous_start = current_start - window
    current = 0.0
    previous = 0.0
    unit = meta["unit"]

    if metric == "open_tasks":
        current = float(_open_task_count(db, dynamic_id, sub_id))
        previous = current
    elif metric == "orgasms_to_dominant" and dominant_id:
        current = float(_count_orgasms(db, dynamic_id, dominant_id, current_start, now))
        previous = float(_count_orgasms(db, dynamic_id, dominant_id, previous_start, current_start))
    elif metric == "sub_orgasms" and sub_id:
        current = float(_count_orgasms(db, dynamic_id, sub_id, current_start, now))
        previous = float(_count_orgasms(db, dynamic_id, sub_id, previous_start, current_start))
    elif metric == "orgasm_ratio_dom_over_sub" and dominant_id and sub_id:
        dom_now = _count_orgasms(db, dynamic_id, dominant_id, current_start, now)
        sub_now = _count_orgasms(db, dynamic_id, sub_id, current_start, now)
        dom_prev = _count_orgasms(db, dynamic_id, dominant_id, previous_start, current_start)
        sub_prev = _count_orgasms(db, dynamic_id, sub_id, previous_start, current_start)
        current = (dom_now / sub_now) if sub_now else (float(dom_now) if dom_now else 0.0)
        previous = (dom_prev / sub_prev) if sub_prev else (float(dom_prev) if dom_prev else 0.0)
    elif metric == "lockup_hours" and sub_id:
        current = _locked_seconds_in_window(db, dynamic_id, sub_id, current_start, now) / 3600
        previous = _locked_seconds_in_window(db, dynamic_id, sub_id, previous_start, current_start) / 3600
    elif metric == "percent_locked" and sub_id:
        span = window.total_seconds() or 1.0
        current = 100.0 * _locked_seconds_in_window(db, dynamic_id, sub_id, current_start, now) / span
        previous = 100.0 * _locked_seconds_in_window(db, dynamic_id, sub_id, previous_start, current_start) / span

    delta = current - previous
    if abs(delta) < 0.05 if unit in {"ratio", "percent", "hours"} else abs(delta) < 0.5:
        trend = "flat"
    elif delta > 0:
        trend = "up"
    else:
        trend = "down"

    if unit == "count":
        current_out: float | int = int(round(current))
        previous_out: float | int = int(round(previous))
    else:
        current_out = round(current, 2)
        previous_out = round(previous, 2)

    return {
        "current": current_out,
        "previous": previous_out,
        "trend": trend,
        "unit": unit,
        "window_days": window_days,
    }


def _on_target(current: float, target: float, direction: str) -> bool:
    if direction == "at_most":
        return current <= target + 1e-6
    if direction == "hold":
        slack = max(0.15 * abs(target), 0.5)
        return abs(current - target) <= slack
    return current >= target - 1e-6


def build_standing_progress(db: Session, dynamic: Dynamic) -> dict:
    data = parse_standing_targets(getattr(dynamic, "standing_targets", None))
    dominant, sub = _partners(db, dynamic.id)
    dominant_id = dominant.id if dominant else None
    sub_id = sub.id if sub else None
    catalog = [
        {
            "id": key,
            "title": meta["title"],
            "unit": meta["unit"],
            "hint": meta["hint"],
            "default_direction": meta["default_direction"],
            "default_target": meta["default_target"],
            "default_window_days": meta["default_window_days"],
        }
        for key, meta in METRICS.items()
    ]
    rows = []
    for target in data["targets"]:
        measured = measure_metric(
            db,
            dynamic_id=dynamic.id,
            metric=target["metric"],
            window_days=target["window_days"],
            sub_id=sub_id,
            dominant_id=dominant_id,
        )
        current = float(measured["current"])
        goal = float(target["target"])
        met = _on_target(current, goal, target["direction"])
        rows.append(
            {
                **target,
                **measured,
                "metric_title": METRICS[target["metric"]]["title"],
                "direction_label": DIRECTIONS[target["direction"]],
                "met": met,
                "nag": int(target["weight"]) >= NAG_WEIGHT and not met,
            }
        )
    last_done = _last_completed_task_at(db, dynamic.id, sub_id)
    return {
        "targets": rows,
        "catalog": catalog,
        "directions": [{"id": key, "title": label} for key, label in DIRECTIONS.items()],
        "sub_membership_id": sub_id,
        "dominant_membership_id": dominant_id,
        "open_task_count": _open_task_count(db, dynamic.id, sub_id),
        "last_completed_task_at": last_done.isoformat() + "Z" if last_done else None,
    }


def format_standing_targets_for_context(db: Session, dynamic: Dynamic) -> str:
    progress = build_standing_progress(db, dynamic)
    lines = []
    for row in progress.get("targets") or []:
        lines.append(
            f"- {row.get('title')} (weight {row.get('weight')}/5, {row.get('direction')} {row.get('target')} "
            f"{row.get('unit')} over {row.get('window_days')}d): current {row.get('current')}, "
            f"previous window {row.get('previous')}, trend {row.get('trend')}"
            + (" — OFF TARGET" if not row.get("met") else "")
        )
    if not lines:
        return ""
    return "Standing balance targets (keyholder weighted goals):\n" + "\n".join(lines)
