from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, FeelingCheckIn, FeelingCheckInSelection, Membership, User
from ..services.chat_events import post_activity_event
from ..services.feelings import (
    checkin_out,
    create_checkin,
    feelings_calendar,
    feelings_status,
    load_wheel,
    recent_checkins,
)

router = APIRouter(prefix="/dynamics", tags=["feelings"])


class FeelingSelectionIn(BaseModel):
    """Legacy path payload; prefer emotion_ids."""

    id: str | None = None
    core: str | None = None
    mid: str | None = None
    outer: str | None = None


class FeelingCheckInCreate(BaseModel):
    for_membership_id: str | None = None
    context: Literal["ad_hoc", "before_play", "after_play", "end_of_day"] = "ad_hoc"
    emotion_ids: list[str] = Field(default_factory=list)
    selections: list[FeelingSelectionIn] = Field(default_factory=list)
    horny_level: int | None = Field(default=None, ge=0, le=10)
    org_entry_id: str | None = None
    chastity_lockup_id: str | None = None
    spin_session_id: str | None = None
    occurred_at: datetime | None = None


class FeelingCheckInOut(BaseModel):
    id: str
    for_membership_id: str
    for_display_name: str
    logged_by_membership_id: str
    logged_by_display_name: str
    context: str
    selections: list[dict]
    horny_level: int | None = None
    org_entry_id: str | None = None
    chastity_lockup_id: str | None = None
    spin_session_id: str | None = None
    occurred_at: datetime
    created_at: datetime


class FeelingsSettingsUpdate(BaseModel):
    prompt_mode: Literal["soft", "hard"] = "soft"
    require_end_of_day: bool = True


def _membership_map(db: Session, dynamic_id: str) -> dict[str, Membership]:
    rows = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    return {m.id: m for m in rows}


def _reload_checkin(db: Session, checkin_id: str) -> FeelingCheckIn:
    row = (
        db.query(FeelingCheckIn)
        .options(
            joinedload(FeelingCheckIn.selections).joinedload(FeelingCheckInSelection.emotion)
        )
        .filter(FeelingCheckIn.id == checkin_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found")
    return row


@router.get("/{dynamic_id}/feelings/wheel")
def get_feelings_wheel(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    return load_wheel(db)


@router.get("/{dynamic_id}/feelings/calendar")
def get_feelings_calendar(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    year: int | None = None,
    month: int | None = None,
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    now = datetime.utcnow()
    y = int(year or now.year)
    m = int(month or now.month)
    if m < 1 or m > 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid month")
    return feelings_calendar(db, dynamic_id, year=y, month=m, you_membership_id=membership.id)


@router.get("/{dynamic_id}/feelings/status")
def get_feelings_status(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return feelings_status(db, dynamic_id, membership, dynamic)


@router.put("/{dynamic_id}/feelings/settings")
def update_feelings_settings(
    dynamic_id: str,
    payload: FeelingsSettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    if membership.role.value != "dominant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can change feelings settings",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    dynamic.feelings_prompt_mode = payload.prompt_mode
    dynamic.feelings_require_end_of_day = payload.require_end_of_day
    db.commit()
    return feelings_status(db, dynamic_id, membership, dynamic)


@router.get("/{dynamic_id}/feelings", response_model=list[FeelingCheckInOut])
def list_feelings(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 40,
) -> list[FeelingCheckInOut]:
    get_membership(dynamic_id, user, db)
    memberships = _membership_map(db, dynamic_id)
    rows = recent_checkins(db, dynamic_id, limit=min(100, max(1, limit)))
    return [FeelingCheckInOut(**checkin_out(r, memberships, db)) for r in rows]


@router.post("/{dynamic_id}/feelings", response_model=FeelingCheckInOut, status_code=status.HTTP_201_CREATED)
def post_feeling(
    dynamic_id: str,
    payload: FeelingCheckInCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FeelingCheckInOut:
    membership = get_membership(dynamic_id, user, db)
    memberships = _membership_map(db, dynamic_id)
    target_id = payload.for_membership_id or membership.id
    if target_id not in memberships:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid partner")
    if target_id != membership.id and membership.role.value != "dominant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only log your own feelings",
        )
    row = create_checkin(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        for_membership_id=target_id,
        context=payload.context,
        emotion_ids=payload.emotion_ids,
        selections=[s.model_dump() for s in payload.selections],
        horny_level=payload.horny_level,
        org_entry_id=payload.org_entry_id,
        chastity_lockup_id=payload.chastity_lockup_id,
        spin_session_id=payload.spin_session_id,
        occurred_at=payload.occurred_at,
    )
    target = memberships[target_id]
    out_preview = checkin_out(row, memberships, db)
    labels = [
        s.get("label")
        for s in (out_preview.get("selections") or [])
        if isinstance(s, dict) and s.get("label")
    ]
    parts = []
    if out_preview.get("horny_level") is not None:
        parts.append(f"horny {out_preview['horny_level']}/10")
    if labels:
        parts.append(", ".join(labels[:4]))
    summary = " · ".join(parts) or "feelings"
    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="feelings_logged",
        text=f"logged feelings for {target.display_name}: {summary}",
        path=f"/dynamic/{dynamic_id}/feelings",
        link_label="Open feelings",
        subject_membership_id=target_id,
        from_label=None,
    )
    db.commit()
    row = _reload_checkin(db, row.id)
    return FeelingCheckInOut(**checkin_out(row, memberships, db))
