from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityBreak,
    ChastityBreakType,
    ChastityLockup,
    ChastityRecordType,
    LockupStatus,
    Membership,
    PartnerRole,
)
from .tracking import format_duration, lockup_duration_seconds


def as_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetimes for SQLite storage / comparisons (always naive UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

MAX_LOCK_PRESETS: list[dict[str, str | int | None]] = [
    {"label": "8h", "hours": 8},
    {"label": "1d", "hours": 24},
    {"label": "3d", "hours": 72},
    {"label": "7d", "hours": 168},
    {"label": "14d", "hours": 336},
    {"label": "30d", "hours": 720},
    {"label": "90d", "hours": 2160},
    {"label": "No limit", "hours": None},
]

BREAK_TYPE_LABELS: dict[str, str] = {
    ChastityBreakType.authorized_hygiene.value: "Hygiene",
    ChastityBreakType.authorized_sleep.value: "Sleep",
    ChastityBreakType.authorized_play.value: "Play",
    ChastityBreakType.authorized_denial.value: "Denial / edging",
    ChastityBreakType.authorized_ruin.value: "Ruined orgasm",
    ChastityBreakType.authorized_other.value: "Other (authorized)",
    ChastityBreakType.authorized_undecided.value: "Undecided",
    ChastityBreakType.emergency_hygiene.value: "Hygiene (emergency)",
    ChastityBreakType.emergency_medical.value: "Medical emergency",
    ChastityBreakType.emergency_discomfort.value: "Discomfort",
    ChastityBreakType.emergency_security.value: "Security / safety",
    ChastityBreakType.emergency_other.value: "Other emergency",
    ChastityBreakType.unauthorized_misbehavior.value: "Misbehavior",
}

EMERGENCY_BREAK_TYPES = {
    ChastityBreakType.emergency_hygiene,
    ChastityBreakType.emergency_medical,
    ChastityBreakType.emergency_discomfort,
    ChastityBreakType.emergency_security,
    ChastityBreakType.emergency_other,
    ChastityBreakType.unauthorized_misbehavior,
}


def chastity_subs(memberships: list[Membership]) -> list[Membership]:
    return [
        m
        for m in memberships
        if m.role == PartnerRole.submissive and m.chastity_enabled
    ]


def require_chastity_sub(target: Membership) -> None:
    if target.role != PartnerRole.submissive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chastity lockups can only be tracked for submissive partners.",
        )
    if not target.chastity_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chastity is not enabled for this submissive. Enable it in chastity settings first.",
        )


def is_dominant(membership: Membership) -> bool:
    return membership.role == PartnerRole.dominant


def active_lockup(
    db: Session, dynamic_id: str, for_membership_id: str
) -> ChastityLockup | None:
    return (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == for_membership_id,
            ChastityLockup.status == LockupStatus.active,
        )
        .first()
    )


def active_break(lockup: ChastityLockup) -> ChastityBreak | None:
    for brk in lockup.breaks:
        if brk.ended_at is None:
            return brk
    return None


def _valid_break_window(
    brk: ChastityBreak, *, window_start: datetime, window_end: datetime
) -> tuple[datetime, datetime] | None:
    """Clip a break to the lockup window; drop inverted / empty ranges."""
    start = brk.started_at
    end = brk.ended_at if brk.ended_at is not None else window_end
    if end <= start:
        return None
    start = max(start, window_start)
    end = min(end, window_end)
    if end <= start:
        return None
    return start, end


def break_seconds(lockup: ChastityLockup, *, until: datetime | None = None) -> float:
    end_cap = until or datetime.utcnow()
    lock_end = lockup.ended_at or end_cap
    if lockup.ended_at and until:
        lock_end = min(lockup.ended_at, until)
    elif until:
        lock_end = until
    if lock_end <= lockup.started_at:
        return 0.0
    total = 0.0
    for brk in lockup.breaks:
        window = _valid_break_window(brk, window_start=lockup.started_at, window_end=lock_end)
        if window:
            total += lockup_duration_seconds(window[0], window[1])
    return total


def effective_locked_seconds(lockup: ChastityLockup, *, until: datetime | None = None) -> float:
    end_cap = until or datetime.utcnow()
    end = lockup.ended_at or end_cap
    if until is not None:
        end = min(end, until)
    if end <= lockup.started_at:
        return 0.0
    gross = lockup_duration_seconds(lockup.started_at, end)
    return max(0.0, gross - break_seconds(lockup, until=end))


