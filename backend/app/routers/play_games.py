from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, User
from ..services import fate_game

router = APIRouter(prefix="/dynamics", tags=["play-games"])


class RevealFateIn(BaseModel):
    number: int = Field(ge=1, le=6)


def _dynamic(db: Session, dynamic_id: str, user: User) -> Dynamic:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return dynamic


@router.get("/{dynamic_id}/play-games/fate")
def get_fate(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return fate_game.public_state(fate_game.load_game(db, dynamic_id))


@router.post("/{dynamic_id}/play-games/fate/deal")
def deal_fate(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    dynamic = _dynamic(db, dynamic_id, user)
    return fate_game.deal_fates(db, user=user, dynamic=dynamic)


@router.post("/{dynamic_id}/play-games/fate/reveal")
def reveal_fate(
    dynamic_id: str,
    payload: RevealFateIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return fate_game.reveal_fate(db, dynamic_id=dynamic_id, number=payload.number)
