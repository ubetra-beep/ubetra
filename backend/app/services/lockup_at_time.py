from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from ..models import ChastityLockup, Membership
from .chastity import chastity_subs


def locked_members_at(
    lockups: list[ChastityLockup],
    at: datetime,
    *,
    membership_ids: set[str] | None = None,
) -> list[str]:
    locked: list[str] = []
    for lockup in lockups:
        if membership_ids is not None and lockup.for_membership_id not in membership_ids:
            continue
        end = lockup.ended_at or datetime.utcnow()
        if lockup.started_at > at or at > end:
            continue
        on_break = False
        for brk in lockup.breaks:
            brk_end = brk.ended_at or datetime.utcnow()
            if brk.started_at <= at <= brk_end:
                on_break = True
                break
        if not on_break:
            locked.append(lockup.for_membership_id)
    return locked


def load_lockups_for_dynamic(db: Session, dynamic_id: str) -> list[ChastityLockup]:
    return (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(ChastityLockup.dynamic_id == dynamic_id)
        .all()
    )


def lockup_context_for_entry(
    entry,
    lockups: list[ChastityLockup],
    memberships: dict[str, Membership],
) -> dict:
    at = entry.occurred_at
    locked_ids = locked_members_at(lockups, at)
    locked_names = [
        memberships[mid].display_name
        for mid in locked_ids
        if mid in memberships
    ]
    own_locked = entry.for_membership_id in locked_ids
    partner_locked = any(mid != entry.for_membership_id for mid in locked_ids)
    return {
        "during_lockup": bool(locked_ids),
        "during_own_lockup": own_locked,
        "during_partner_lockup": partner_locked and not own_locked,
        "locked_partner_names": locked_names,
    }