def locked_segments(
    lockup: ChastityLockup, *, until: datetime | None = None
) -> list[tuple[datetime, datetime]]:
    """Non-overlapping locked intervals inside one lockup (breaks carved out)."""
    end_cap = until or datetime.utcnow()
    end = lockup.ended_at or end_cap
    if until is not None:
        end = min(end, until)
    if end <= lockup.started_at:
        return []

    breaks: list[tuple[datetime, datetime]] = []
    for brk in lockup.breaks:
        window = _valid_break_window(brk, window_start=lockup.started_at, window_end=end)
        if window:
            breaks.append(window)
    breaks.sort(key=lambda w: w[0])

    segments: list[tuple[datetime, datetime]] = []
    cursor = lockup.started_at
    for b_start, b_end in breaks:
        if b_start > cursor:
            segments.append((cursor, b_start))
        cursor = max(cursor, b_end)
    if cursor < end:
        segments.append((cursor, end))
    return segments


def merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda w: w[0])
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def total_merged_locked_seconds(
    lockups: list[ChastityLockup], *, until: datetime | None = None
) -> float:
    """Union of locked time across lockups — overlaps never count twice."""
    end_cap = until or datetime.utcnow()
    intervals: list[tuple[datetime, datetime]] = []
    for lockup in lockups:
        intervals.extend(locked_segments(lockup, until=end_cap))
    return sum(lockup_duration_seconds(a, b) for a, b in merge_intervals(intervals))


def intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    a_start = as_naive_utc(a_start) or a_start
    a_end = as_naive_utc(a_end) or a_end
    b_start = as_naive_utc(b_start) or b_start
    b_end = as_naive_utc(b_end) or b_end
    return a_start < b_end and b_start < a_end


def assert_no_lockup_overlap(
    db: Session,
    *,
    dynamic_id: str,
    for_membership_id: str,
    started_at: datetime,
    ended_at: datetime | None,
    exclude_id: str | None = None,
) -> None:
    started_at = as_naive_utc(started_at) or datetime.utcnow()
    ended_at = as_naive_utc(ended_at)
    rows = (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == for_membership_id,
        )
        .all()
    )
    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        a_end = ended_at or datetime.max.replace(year=9999)
        b_start = as_naive_utc(row.started_at) or row.started_at
        b_end = as_naive_utc(row.ended_at) or datetime.max.replace(year=9999)
        if intervals_overlap(started_at, a_end, b_start, b_end):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This lockup overlaps an existing period "
                    f"({row.started_at.isoformat()} – "
                    f"{row.ended_at.isoformat() if row.ended_at else 'ongoing'}). "
                    "Adjust the times so periods do not overlap."
                ),
            )


def validate_break_times(
    lockup: ChastityLockup,
    *,
    started_at: datetime,
    ended_at: datetime | None,
) -> None:
    started_at = as_naive_utc(started_at) or started_at
    ended_at = as_naive_utc(ended_at)
    lock_start = as_naive_utc(lockup.started_at) or lockup.started_at
    if started_at < lock_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Break cannot start before the lockup.",
        )
    lock_end = as_naive_utc(lockup.ended_at)
    if lock_end and started_at > lock_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Break cannot start after the lockup ended.",
        )
    if ended_at is not None:
        if ended_at <= started_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Break end must be after break start.",
            )
        if lock_end and ended_at > lock_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Break cannot end after the lockup ended.",
            )


def validate_planned_end(target: Membership, started_at: datetime, planned_end_at: datetime | None) -> None:
    started_at = as_naive_utc(started_at) or started_at
    planned_end_at = as_naive_utc(planned_end_at)
    if planned_end_at is None:
        return
    if planned_end_at <= started_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Planned end must be after the lockup start time.",
        )
    if target.chastity_max_lock_hours is not None:
        max_end = started_at + timedelta(hours=target.chastity_max_lock_hours)
        if planned_end_at > max_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Planned end exceeds the maximum lock time ({target.chastity_max_lock_hours}h).",
            )


