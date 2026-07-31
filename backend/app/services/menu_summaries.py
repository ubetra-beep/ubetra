from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import (
    ActStatus,
    ChastityBreak,
    ChastityBreakType,
    ChastityLockup,
    LockupStatus,
    Membership,
    OrgTrackingEntry,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
)
from .chastity import active_lockup, effective_locked_seconds, lockup_duration_seconds
from .tracking import format_duration


def _days_since(when: datetime | None, *, now: datetime | None = None) -> int | None:
    if when is None:
        return None
    now = now or datetime.utcnow()
    return max(0, (now.date() - when.date()).days)


def _days_label(days: int | None) -> str:
    if days is None:
        return "no log yet"
    if days == 0:
        return "today"
    return f"{days}d"


def _last_orgasm_at(db: Session, dynamic_id: str, membership_id: str) -> datetime | None:
    row = (
        db.query(OrgTrackingEntry)
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == membership_id,
            OrgTrackingEntry.event_type.in_(["orgasm", "both"]),
        )
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .first()
    )
    return row.occurred_at if row else None


def _last_play_or_ruin_at(db: Session, dynamic_id: str, membership_id: str) -> datetime | None:
    candidates: list[datetime] = []
    play_row = (
        db.query(OrgTrackingEntry)
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == membership_id,
            OrgTrackingEntry.event_type.in_(["no_orgasm", "sex"]),
        )
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .first()
    )
    if play_row:
        candidates.append(play_row.occurred_at)

    ruin_types = {ChastityBreakType.authorized_denial, ChastityBreakType.authorized_ruin}
    breaks = (
        db.query(ChastityBreak)
        .join(ChastityLockup, ChastityBreak.lockup_id == ChastityLockup.id)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == membership_id,
            ChastityBreak.break_type.in_(ruin_types),
        )
        .order_by(ChastityBreak.started_at.desc())
        .all()
    )
    candidates.extend(brk.started_at for brk in breaks)
    return max(candidates) if candidates else None


def _days_since_full_o(db: Session, dynamic_id: str, membership: Membership) -> int | None:
    now = datetime.utcnow()
    last_o = _last_orgasm_at(db, dynamic_id, membership.id)
    lockup = active_lockup(db, dynamic_id, membership.id)
    if lockup and (last_o is None or last_o < lockup.started_at):
        return _days_since(lockup.started_at, now=now)
    return _days_since(last_o, now=now)


def org_tracking_summary(db: Session, dynamic_id: str) -> str:
    memberships = (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id)
        .order_by(Membership.role.desc())
        .all()
    )
    if not memberships:
        return "No partners yet"

    parts: list[str] = []
    for member in memberships:
        days = _days_since(_last_orgasm_at(db, dynamic_id, member.id))
        parts.append(f"{member.display_name}: {_days_label(days)} since last O")

    for sub in memberships:
        if sub.role != PartnerRole.submissive or not sub.chastity_enabled:
            continue
        play_ruin = _days_since(_last_play_or_ruin_at(db, dynamic_id, sub.id))
        full_o = _days_since_full_o(db, dynamic_id, sub)
        parts.append(
            f"{sub.display_name} (chastity): {_days_label(play_ruin)} play/ruin · {_days_label(full_o)} full O"
        )

    return " · ".join(parts)


def _locked_since_last_break(lockup: ChastityLockup, now: datetime) -> float:
    finished_breaks = [
        b
        for b in lockup.breaks
        if b.ended_at is not None
        and b.ended_at > b.started_at
        and b.ended_at >= lockup.started_at
        and (lockup.ended_at is None or b.started_at <= lockup.ended_at)
    ]
    if not finished_breaks:
        return effective_locked_seconds(lockup, until=now)
    last_end = max(b.ended_at for b in finished_breaks if b.ended_at)
    # Never count "since" from before this lockup began
    last_end = max(last_end, lockup.started_at)
    open_break = next((b for b in lockup.breaks if b.ended_at is None), None)
    if open_break:
        return effective_locked_seconds(lockup, until=open_break.started_at)
    until = now
    if lockup.ended_at:
        until = min(now, lockup.ended_at)
    if until <= last_end:
        return 0.0
    return max(0.0, lockup_duration_seconds(last_end, until) - _break_overlap_since(lockup, last_end, until))


