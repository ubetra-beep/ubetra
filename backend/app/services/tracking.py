from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import ChastityLockup, LockupStatus, Membership, OrgTrackingEntry
from .tracking_events import is_orgasm_event, orgasm_count


def format_duration(total_seconds: float) -> str:
    seconds = max(0, int(total_seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def lockup_duration_seconds(started_at: datetime, ended_at: datetime) -> float:
    return max(0.0, (ended_at - started_at).total_seconds())


def partner_orgasm_counts(
    db: Session, dynamic_id: str, memberships: list[Membership], *, days: int = 90
) -> dict[str, int]:
    since = datetime.utcnow() - timedelta(days=days)
    counts: dict[str, int] = {}
    for membership in memberships:
        entries = (
            db.query(OrgTrackingEntry)
            .options(joinedload(OrgTrackingEntry.orgasms))
            .filter(
                OrgTrackingEntry.dynamic_id == dynamic_id,
                OrgTrackingEntry.for_membership_id == membership.id,
                OrgTrackingEntry.occurred_at >= since,
            )
            .all()
        )
        counts[membership.id] = sum(
            orgasm_count(entry) for entry in entries if is_orgasm_event(entry.event_type)
        )
    return counts
