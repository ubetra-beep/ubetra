from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import ChatMessage, ChatMessageType, Dynamic, User, VaultImage
from ..schemas import VaultImageCreate, VaultImageOut, VaultImageUpdate
from ..services.chat_events import post_system_event

router = APIRouter(prefix="/dynamics", tags=["vault"])


def _purge_expired(db: Session, dynamic_id: str) -> None:
    now = datetime.utcnow()
    db.query(VaultImage).filter(
        VaultImage.dynamic_id == dynamic_id,
        VaultImage.expires_at.isnot(None),
        VaultImage.expires_at < now,
    ).delete(synchronize_session=False)


def _import_missing_chat_images(db: Session, dynamic_id: str) -> None:
    """Backfill vault entries for chat photos that never made it in."""
    existing = {
        row[0]
        for row in db.query(VaultImage.source_chat_message_id)
        .filter(
            VaultImage.dynamic_id == dynamic_id,
            VaultImage.source_chat_message_id.isnot(None),
        )
        .all()
    }
    messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.dynamic_id == dynamic_id,
            ChatMessage.message_type == ChatMessageType.image,
            ChatMessage.image_data != "",
        )
        .all()
    )
    for message in messages:
        if message.id in existing:
            continue
        db.add(
            VaultImage(
                dynamic_id=dynamic_id,
                uploaded_by_membership_id=message.sender_membership_id,
                source_chat_message_id=message.id,
                title="From chat",
                image_encrypted=f"ubetra:plain:{message.image_data}",
                image_blurred=bool(message.image_blurred),
                created_at=message.created_at,
            )
        )


def _vault_out(image: VaultImage, membership_id: str) -> VaultImageOut:
    return VaultImageOut(
        id=image.id,
        title=image.title or "",
        image_encrypted=image.image_encrypted,
        image_blurred=bool(image.image_blurred),
        source_chat_message_id=image.source_chat_message_id,
        uploaded_by_membership_id=image.uploaded_by_membership_id,
        is_yours=image.uploaded_by_membership_id == membership_id,
        created_at=image.created_at,
        expires_at=image.expires_at,
    )


@router.get("/{dynamic_id}/vault", response_model=list[VaultImageOut])
def list_vault_images(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[VaultImageOut]:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    _purge_expired(db, dynamic_id)
    _import_missing_chat_images(db, dynamic_id)
    db.commit()
    images = (
        db.query(VaultImage)
        .filter(VaultImage.dynamic_id == dynamic_id)
        .order_by(VaultImage.created_at.desc())
        .all()
    )
    return [_vault_out(image, membership.id) for image in images]


@router.post(
    "/{dynamic_id}/vault",
    response_model=VaultImageOut,
    status_code=status.HTTP_201_CREATED,
)
def add_vault_image(
    dynamic_id: str,
    payload: VaultImageCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VaultImageOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    expires_at = None
    if payload.expire_hours:
        expires_at = datetime.utcnow() + timedelta(hours=payload.expire_hours)

    image = VaultImage(
        dynamic_id=dynamic_id,
        uploaded_by_membership_id=membership.id,
        source_chat_message_id=payload.source_chat_message_id,
        title=(payload.title or "").strip(),
        image_encrypted=payload.image_encrypted.strip(),
        image_blurred=payload.image_blurred,
        expires_at=expires_at,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return _vault_out(image, membership.id)


@router.patch("/{dynamic_id}/vault/{image_id}", response_model=VaultImageOut)
def update_vault_image(
    dynamic_id: str,
    image_id: str,
    payload: VaultImageUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VaultImageOut:
    membership = get_membership(dynamic_id, user, db)
    image = (
        db.query(VaultImage)
        .filter(VaultImage.id == image_id, VaultImage.dynamic_id == dynamic_id)
        .first()
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    if payload.title is not None:
        image.title = payload.title.strip()
    if payload.image_blurred is not None:
        image.image_blurred = payload.image_blurred
    db.commit()
    db.refresh(image)
    return _vault_out(image, membership.id)


@router.delete(
    "/{dynamic_id}/vault/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_vault_image(
    dynamic_id: str,
    image_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    membership = get_membership(dynamic_id, user, db)
    image = (
        db.query(VaultImage)
        .filter(VaultImage.id == image_id, VaultImage.dynamic_id == dynamic_id)
        .first()
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    title = (image.title or "Untitled").strip() or "Untitled"
    chat_id = image.source_chat_message_id
    if chat_id:
        db.query(VaultImage).filter(
            VaultImage.dynamic_id == dynamic_id,
            VaultImage.source_chat_message_id == chat_id,
        ).delete(synchronize_session=False)
        db.flush()
        chat_msg = db.get(ChatMessage, chat_id)
        if chat_msg is not None and chat_msg.dynamic_id == dynamic_id:
            db.delete(chat_msg)
    else:
        db.delete(image)
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"deleted vault image “{title[:80]}”",
        force=True,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
