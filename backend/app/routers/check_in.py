from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, Membership, RelationshipCheckIn, User
from ..schemas import RelationshipCheckInOut, RelationshipCheckInStatusOut
from ..services.relationship_check_in import (
    check_in_due,
    earliest_tracking_log_at,
    generate_check_in,
    last_check_in,
    post_check_in_invite,
    readiness,
)

router = APIRouter(prefix="/dynamics", tags=["check-in"])


def _out(row: RelationshipCheckIn, db: Session) -> RelationshipCheckInOut:
    creator = db.get(Membership, row.created_by_membership_id)
    return RelationshipCheckInOut(
        id=row.id,
        report_text=row.report_text or "",
        period_start=row.period_start,
        period_end=row.period_end,
        window_days=row.window_days or 90,
        created_at=row.created_at,
        created_by_display_name=(creator.display_name if creator else "") or "",
    )


@router.get("/{dynamic_id}/check-in", response_model=RelationshipCheckInStatusOut)
def get_check_in_status(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RelationshipCheckInStatusOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    ready, reason = readiness(db, dynamic, user)
    rows = (
        db.query(RelationshipCheckIn)
        .filter(RelationshipCheckIn.dynamic_id == dynamic_id)
        .order_by(RelationshipCheckIn.created_at.desc())
        .limit(12)
        .all()
    )
    latest = rows[0] if rows else None
    return RelationshipCheckInStatusOut(
        ready=ready,
        reason=reason,
        due=check_in_due(db, dynamic),
        earliest_tracking_at=earliest_tracking_log_at(db, dynamic_id),
        last_check_in_at=latest.created_at if latest else None,
        invite_posted_at=getattr(dynamic, "check_in_invite_posted_at", None),
        latest=_out(latest, db) if latest else None,
        history=[_out(r, db) for r in rows],
    )


@router.get("/{dynamic_id}/check-in/{check_in_id}", response_model=RelationshipCheckInOut)
def get_check_in(
    dynamic_id: str,
    check_in_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RelationshipCheckInOut:
    get_membership(dynamic_id, user, db)
    row = db.get(RelationshipCheckIn, check_in_id)
    if row is None or row.dynamic_id != dynamic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found")
    return _out(row, db)


@router.post("/{dynamic_id}/check-in/generate", response_model=RelationshipCheckInOut)
def run_check_in(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RelationshipCheckInOut:
    actor = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    row = generate_check_in(db, dynamic=dynamic, actor=actor, user=user)
    db.commit()
    db.refresh(row)
    return _out(row, db)


@router.post("/{dynamic_id}/check-in/invite", response_model=RelationshipCheckInStatusOut)
def invite_check_in(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RelationshipCheckInStatusOut:
    """Post (or re-post) the Chat invite now — either partner may trigger."""
    actor = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    post_check_in_invite(db, dynamic, actor=actor, force=True)
    db.commit()
    return get_check_in_status(dynamic_id, user, db)
