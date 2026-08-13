from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Health Connect often splits one night into sessions a couple of hours apart.
# A night ends once the person has been awake for more than six hours.
NIGHT_AWAKE = timedelta(hours=6)


@dataclass
class SleepNight:
    start_at: datetime
    end_at: datetime
    duration_min: int
    night_date: str
    sessions: list


def merged_sleep_intervals(sessions) -> list[tuple[datetime, datetime]]:
    intervals = sorted(
        ((s.start_at, s.end_at) for s in sessions),
        key=lambda pair: pair[0],
    )
    merged: list[list[datetime]] = []
    for start, end in intervals:
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def duration_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    return sum(int((end - start).total_seconds() // 60) for start, end in intervals)


def group_sleep_nights(sessions: list) -> list[SleepNight]:
    rows = sorted(sessions, key=lambda s: s.start_at)
    clusters: list[list] = []
    current: list = []
    for session in rows:
        if not current:
            current = [session]
            continue
        gap = session.start_at - current[-1].end_at
        if gap <= NIGHT_AWAKE:
            current.append(session)
        else:
            clusters.append(current)
            current = [session]
    if current:
        clusters.append(current)

    nights: list[SleepNight] = []
    for cluster in clusters:
        intervals = merged_sleep_intervals(cluster)
        start = min(s.start_at for s in cluster)
        end = max(s.end_at for s in cluster)
        minutes = duration_minutes(intervals)
        if minutes <= 0:
            minutes = sum(int(getattr(s, "duration_min", 0) or 0) for s in cluster)
        nights.append(
            SleepNight(
                start_at=start,
                end_at=end,
                duration_min=minutes,
                night_date=end.date().isoformat(),
                sessions=cluster,
            )
        )
    return nights


def group_sleep_nights_by_subject(sessions: list) -> dict[str, list[SleepNight]]:
    by_subject: dict[str, list] = {}
    for session in sessions:
        by_subject.setdefault(session.subject_membership_id, []).append(session)
    return {mid: group_sleep_nights(rows) for mid, rows in by_subject.items()}