def partner_state(
    db: Session, dynamic_id: str, membership: Membership
) -> dict:
    if membership.role != PartnerRole.submissive or not membership.chastity_enabled:
        return {
            "membership_id": membership.id,
            "name": membership.display_name,
            "role": membership.role.value,
            "chastity_enabled": membership.chastity_enabled,
            "chastity_max_lock_hours": membership.chastity_max_lock_hours,
            "state": "not_tracked",
            "currently_locked": False,
            "on_break": False,
            "current_duration_label": None,
            "break_duration_label": None,
            "free_duration_label": None,
            "active_lockup_id": None,
            "active_break_id": None,
            "planned_end_at": None,
            "timer_overdue": False,
            "percent_locked_all_time": 0.0,
            "total_locked_label": "0m",
            "average_lockup_label": None,
            "longest_lockup_label": None,
            "lockup_count": 0,
        }

    now = datetime.utcnow()
    lockup = active_lockup(db, dynamic_id, membership.id)
    brk = active_break(lockup) if lockup else None

    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == membership.id,
        )
        .order_by(ChastityLockup.started_at.asc())
        .all()
    )

    total_locked = 0.0
    longest = 0.0
    completed_durations: list[float] = []
    tracking_since: datetime | None = None

    for period in lockups:
        if tracking_since is None or period.started_at < tracking_since:
            tracking_since = period.started_at
        locked = effective_locked_seconds(period, until=now)
        longest = max(longest, locked)
        if period.status == LockupStatus.ended:
            completed_durations.append(locked)

    # Union locked intervals so overlapping / bad historical periods cannot exceed 100%
    total_locked = total_merged_locked_seconds(lockups, until=now)

    span_seconds = 0.0
    if tracking_since:
        span_seconds = lockup_duration_seconds(tracking_since, now)
    raw_pct = (total_locked / span_seconds) * 100 if span_seconds > 0 else 0.0
    percent_locked = round(min(100.0, max(0.0, raw_pct)), 1)

    last_ended = next(
        (p for p in reversed(lockups) if p.status == LockupStatus.ended and p.ended_at),
        None,
    )
    free_duration_label = None
    if not lockup and last_ended and last_ended.ended_at:
        free_duration_label = format_duration(
            lockup_duration_seconds(last_ended.ended_at, now)
        )

    state = "unlocked"
    current_duration_label = None
    break_duration_label = None
    if lockup:
        if brk:
            state = "on_break"
            break_duration_label = format_duration(
                lockup_duration_seconds(brk.started_at, now)
            )
        else:
            state = "locked"
            current_duration_label = format_duration(
                effective_locked_seconds(lockup, until=now)
            )

    avg_label = None
    if completed_durations:
        avg_label = format_duration(sum(completed_durations) / len(completed_durations))

    planned_end_at = lockup.planned_end_at if lockup else None
    timer_overdue = bool(
        lockup
        and planned_end_at
        and planned_end_at <= now
        and lockup.status == LockupStatus.active
    )

    return {
        "membership_id": membership.id,
        "name": membership.display_name,
        "role": membership.role.value,
        "chastity_enabled": True,
        "chastity_max_lock_hours": membership.chastity_max_lock_hours,
        "state": state,
        "currently_locked": lockup is not None and brk is None,
        "on_break": brk is not None,
        "current_duration_label": current_duration_label,
        "break_duration_label": break_duration_label,
        "free_duration_label": free_duration_label,
        "active_lockup_id": lockup.id if lockup else None,
        "active_break_id": brk.id if brk else None,
        "planned_end_at": planned_end_at,
        "timer_overdue": timer_overdue,
        "percent_locked_all_time": percent_locked,
        "total_locked_label": format_duration(total_locked),
        "average_lockup_label": avg_label,
        "longest_lockup_label": format_duration(longest) if longest else None,
        "lockup_count": len(lockups),
    }


def partner_chastity_stats(
    db: Session, dynamic_id: str, membership: Membership, *, days: int = 90
) -> dict:
    overview = partner_state(db, dynamic_id, membership)
    if membership.role != PartnerRole.submissive:
        return {
            "membership_id": membership.id,
            "name": membership.display_name,
            "chastity_enabled": False,
            "currently_locked": False,
            "on_break": False,
            "current_duration_label": None,
            "total_locked_days_90d": 0.0,
            "longest_lockup_days_90d": 0.0,
            "lockup_count_90d": 0,
            "percent_locked_all_time": 0.0,
        }

    since = datetime.utcnow() - timedelta(days=days)
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id == membership.id,
            ChastityLockup.started_at >= since,
        )
        .order_by(ChastityLockup.started_at.desc())
        .all()
    )

    total_seconds = 0.0
    longest_seconds = 0.0
    now = datetime.utcnow()
    for lockup in lockups:
        end = lockup.ended_at or now
        duration = effective_locked_seconds(lockup, until=end)
        total_seconds += duration
        longest_seconds = max(longest_seconds, duration)

    return {
        "membership_id": membership.id,
        "name": membership.display_name,
        "chastity_enabled": membership.chastity_enabled,
        "currently_locked": overview["currently_locked"],
        "on_break": overview["on_break"],
        "current_duration_label": overview["current_duration_label"],
        "total_locked_days_90d": round(total_seconds / 86400, 1),
        "longest_lockup_days_90d": round(longest_seconds / 86400, 1),
        "lockup_count_90d": len(lockups),
        "percent_locked_all_time": overview["percent_locked_all_time"],
    }
