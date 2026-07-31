from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityBreakType,
    ChastityLockup,
    Membership,
    OrgTrackingEntry,
)
from .chastity import chastity_subs
from .lockup_at_time import load_lockups_for_dynamic, lockup_context_for_entry
from .chastity_calendar import (
    calendar_day_status,
    count_rolling_full_days,
)
from .tags import entry_matches_selected_tags, tags_to_list
from .tracking_events import has_full_orgasm_tag, has_ruined_orgasm_tag, is_orgasm_event, is_play_event, orgasm_count

RUIN_TYPES = {ChastityBreakType.authorized_denial, ChastityBreakType.authorized_ruin}


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    return start, end


def _days_in_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _gaps_between_days(dates: list[date]) -> list[int]:
    if len(dates) < 2:
        return []
    sorted_days = sorted(dates)
    return [(sorted_days[i] - sorted_days[i - 1]).days for i in range(1, len(sorted_days))]


def _avg(values: list[int | float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _avg_duration(values: list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _month_keys(period_start: date, period_end: date) -> list[str]:
    keys: list[str] = []
    cursor = date(period_start.year, period_start.month, 1)
    end = date(period_end.year, period_end.month, 1)
    while cursor <= end:
        keys.append(cursor.strftime("%Y-%m"))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return keys


def build_chastity_days_report(
    db: Session,
    dynamic_id: str,
    memberships: list[Membership],
    *,
    year: int,
) -> dict:
    period_start, period_end = _year_bounds(year)
    now = datetime.utcnow()
    if period_end > now:
        period_end = now
    tracked_subs = chastity_subs(memberships)
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id.in_([s.id for s in tracked_subs] or [""]),
            ChastityLockup.started_at <= period_end,
        )
        .all()
    )
    if not tracked_subs:
        lockups = []

    day_list = _days_in_range(period_start.date(), period_end.date())
    partners = []
    for sub in tracked_subs:
        days_payload = []
        partial_days = free_days = 0
        whole_days = count_rolling_full_days(lockups, sub.id, until=period_end)
        for day in day_list:
            status, locked = calendar_day_status(
                lockups, sub.id, day, period_end=period_end
            )
            if status == "full":
                pass
            elif status == "partial":
                partial_days += 1
            else:
                free_days += 1
            days_payload.append(
                {
                    "date": day.isoformat(),
                    "status": status,
                    "locked_seconds": locked,
                }
            )
        partners.append(
            {
                "membership_id": sub.id,
                "name": sub.display_name,
                "days": days_payload,
                "whole_days": whole_days,
                "partial_days": partial_days,
                "free_days": free_days,
            }
        )

    return {"year": year, "partners": partners, "any_enabled": bool(tracked_subs)}


def build_orgasm_report(
    db: Session,
    dynamic_id: str,
    memberships: list[Membership],
    *,
    year: int,
    selected_tags: list[str] | None = None,
) -> dict:
    selected_tags = selected_tags or []
    period_start, period_end = _year_bounds(year)
    now = datetime.utcnow()
    if period_end > now:
        period_end = now

    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.occurred_at >= period_start,
            OrgTrackingEntry.occurred_at <= period_end,
        )
        .all()
    )
    filtered = [
        e for e in entries if entry_matches_selected_tags(e, selected_tags)
    ]
    lockups = load_lockups_for_dynamic(db, dynamic_id)
    membership_map = {m.id: m for m in memberships}
    ruin_count_by_member: dict[str, int] = {m.id: 0 for m in memberships}
    lockups_for_ruin = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.started_at <= period_end,
        )
        .all()
    )
    for lockup in lockups_for_ruin:
        for brk in lockup.breaks:
            if brk.break_type in RUIN_TYPES and period_start <= brk.started_at <= period_end:
                ruin_count_by_member[lockup.for_membership_id] = (
                    ruin_count_by_member.get(lockup.for_membership_id, 0) + 1
                )
    for entry in filtered:
        if not is_orgasm_event(entry.event_type):
            continue
        ruined = 0
        rows = entry.orgasms or []
        if rows:
            ruined = sum(1 for row in rows if has_ruined_orgasm_tag(tags_to_list(row.tags)))
        elif has_ruined_orgasm_tag(tags_to_list(entry.tags)):
            ruined = 1
        if ruined:
            ruin_count_by_member[entry.for_membership_id] = (
                ruin_count_by_member.get(entry.for_membership_id, 0) + ruined
            )

    day_list = _days_in_range(period_start.date(), period_end.date())
    total_days = len(day_list)
    weeks = max(1.0, total_days / 7.0)
    months = max(1.0, total_days / 30.437)
    month_keys = _month_keys(period_start.date(), period_end.date())

    partners = []
    for member in memberships:
        member_entries = [e for e in filtered if e.for_membership_id == member.id]
        orgasm_entries = [e for e in member_entries if is_orgasm_event(e.event_type)]
        play_entries = [e for e in member_entries if is_play_event(e.event_type)]

        any_orgasm_dates = {e.occurred_at.date() for e in orgasm_entries}
        full_orgasm_dates = set()
        total_orgasms = 0
        orgasms_during_lockup = 0
        orgasms_during_own_lockup = 0
        orgasms_while_partner_locked = 0
        month_orgasms: dict[str, int] = {k: 0 for k in month_keys}
        month_full: dict[str, int] = {k: 0 for k in month_keys}
        month_ruined: dict[str, int] = {k: 0 for k in month_keys}
        month_play: dict[str, int] = {k: 0 for k in month_keys}
        month_durations: dict[str, list[int]] = {k: [] for k in month_keys}

        for entry in orgasm_entries:
            count = orgasm_count(entry)
            total_orgasms += count
            month_key = entry.occurred_at.strftime("%Y-%m")
            if month_key in month_orgasms:
                month_orgasms[month_key] += count
            ctx = lockup_context_for_entry(entry, lockups, membership_map)
            if ctx["during_lockup"]:
                orgasms_during_lockup += count
            if ctx["during_own_lockup"]:
                orgasms_during_own_lockup += count
            if ctx["during_partner_lockup"]:
                orgasms_while_partner_locked += count
            rows = entry.orgasms or []
            is_full = False
            if rows:
                is_full = any(has_full_orgasm_tag(tags_to_list(row.tags)) for row in rows)
            else:
                is_full = has_full_orgasm_tag(tags_to_list(entry.tags))
            if is_full:
                full_orgasm_dates.add(entry.occurred_at.date())
                if month_key in month_full:
                    month_full[month_key] += 1
            if month_key in month_ruined:
                tag_ruin = 0
                if rows:
                    tag_ruin = sum(
                        1 for row in rows if has_ruined_orgasm_tag(tags_to_list(row.tags))
                    )
                elif has_ruined_orgasm_tag(tags_to_list(entry.tags)):
                    tag_ruin = 1
                month_ruined[month_key] += tag_ruin

        play_dates = {e.occurred_at.date() for e in play_entries}
        for entry in play_entries:
            month_key = entry.occurred_at.strftime("%Y-%m")
            if month_key in month_play:
                month_play[month_key] += 1
        for entry in member_entries:
            if entry.duration_minutes is None:
                continue
            month_key = entry.occurred_at.strftime("%Y-%m")
            if month_key in month_durations:
                month_durations[month_key].append(entry.duration_minutes)

        durations = [
            e.duration_minutes
            for e in member_entries
            if e.duration_minutes is not None
        ]
        satisfactions = [
            e.satisfaction
            for e in member_entries
            if e.satisfaction is not None
        ]
        edgings = [
            e.edging_count
            for e in member_entries
            if e.edging_count is not None
        ]
        days_with = len(any_orgasm_dates)
        gaps_full = _gaps_between_days(list(full_orgasm_dates))
        gaps_any = _gaps_between_days(list(any_orgasm_dates))
        ruined_total = ruin_count_by_member.get(member.id, 0)

        monthly = []
        for key in month_keys:
            label = datetime.strptime(key + "-01", "%Y-%m-%d").strftime("%b")
            monthly.append(
                {
                    "month": key,
                    "label": label,
                    "orgasms": month_orgasms[key],
                    "full_orgasm_days": month_full[key],
                    "ruined": month_ruined[key],
                    "play_sessions": month_play[key],
                    "avg_duration_minutes": _avg_duration(month_durations[key]),
                }
            )

        partners.append(
            {
                "membership_id": member.id,
                "name": member.display_name,
                "role": member.role.value,
                "days_with_orgasms": days_with,
                "days_without_orgasms": max(0, total_days - days_with),
                "full_orgasm_days": len(full_orgasm_dates),
                "play_days": len(play_dates),
                "total_orgasms": total_orgasms,
                "orgasms_during_lockup": orgasms_during_lockup,
                "orgasms_during_own_lockup": orgasms_during_own_lockup,
                "orgasms_while_partner_locked": orgasms_while_partner_locked,
                "ruined_orgasms": ruined_total,
                "avg_duration_minutes": _avg_duration(durations),
                "avg_satisfaction": round(_avg(satisfactions), 2) if satisfactions else None,
                "avg_edging_count": round(_avg(edgings), 2) if edgings else None,
                "avg_orgasms_per_week": round(total_orgasms / weeks, 2),
                "avg_orgasms_per_month": round(total_orgasms / months, 2),
                "avg_ruined_per_month": round(ruined_total / months, 2),
                "avg_play_days_per_month": round(len(play_dates) / months, 2),
                "max_days_between_full": max(gaps_full) if gaps_full else None,
                "min_days_between_full": min(gaps_full) if gaps_full else None,
                "avg_days_between_full": round(_avg(gaps_full), 2) if gaps_full else None,
                "max_days_between_any": max(gaps_any) if gaps_any else None,
                "avg_days_between_any": round(_avg(gaps_any), 2) if gaps_any else None,
                "monthly": monthly,
            }
        )

    return {
        "year": year,
        "total_days": total_days,
        "selected_tags": selected_tags,
        "partners": partners,
        "note": "Charts use year-to-date totals. Averages divide by elapsed weeks/months. Orgasm days count sessions with orgasms; each orgasm row is tagged separately. Play days are no-orgasm sessions.",
    }


