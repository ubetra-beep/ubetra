from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
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
from .tracking_events import has_ruined_orgasm_tag, is_orgasm_event, is_play_event


def _span_label(days: int) -> str:
    if days >= 45:
        months = max(1, round(days / 30.44))
        return "1 month" if months == 1 else f"{months} months"
    weeks = max(1, round(days / 7))
    return "1 week" if weeks == 1 else f"{weeks} weeks"


def _history_start(db: Session, dynamic_id: str) -> datetime | None:
    first_entry = (
        db.query(func.min(OrgTrackingEntry.occurred_at))
        .filter(OrgTrackingEntry.dynamic_id == dynamic_id)
        .scalar()
    )
    first_lock = (
        db.query(func.min(ChastityLockup.started_at))
        .filter(ChastityLockup.dynamic_id == dynamic_id)
        .scalar()
    )
    stamps = [stamp for stamp in (first_entry, first_lock) if stamp is not None]
    return min(stamps) if stamps else None


def _orgasm_kind_counts(entry: OrgTrackingEntry) -> tuple[int, int]:
    """Ruined is its own tag. Every other orgasm row, including older method-only logs, is full."""
    if not is_orgasm_event(entry.event_type):
        return 0, 0
    rows = list(entry.orgasms or [])
    tag_lists = [tags_to_list(row.tags) for row in rows] or [tags_to_list(entry.tags)]
    full = ruined = 0
    for tags in tag_lists:
        if has_ruined_orgasm_tag(tags):
            ruined += 1
        else:
            full += 1
    if not tag_lists:
        return 1, 0
    return full, ruined


def _is_logged_session(entry: OrgTrackingEntry) -> bool:
    return is_orgasm_event(entry.event_type) or is_play_event(entry.event_type)


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
    since_first: bool = False,
) -> dict:
    selected_tags = selected_tags or []
    now = datetime.utcnow()
    if since_first:
        start = _history_start(db, dynamic_id)
        since = datetime.combine(start.date(), datetime.min.time()) if start else now - timedelta(days=30)
    else:
        since = now - timedelta(days=days)
    span_days = max(1, (now - since).days or 1)
    span_label = _span_label(span_days)
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
        full_by_partner: dict[str, int] = {}
        sessions_by_partner: dict[str, int] = {}
        chastity_locked_pct: dict[str, float] = {}
        durations: dict[str, list[int]] = {}
        play_by_partner: dict[str, int] = {}
        ruined_by_partner: dict[str, int] = {}

        for membership in memberships:
            orgasms_by_partner[membership.id] = 0
            full_by_partner[membership.id] = 0
            sessions_by_partner[membership.id] = 0
            play_by_partner[membership.id] = 0
            ruined_by_partner[membership.id] = 0
            durations[membership.id] = []

        for entry in filtered_entries:
            if week_start <= entry.occurred_at < week_end:
                mid = entry.for_membership_id
                if _is_logged_session(entry):
                    sessions_by_partner[mid] = sessions_by_partner.get(mid, 0) + 1
                if is_orgasm_event(entry.event_type):
                    full_n, ruined_n = _orgasm_kind_counts(entry)
                    orgasms_by_partner[mid] = orgasms_by_partner.get(mid, 0) + full_n + ruined_n
                    full_by_partner[mid] = full_by_partner.get(mid, 0) + full_n
                    ruined_by_partner[mid] = ruined_by_partner.get(mid, 0) + ruined_n
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
                full_by_partner=full_by_partner,
                sessions_by_partner=sessions_by_partner,
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
        member_entries = [
            entry for entry in filtered_entries if entry.for_membership_id == membership.id
        ]
        full_total = ruined_total = 0
        full_sessions = ruined_sessions = 0
        for entry in member_entries:
            full_n, ruined_n = _orgasm_kind_counts(entry)
            full_total += full_n
            ruined_total += ruined_n
            if full_n > 0:
                full_sessions += 1
            elif ruined_n > 0:
                ruined_sessions += 1
        org_count = full_total + ruined_total
        play_count = sum(1 for entry in member_entries if is_play_event(entry.event_type))
        dur_vals = [
            e.duration_minutes
            for e in member_entries
            if e.duration_minutes is not None
        ]
        org_totals[membership.id] = full_total
        pct_locked = None
        if membership.chastity_enabled and membership.role == PartnerRole.submissive:
            pct_locked = partner_state(db, dynamic_id, membership)["percent_locked_all_time"]
        partner_summaries.append(
            HistoryPartnerSummary(
                membership_id=membership.id,
                name=membership.display_name,
                role=membership.role.value,
                orgasm_count=org_count,
                full_orgasm_count=full_total,
                ruined_orgasm_count=ruined_total,
                full_session_count=full_sessions,
                ruined_session_count=ruined_sessions,
                play_count=play_count,
                avg_duration_minutes=round(sum(dur_vals) / len(dur_vals), 1) if dur_vals else None,
                chastity_enabled=membership.chastity_enabled,
                percent_locked=pct_locked,
            )
        )

    values = list(org_totals.values())
    comparison_label = "No full orgasms logged in this period"
    if values and max(values) > 0:
        names = {m.id: m.display_name for m in memberships}
        leader_id = max(org_totals, key=org_totals.get)
        leader = org_totals[leader_id]
        other_total = sum(v for k, v in org_totals.items() if k != leader_id)
        window = span_label if since_first else f"last {span_days} days"
        if leader > other_total and other_total == 0:
            comparison_label = f"{names[leader_id]}: {leader} full orgasms · partner: 0"
        elif leader != other_total:
            comparison_label = (
                f"{names[leader_id]} leads {leader}–{other_total} full orgasms over {window}"
            )
        else:
            comparison_label = f"Tied at {leader} full orgasms each over {window}"

    available_tags: set[str] = set()
    for entry in entries:
        available_tags.update(tags_to_list(entry.tags))

    return {
        "days": span_days,
        "span_days": span_days,
        "span_label": span_label,
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
