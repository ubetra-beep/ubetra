"""Switch overlay: offer, draft, approve, log. Roles stay put."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, User
from ..services.switch_mode import (
    approve_switch,
    decline_switch,
    end_switch,
    log_experience,
    offer_switch,
    prepare,
    send_back,
    submit_draft,
    to_public,
)

router = APIRouter(prefix="/dynamics", tags=["switch"])


class SwitchOfferIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    hours: int | None = None


class SwitchDraftIn(BaseModel):
    goal: dict | None = None
    scene: dict | None = None


class SwitchNoteIn(BaseModel):
    note: str = ""


class SwitchLogIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)


def _dynamic(db: Session, dynamic_id: str) -> Dynamic:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return dynamic


@router.get("/{dynamic_id}/switch")
def get_switch(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = prepare(db, dynamic)
    db.commit()
    return to_public(db, session, actor)


@router.post("/{dynamic_id}/switch/offer")
def post_switch_offer(
    dynamic_id: str,
    payload: SwitchOfferIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = offer_switch(db, dynamic, actor, kind=payload.kind, hours=payload.hours)
    db.commit()
    return to_public(db, session, actor)


@router.post("/{dynamic_id}/switch/draft")
def post_switch_draft(
    dynamic_id: str,
    payload: SwitchDraftIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = submit_draft(db, dynamic, actor, goal=payload.goal, scene=payload.scene)
    db.commit()
    return to_public(db, session, actor)


@router.post("/{dynamic_id}/switch/approve")
def post_switch_approve(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = approve_switch(db, dynamic, actor)
    db.commit()
    return to_public(db, session, actor)


@router.post("/{dynamic_id}/switch/send-back")
def post_switch_send_back(
    dynamic_id: str,
    payload: SwitchNoteIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = send_back(db, dynamic, actor, note=payload.note)
    db.commit()
    return to_public(db, session, actor)


@router.post("/{dynamic_id}/switch/decline")
def post_switch_decline(
    dynamic_id: str,
    payload: SwitchNoteIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = decline_switch(db, dynamic, actor, note=payload.note)
    db.commit()
    return to_public(db, None, actor)


@router.post("/{dynamic_id}/switch/end")
def post_switch_end(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    end_switch(db, dynamic, actor)
    db.commit()
    return to_public(db, None, actor)


@router.post("/{dynamic_id}/switch/log")
def post_switch_log(
    dynamic_id: str,
    payload: SwitchLogIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    actor = get_membership(dynamic_id, user, db)
    dynamic = _dynamic(db, dynamic_id)
    session = log_experience(db, dynamic, actor, kind=payload.kind)
    db.commit()
    current = session if session.status in {"drafting", "pending_approval", "active"} else None
    return to_public(db, current, actor)
