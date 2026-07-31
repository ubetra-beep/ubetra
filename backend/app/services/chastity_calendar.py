from __future__ import annotations

from datetime import date, datetime, timedelta

from ..models import ChastityLockup
from .history_dashboard import locked_seconds_in_range

MAX_BREAK_FOR_FULL_DAY_SECONDS = 20 * 60
FULL_DAY_SECONDS = 24 * 3600
PARTIAL_LOCKED_SECONDS = 2 * 3600


def _break_seconds_in_range(
    lockup: ChastityLockup, range_start: datetime, range_end: datetime
) -> float:
    total = 0.0
    for brk in lockup.breaks:
        b_start = max(brk.started_at, range_start)
        b_end = min(brk.ended_at or range_end, range_end)
        if b_end > b_start:
            total += (b_end - b_start).total_seconds()
    return total


def _break_over_limit_in_range(
    lockup: ChastityLockup, range_start: datetime, range_end: datetime
) -> bool:
    for brk in lockup.breaks:
        b_start = max(brk.started_at, range_start)
        b_end = min(brk.ended_at or range_end, range_end)
        if b_end > b_start and (b_end - b_start).total_seconds() > MAX_BREAK_FOR_FULL_DAY_SECONDS:
            return True
    return False


def window_qualifies_as_full_day(
    lockup: ChastityLockup, window_start: datetime, window_end: datetime
) -> bool:
    if _break_over_limit_in_range(lockup, window_start, window_end):
        return False
    locked = locked_seconds_in_range(lockup, window_start, window_end)
    return locked >= FULL_DAY_SECONDS - 1


def _resume_after_failed_window(
    lockup: ChastityLockup, window_start: datetime, window_end: datetime
) -> datetime:
    for brk in sorted(lockup.breaks, key=lambda b: b.started_at):
        b_start = max(brk.started_at, window_start)
        b_end = min(brk.ended_at or window_end, window_end)
        if b_end <= b_start:
            continue
        if (b_end - b_start).total_seconds() > MAX_BREAK_FOR_FULL_DAY_SECONDS:
            if brk.ended_at:
                return max(brk.ended_at, window_start)
            return window_end
    return window_start + timedelta(hours=1)


def rolling_full_day_windows(
    lockup: ChastityLockup, *, until: datetime
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    end_cap = min(lockup.ended_at or until, until)
    cursor = lockup.started_at
    while cursor + timedelta(hours=24) <= end_cap:
        window_end = cursor + timedelta(hours=24)
        if window_qualifies_as_full_day(lockup, cursor, window_end):
            windows.append((cursor, window_end))
            cursor = window_end
        else:
            cursor = _resume_after_failed_window(lockup, cursor, window_end)
    return windows


def calendar_day_status(
    lockups: list[ChastityLockup],
    membership_id: str,
    day: date,
    *,
    period_end: datetime,
) -> tuple[str, int]:
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    range_end = min(day_end, period_end + timedelta(seconds=1))

    locked = 0.0
    for lockup in lockups:
        if lockup.for_membership_id != membership_id:
            continue
        locked += locked_seconds_in_range(lockup, day_start, range_end)
        if _break_over_limit_in_range(lockup, day_start, range_end):
            if locked >= PARTIAL_LOCKED_SECONDS:
                return "partial", int(locked)
            return "none", int(locked)

    if locked >= FULL_DAY_SECONDS - 1:
        return "full", int(locked)
    if locked >= PARTIAL_LOCKED_SECONDS:
        return "partial", int(locked)
    return "none", int(locked)


def count_rolling_full_days(
    lockups: list[ChastityLockup], membership_id: str, *, until: datetime
) -> int:
    total = 0
    for lockup in lockups:
        if lockup.for_membership_id != membership_id:
            continue
        total += len(rolling_full_day_windows(lockup, until=until))
    return total
