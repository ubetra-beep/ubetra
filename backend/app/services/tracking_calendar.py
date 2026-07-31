from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityLockup,
    FeelingCheckIn,
    Membership,
    OrgTrackingEntry,
)
from .chastity import BREAK_TYPE_LABELS
from .tracking_events import is_orgasm_event, is_play_event


def _day_key(dt: datetime) -> str:
    return dt.date().isoformat()


def _range_bounds(range_key: str, *, anchor: date | None = None) -> tuple[datetime, datetime, list[date]]:
    today = anchor or datetime.utcnow().date()
    if range_key == "7d":
        start_day = today - timedelta(days=6)
        days = [start_day + timedelta(days=i) for i in range(7)]
    else:
        # month
        start_day = today.replace(day=1)
        if today.month == 12:
            next_month = date(today.year + 1, 1, 1)
        else:
            next_month = date(today.year, today.month + 1, 1)
        end_day = next_month - timedelta(days=1)
        days = [start_day + timedelta(days=i) for i in range((end_day - start_day).days + 1)]
    start_dt = datetime.combine(days[0], datetime.min.time())
    end_dt = datetime.combine(days[-1], datetime.max.time()).replace(microsecond=0)
    return start_dt, end_dt, days


def build_tracking_calendar(
    db: Session,
    dynamic_id: str,
    *,
    range_key: str = "month",
    membership_ids: list[str] | None = None,
    event_types: list[str] | None = None,
) -> dict:
    """Unified day grid for Tracking hub: chastity / orgasms / feelings."""
    range_key = "7d" if range_key == "7d" else "month"
    types = set(event_types or ["chastity", "orgasms", "feelings"])
    start_dt, end_dt, days = _range_bounds(range_key)

    partners = (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id)
        .order_by(Membership.display_name.asc())
        .all()
    )
    partner_filter = set(membership_ids) if membership_ids else None

    by_day: dict[str, list[dict]] = defaultdict(list)

    if "chastity" in types:
        lockups = (
            db.query(ChastityLockup)
            .options(joinedload(ChastityLockup.breaks))
            .filter(ChastityLockup.dynamic_id == dynamic_id)
            .all()
        )
        for lockup in lockups:
            if partner_filter and lockup.for_membership_id not in partner_filter:
                continue
            name = next((p.display_name for p in partners if p.id == lockup.for_membership_id), "Partner")
            if start_dt <= lockup.started_at <= end_dt:
                by_day[_day_key(lockup.started_at)].append(
                    {
                        "id": f"lock-start-{lockup.id}",
                        "kind": "chastity_lockup",
                        "type_group": "chastity",
                        "title": f"Lockup started · {name}",
                        "detail": lockup.device_notes or "",
                        "at": lockup.started_at,
                        "membership_id": lockup.for_membership_id,
                        "path": f"/dynamic/{dynamic_id}/chastity",
                    }
                )
            if lockup.ended_at and start_dt <= lockup.ended_at <= end_dt:
                by_day[_day_key(lockup.ended_at)].append(
                    {
                        "id": f"lock-end-{lockup.id}",
                        "kind": "chastity_release",
                        "type_group": "chastity",
                        "title": f"Full release · {name}",
                        "detail": lockup.release_notes or "",
                        "at": lockup.ended_at,
                        "membership_id": lockup.for_membership_id,
                        "path": f"/dynamic/{dynamic_id}/chastity",
                    }
                )
            for brk in lockup.breaks:
                if brk.ended_at is not None and brk.ended_at <= brk.started_at:
                    continue
                if start_dt <= brk.started_at <= end_dt:
                    label = BREAK_TYPE_LABELS.get(brk.break_type.value if hasattr(brk.break_type, "value") else str(brk.break_type), brk.break_reason)
                    by_day[_day_key(brk.started_at)].append(
                        {
                            "id": f"break-start-{brk.id}",
                            "kind": "chastity_temp_unlock",
                            "type_group": "chastity",
                            "title": f"Temp unlock · {label}",
                            "detail": brk.note or brk.break_reason or "",
                            "at": brk.started_at,
                            "membership_id": lockup.for_membership_id,
                            "path": f"/dynamic/{dynamic_id}/chastity",
                        }
                    )
                if brk.ended_at and start_dt <= brk.ended_at <= end_dt:
                    by_day[_day_key(brk.ended_at)].append(
                        {
                            "id": f"break-end-{brk.id}",
                            "kind": "chastity_relock",
                            "type_group": "chastity",
                            "title": f"Locked again · {name}",
                            "detail": "",
                            "at": brk.ended_at,
                            "membership_id": lockup.for_membership_id,
                            "path": f"/dynamic/{dynamic_id}/chastity",
                        }
                    )

    if "orgasms" in types:
        entries = (
            db.query(OrgTrackingEntry)
            .filter(
                OrgTrackingEntry.dynamic_id == dynamic_id,
                OrgTrackingEntry.occurred_at >= start_dt,
                OrgTrackingEntry.occurred_at <= end_dt,
            )
            .order_by(OrgTrackingEntry.occurred_at.asc())
            .all()
        )
        for entry in entries:
            if partner_filter and entry.for_membership_id not in partner_filter:
                continue
            name = next((p.display_name for p in partners if p.id == entry.for_membership_id), "Partner")
            if is_orgasm_event(entry.event_type):
                kind = "orgasm"
                title = f"Orgasm · {name}"
            elif is_play_event(entry.event_type):
                kind = "play"
                title = f"Play · {name}"
            else:
                kind = "orgasm"
                title = f"Tracking · {name}"
            by_day[_day_key(entry.occurred_at)].append(
                {
                    "id": f"org-{entry.id}",
                    "kind": kind,
                    "type_group": "orgasms",
                    "title": title,
                    "detail": (entry.notes or "")[:160],
                    "at": entry.occurred_at,
                    "membership_id": entry.for_membership_id,
                    "path": f"/dynamic/{dynamic_id}/tracking",
                }
            )

    if "feelings" in types:
        checkins = (
            db.query(FeelingCheckIn)
            .filter(
                FeelingCheckIn.dynamic_id == dynamic_id,
                FeelingCheckIn.occurred_at >= start_dt,
                FeelingCheckIn.occurred_at <= end_dt,
            )
            .order_by(FeelingCheckIn.occurred_at.asc())
            .all()
        )
        for checkin in checkins:
            if partner_filter and checkin.for_membership_id not in partner_filter:
                continue
            name = next((p.display_name for p in partners if p.id == checkin.for_membership_id), "Partner")
            by_day[_day_key(checkin.occurred_at)].append(
                {
                    "id": f"feel-{checkin.id}",
                    "kind": "feelings",
                    "type_group": "feelings",
                    "title": f"Feelings · {name}",
                    "detail": checkin.context or "",
                    "at": checkin.occurred_at,
                    "membership_id": checkin.for_membership_id,
                    "path": f"/dynamic/{dynamic_id}/feelings",
                }
            )

    day_rows = []
    max_dots = 4 if range_key == "month" else 8
    for day in days:
        key = day.isoformat()
        events = sorted(by_day.get(key, []), key=lambda e: e["at"])
        day_rows.append(
            {
                "date": key,
                "weekday": day.strftime("%a"),
                "events": events,
                "overflow": max(0, len(events) - max_dots),
                "visible_events": events[:max_dots],
            }
        )

    return {
        "range": range_key,
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "max_dots_per_day": max_dots,
        "partners": [
            {"membership_id": p.id, "display_name": p.display_name, "role": p.role.value}
            for p in partners
        ],
        "days": day_rows,
    }
