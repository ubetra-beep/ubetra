from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import PushSubscription, User
from ..schemas import (
    PushPublicKeyOut,
    PushSettingsUpdate,
    PushStatusOut,
    PushSubscribeIn,
)
from ..services.vapid import is_configured, vapid_public_key

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/public-key", response_model=PushPublicKeyOut)
def get_public_key() -> PushPublicKeyOut:
    configured = is_configured()
    return PushPublicKeyOut(
        public_key=vapid_public_key() if configured else "",
        configured=configured,
    )


@router.get("/status", response_model=PushStatusOut)
def push_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PushStatusOut:
    count = db.query(PushSubscription).filter(PushSubscription.user_id == user.id).count()
    return PushStatusOut(
        configured=is_configured(),
        push_enabled=bool(user.push_enabled),
        subscription_count=count,
    )


@router.put("/settings", response_model=PushStatusOut)
def update_push_settings(
    payload: PushSettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PushStatusOut:
    """Toggle the account-level push preference.

    Turning push off does **not** delete stored device endpoints — those are
    removed per-device via DELETE /push/subscribe?endpoint=… so other phones/PWAs
    keep working.
    """
    user.push_enabled = payload.push_enabled
    db.commit()
    db.refresh(user)
    count = db.query(PushSubscription).filter(PushSubscription.user_id == user.id).count()
    return PushStatusOut(
        configured=is_configured(),
        push_enabled=bool(user.push_enabled),
        subscription_count=count,
    )


@router.post("/subscribe", response_model=PushStatusOut, status_code=status.HTTP_201_CREATED)
def subscribe_push(
    payload: PushSubscribeIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PushStatusOut:
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not configured on this server",
        )
    p256dh = payload.keys.get("p256dh", "").strip()
    auth = payload.keys.get("auth", "").strip()
    if not p256dh or not auth:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid push keys")

    existing = (
        db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    )
    if existing is None:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=payload.endpoint.strip(),
                p256dh=p256dh,
                auth=auth,
            )
        )
    else:
        existing.user_id = user.id
        existing.p256dh = p256dh
        existing.auth = auth

    user.push_enabled = True
    db.commit()
    count = db.query(PushSubscription).filter(PushSubscription.user_id == user.id).count()
    return PushStatusOut(
        configured=True,
        push_enabled=True,
        subscription_count=count,
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def unsubscribe_push(
    endpoint: Annotated[str, Query(min_length=8)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    db.query(PushSubscription).filter(
        PushSubscription.user_id == user.id,
        PushSubscription.endpoint == endpoint.strip(),
    ).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
