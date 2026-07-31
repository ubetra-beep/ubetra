from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityLockup,
    LockupStatus,
    Membership,
    OrgTrackingEntry,
    PartnerRole,
)
from ..schemas import HistoryPartnerSummary, HistoryWeekBucket
from .chastity import chastity_subs, effective_locked_seconds, partner_state
from .tags import entry_matches_selected_tags, tags_to_list
from .tracking_events import has_ruined_orgasm_tag, is_orgasm_event, is_play_event, orgasm_count


def _week_starts(since: datetime, until: datetime) -> list[datetime]:
    cursor = since.date()
    end_date = until.date()
    starts: list[datetime] = []
    while cursor <= end_date:
        starts.append(datetime.combine(cursor, datetime.min.time()))
        cursor += timedelta(days=7)
    return starts


def locked_seconds_in_range(
    lockup: ChastityLockup, range_start: datetime, range_end: datetime
) -> float:
    start = max(lockup.started_at, range_start)
    end = min(lockup.ended_at or range_end, range_end)
    if end <= start:
        return 0.0
    gross = (end - start).total_seconds()
    break_total = 0.0
    for brk in lockup.breaks:
        b_start = max(brk.started_at, start)
        b_end = min(brk.ended_at or end, end)
        if b_end > b_start:
            break_total += (b_end - b_start).total_seconds()
    return max(0.0, gross - break_total)


def build_history_dashboard(
    db: Session,
    dynamic_id: str,
    memberships: list[Membership],
    *,
    days: int = 90,
    selected_tags: list[str] | None = None,
) -> dict:
    selected_tags = selected_tags or []
    since = datetime.utcnow() - timedelta(days=days)
    now = datetime.utcnow()
    membership_map = {m.id: m for m in memberships}
    tracked_subs = chastity_subs(memberships)

    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.occurred_at >= since,
        )
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .all()
    )
    filtered_entries = [
        entry
        for entry in entries
        if entry_matches_selected_tags(entry, selected_tags)
    ]

    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id.in_([s.id for s in tracked_subs] or [""]),
            ChastityLockup.started_at < now,
        )
        .all()
    )
    if not tracked_subs:
        lockups = []

    weekly_buckets: list[HistoryWeekBucket] = []
    for week_start in _week_starts(since, now):
        week_end = min(week_start + timedelta(days=7), now + timedelta(seconds=1))
        orgasms_by_partner: dict[str, int] = {}
        chastity_locked_pct: dict[str, float] = {}
        durations: dict[str, list[int]] = {}
        play_by_partner: dict[str, int] = {}
        ruined_by_partner: dict[str, int] = {}

        for membership in memberships:
            orgasms_by_partner[membership.id] = 0
            play_by_partner[membership.id] = 0
            ruined_by_partner[membership.id] = 0
            durations[membership.id] = []

        for entry in filtered_entries:
            if week_start <= entry.occurred_at < week_end:
                mid = entry.for_membership_id
                if is_orgasm_event(entry.event_type):
                    orgasms_by_partner[mid] = orgasms_by_partner.get(mid, 0) + orgasm_count(entry)
                    rows = entry.orgasms or []
                    if rows:
                        ruined_by_partner[mid] = ruined_by_partner.get(mid, 0) + sum(
                            1 for row in rows if has_ruined_orgasm_tag(tags_to_list(row.tags))
                        )
                    elif has_ruined_orgasm_tag(tags_to_list(entry.tags)):
                        ruined_by_partner[mid] = ruined_by_partner.get(mid, 0) + 1
                if is_play_event(entry.event_type):
                    play_by_partner[mid] = play_by_partner.get(mid, 0) + 1
                if entry.duration_minutes is not None:
                    durations[mid].append(entry.duration_minutes)

        week_seconds = max(1.0, (week_end - week_start).total_seconds())
        for sub in tracked_subs:
            locked_seconds = 0.0
            for lockup in lockups:
                if lockup.for_membership_id != sub.id:
                    continue
                locked_seconds += locked_seconds_in_range(lockup, week_start, week_end)
            chastity_locked_pct[sub.id] = round(min(100.0, (locked_seconds / week_seconds) * 100), 1)

        weekly_buckets.append(
            HistoryWeekBucket(
                label=week_start.strftime("%b %d"),
                start=week_start,
                end=week_end,
                orgasms_by_partner=orgasms_by_partner,
                chastity_locked_pct_by_partner=chastity_locked_pct,
                avg_duration_by_partner={
                    mid: round(sum(vals) / len(vals), 1) if vals else None
                    for mid, vals in durations.items()
                },
                play_by_partner=play_by_partner,
                ruined_by_partner=ruined_by_partner,
            )
        )

    partner_summaries: list[HistoryPartnerSummary] = []
    org_totals: dict[str, int] = {}
    for membership in memberships:
        org_count = sum(
            orgasm_count(entry)
            for entry in filtered_entries
            if entry.for_membership_id == membership.id
            and is_orgasm_event(entry.event_type)
        )
        play_count = sum(
            1
            for entry in filtered_entries
            if entry.for_membership_id == membership.id
            and is_play_event(entry.event_type)
        )
        dur_vals = [
            e.duration_minutes
            for e in filtered_entries
            if e.for_membership_id == membership.id and e.duration_minutes is not None
        ]
        org_totals[membership.id] = org_count
        pct_locked = None
        if membership.chastity_enabled and membership.role == PartnerRole.submissive:
            pct_locked = partner_state(db, dynamic_id, membership)["percent_locked_all_time"]
        partner_summaries.append(
            HistoryPartnerSummary(
                membership_id=membership.id,
                name=membership.display_name,
                role=membership.role.value,
                orgasm_count=org_count,
                play_count=play_count,
                avg_duration_minutes=round(sum(dur_vals) / len(dur_vals), 1) if dur_vals else None,
                chastity_enabled=membership.chastity_enabled,
                percent_locked=pct_locked,
            )
        )

    values = list(org_totals.values())
    comparison_label = "No orgasms logged in this period"
    if values and max(values) > 0:
        names = {m.id: m.display_name for m in memberships}
        leader_id = max(org_totals, key=org_totals.get)
        leader = org_totals[leader_id]
        other_total = sum(v for k, v in org_totals.items() if k != leader_id)
        if leader > other_total and other_total == 0:
            comparison_label = f"{names[leader_id]}: {leader} orgasms · partner: 0"
        elif leader != other_total:
            comparison_label = (
                f"{names[leader_id]} leads {leader}–{other_total} orgasms in last {days} days"
            )
        else:
            comparison_label = f"Tied at {leader} orgasms each in last {days} days"

    available_tags: set[str] = set()
    for entry in entries:
        available_tags.update(tags_to_list(entry.tags))

    return {
        "days": days,
        "selected_tags": selected_tags,
        "available_tags": sorted(available_tags),
        "partners": partner_summaries,
        "comparison_label": comparison_label,
        "weekly_buckets": weekly_buckets,
        "org_entries": filtered_entries,
        "chastity_lockups": lockups,
        "chastity_any_enabled": bool(tracked_subs),
        "membership_map": membership_map,
    }
