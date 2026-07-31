from __future__ import annotations

from datetime import datetime, timedelta

from ..models import OrgTrackingEntry

SESSION_LINK_GAP = timedelta(hours=1)


def entry_time_range(entry: OrgTrackingEntry) -> tuple[datetime, datetime]:
    start = entry.occurred_at
    if entry.ended_at and entry.ended_at > start:
        end = entry.ended_at
    elif entry.duration_minutes:
        end = start + timedelta(minutes=entry.duration_minutes)
    else:
        end = start
    return start, end


def _ranges_linked(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
    *,
    gap: timedelta = SESSION_LINK_GAP,
) -> bool:
    if a_start <= b_end and b_start <= a_end:
        return True
    if a_end <= b_start:
        return (b_start - a_end) <= gap
    return (a_start - b_end) <= gap


def group_tracking_sessions(
    entries: list[OrgTrackingEntry],
) -> tuple[dict[str, str], list[dict]]:
    if not entries:
        return {}, []

    sorted_entries = sorted(entries, key=lambda e: entry_time_range(e)[0])
    parent = {entry.id: entry.id for entry in sorted_entries}

    def find(entry_id: str) -> str:
        while parent[entry_id] != entry_id:
            parent[entry_id] = parent[parent[entry_id]]
            entry_id = parent[entry_id]
        return entry_id

    def union(a_id: str, b_id: str) -> None:
        root_a = find(a_id)
        root_b = find(b_id)
        if root_a != root_b:
            parent[root_b] = root_a

    ranges = {entry.id: entry_time_range(entry) for entry in sorted_entries}
    for i, left in enumerate(sorted_entries):
        l_start, l_end = ranges[left.id]
        for right in sorted_entries[i + 1 :]:
            r_start, r_end = ranges[right.id]
            if r_start > l_end and (r_start - l_end) > SESSION_LINK_GAP:
                break
            if _ranges_linked(l_start, l_end, r_start, r_end):
                union(left.id, right.id)

    clusters: dict[str, list[OrgTrackingEntry]] = {}
    for entry in sorted_entries:
        root = find(entry.id)
        clusters.setdefault(root, []).append(entry)

    entry_to_session: dict[str, str] = {}
    sessions: list[dict] = []
    for cluster_entries in clusters.values():
        cluster_entries.sort(key=lambda e: e.occurred_at)
        session_id = cluster_entries[0].id
        starts = [ranges[e.id][0] for e in cluster_entries]
        ends = [ranges[e.id][1] for e in cluster_entries]
        for entry in cluster_entries:
            entry_to_session[entry.id] = session_id
        sessions.append(
            {
                "session_id": session_id,
                "started_at": min(starts),
                "ended_at": max(ends),
                "entry_ids": [e.id for e in cluster_entries],
                "entry_count": len(cluster_entries),
            }
        )

    sessions.sort(key=lambda s: s["started_at"], reverse=True)
    return entry_to_session, sessions
