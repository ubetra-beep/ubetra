from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, PartnerRole, User
from ..services import fate_game, roulette

router = APIRouter(prefix="/dynamics", tags=["play-games"])


class RevealFateIn(BaseModel):
    number: int = Field(ge=1, le=6)


class RouletteSettingsIn(BaseModel):
    enabled: bool = False
    mode: str = "virtual"
    started_on: str = ""


class RouletteBagIn(BaseModel):
    bag: dict = {}
    reserve: dict = {}
    focus: str = "bag"


class RouletteGrantRuleIn(BaseModel):
    id: str = ""
    kind: str = "task_tag"
    tag: str = ""
    every: int = 1
    effect: str = "pull"


class RouletteGrantsIn(BaseModel):
    rules: list[RouletteGrantRuleIn] = []


def _dominant(db: Session, dynamic_id: str, user: User) -> bool:
    membership = get_membership(dynamic_id, user, db)
    return membership.role == PartnerRole.dominant


def _roulette_call(action):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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


@router.get("/{dynamic_id}/play-games/roulette")
def get_roulette(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return roulette.public_state(db, dynamic_id, you_are_dominant=_dominant(db, dynamic_id, user))


@router.put("/{dynamic_id}/play-games/roulette")
def put_roulette(
    dynamic_id: str,
    payload: RouletteSettingsIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return _roulette_call(
        lambda: roulette.update_settings(
            db,
            dynamic_id,
            enabled=payload.enabled,
            mode=payload.mode or "virtual",
            you_are_dominant=_dominant(db, dynamic_id, user),
            started_on=payload.started_on,
        )
    )


@router.put("/{dynamic_id}/play-games/roulette/bag")
def put_roulette_bag(
    dynamic_id: str,
    payload: RouletteBagIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return _roulette_call(
        lambda: roulette.set_bag(
            db,
            dynamic_id,
            bag=payload.bag or {},
            reserve=payload.reserve or {},
            you_are_dominant=_dominant(db, dynamic_id, user),
            focus=payload.focus or "bag",
        )
    )


@router.put("/{dynamic_id}/play-games/roulette/grants")
def put_roulette_grants(
    dynamic_id: str,
    payload: RouletteGrantsIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return _roulette_call(
        lambda: roulette.set_grant_rules(
            db,
            dynamic_id,
            [rule.model_dump() for rule in payload.rules],
            you_are_dominant=_dominant(db, dynamic_id, user),
        )
    )


@router.post("/{dynamic_id}/play-games/roulette/draw")
def draw_roulette(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return _roulette_call(
        lambda: roulette.perform_draw(db, dynamic_id, you_are_dominant=_dominant(db, dynamic_id, user))
    )


@router.post("/{dynamic_id}/play-games/roulette/end")
def end_roulette(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _dynamic(db, dynamic_id, user)
    return _roulette_call(
        lambda: roulette.perform_end(db, dynamic_id, you_are_dominant=_dominant(db, dynamic_id, user))
    )