def _break_overlap_since(lockup: ChastityLockup, since: datetime, until: datetime) -> float:
    total = 0.0
    for brk in lockup.breaks:
        if brk.ended_at is None or brk.ended_at <= brk.started_at:
            continue
        start = max(brk.started_at, since, lockup.started_at)
        end = min(brk.ended_at, until)
        if lockup.ended_at:
            end = min(end, lockup.ended_at)
        if end > start:
            total += lockup_duration_seconds(start, end)
    return total


def chastity_summary(db: Session, dynamic_id: str) -> str:
    subs = (
        db.query(Membership)
        .filter(
            Membership.dynamic_id == dynamic_id,
            Membership.role == PartnerRole.submissive,
            Membership.chastity_enabled.is_(True),
        )
        .all()
    )
    if not subs:
        return "Not configured for submissive"

    now = datetime.utcnow()
    parts: list[str] = []
    for sub in subs:
        lockup = active_lockup(db, dynamic_id, sub.id)
        if not lockup:
            last_ended = (
                db.query(ChastityLockup)
                .filter(
                    ChastityLockup.dynamic_id == dynamic_id,
                    ChastityLockup.for_membership_id == sub.id,
                    ChastityLockup.status == LockupStatus.ended,
                )
                .order_by(ChastityLockup.ended_at.desc())
                .first()
            )
            if last_ended and last_ended.ended_at:
                free_days = _days_since(last_ended.ended_at, now=now)
                parts.append(f"{sub.display_name}: free {_days_label(free_days)}")
            else:
                parts.append(f"{sub.display_name}: not locked")
            continue

        open_break = next((b for b in lockup.breaks if b.ended_at is None), None)
        total_locked = effective_locked_seconds(lockup, until=now)
        since_break = _locked_since_last_break(lockup, now)
        if open_break:
            break_secs = lockup_duration_seconds(open_break.started_at, now)
            parts.append(
                f"{sub.display_name}: {format_duration(total_locked)} locked since full release · "
                f"on break {format_duration(break_secs)}"
            )
        else:
            parts.append(
                f"{sub.display_name}: {format_duration(total_locked)} locked since full release · "
                f"{format_duration(since_break)} since last temp release"
            )

    return " · ".join(parts) if parts else "No lockup history yet"


def tasks_summary(db: Session, dynamic_id: str) -> str:
    pending = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(
            TaskList.dynamic_id == dynamic_id,
            Task.approval_status == TaskApprovalStatus.pending,
            Task.completed_at.is_(None),
        )
        .count()
    )
    if pending:
        return f"{pending} pending approval"
    return "Ordered lists for your sub"


def acts_summary(db: Session, dynamic: object) -> str:
    from ..models import ActOfSubmission, Dynamic
    from .act_catalog import parse_act_catalog

    if not isinstance(dynamic, Dynamic):
        return "AI-generated personal acts"

    catalog = parse_act_catalog(dynamic.act_categories)
    if catalog:
        titles = [c["title"] for c in catalog[:3]]
        suffix = f" +{len(catalog) - 3} more" if len(catalog) > 3 else ""
        return ", ".join(titles) + suffix

    active_act = (
        db.query(ActOfSubmission)
        .filter(
            ActOfSubmission.dynamic_id == dynamic.id,
            ActOfSubmission.status == ActStatus.active,
        )
        .first()
    )
    if active_act:
        return "Act in progress"
    return "Generate act types from your interviews"


def menu_summaries(db: Session, dynamic_id: str) -> dict[str, str]:
    from ..models import Dynamic

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        return {}

    return {
        "org_tracking": org_tracking_summary(db, dynamic_id),
        "chastity": chastity_summary(db, dynamic_id),
        "tasks": tasks_summary(db, dynamic_id),
        "acts": acts_summary(db, dynamic),
    }