def build_chastity_stats_report(
    db: Session,
    dynamic_id: str,
    memberships: list[Membership],
    *,
    year: int,
) -> dict:
    from .history_dashboard import locked_seconds_in_range
    from .tracking import format_duration

    period_start, period_end = _year_bounds(year)
    now = datetime.utcnow()
    if period_end > now:
        period_end = now
    period_seconds = max(1.0, (period_end - period_start).total_seconds())
    tracked_subs = chastity_subs(memberships)
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id.in_([s.id for s in tracked_subs] or [""]),
            ChastityLockup.started_at <= period_end,
        )
        .all()
    )
    if not tracked_subs:
        lockups = []

    month_keys = _month_keys(period_start.date(), period_end.date())
    partners = []
    for sub in tracked_subs:
        sub_lockups = [
            lockup
            for lockup in lockups
            if lockup.for_membership_id == sub.id and lockup.started_at <= period_end
        ]
        durations: list[float] = []
        cumulative_locked = 0.0
        for lockup in sub_lockups:
            end = lockup.ended_at or min(now, period_end)
            start = max(lockup.started_at, period_start)
            if end <= start:
                continue
            locked = locked_seconds_in_range(lockup, start, end)
            if locked > 0:
                durations.append(locked)
                cumulative_locked += locked
        cumulative_unlocked = max(0.0, period_seconds - cumulative_locked)

        monthly = []
        for key in month_keys:
            month_start = datetime.strptime(key + "-01", "%Y-%m-%d")
            if month_start.month == 12:
                month_end = datetime(month_start.year + 1, 1, 1)
            else:
                month_end = datetime(month_start.year, month_start.month + 1, 1)
            range_start = max(month_start, period_start)
            range_end = min(month_end, period_end + timedelta(seconds=1))
            if range_end <= range_start:
                monthly.append(
                    {
                        "month": key,
                        "label": month_start.strftime("%b"),
                        "percent_locked": 0.0,
                        "locked_seconds": 0,
                    }
                )
                continue
            locked_s = 0.0
            for lockup in sub_lockups:
                locked_s += locked_seconds_in_range(lockup, range_start, range_end)
            span = max(1.0, (range_end - range_start).total_seconds())
            monthly.append(
                {
                    "month": key,
                    "label": month_start.strftime("%b"),
                    "percent_locked": round(min(100.0, (locked_s / span) * 100), 1),
                    "locked_seconds": int(locked_s),
                }
            )

        partners.append(
            {
                "membership_id": sub.id,
                "name": sub.display_name,
                "sessions_count": len(durations),
                "max_locked_label": format_duration(max(durations)) if durations else "—",
                "min_locked_label": format_duration(min(durations)) if durations else "—",
                "avg_locked_label": format_duration(sum(durations) / len(durations)) if durations else "—",
                "cumulative_locked_label": format_duration(cumulative_locked),
                "cumulative_unlocked_label": format_duration(cumulative_unlocked),
                "percent_locked": round(min(100.0, max(0.0, (cumulative_locked / period_seconds) * 100)), 2),
                "percent_unlocked": round(min(100.0, max(0.0, (cumulative_unlocked / period_seconds) * 100)), 2),
                "avg_session_days": round((sum(durations) / len(durations)) / 86400, 2) if durations else None,
                "monthly": monthly,
            }
        )

    return {"year": year, "partners": partners, "any_enabled": bool(tracked_subs)}
