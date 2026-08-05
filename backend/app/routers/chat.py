from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import (
    ChatKeyTransfer,
    ChatMessage,
    ChatMessageType,
    Dynamic,
    Membership,
    PartnerRole,
    User,
    VaultImage,
)

# Server-side chat cache default (multi-device / offline sync).
DEFAULT_CHAT_EXPIRE_HOURS = 24 * 30  # 30 days

from ..schemas import (
    ChatKeyRedeemIn,
    ChatKeyRedeemOut,
    ChatKeyShareIn,
    ChatKeyShareOut,
    ChatMessageCreate,
    ChatMessageOut,
    ChatSettingsOut,
    ChatSettingsUpdate,
    ChatSharedKeyIn,
    ChatSharedKeyOut,
    ImageUnlockResolve,
    SettingsRequestCreate,
    SettingsRequestResolve,
)
from ..services.chat_events import post_system_event
from ..services.chat_presence import active_typers, mark_typing
from ..services.push import notify_chat_push_async
from ..services.settings_policy import (
    apply_setting,
    is_dominant,
    require_dom_for_setting,
    setting_label,
)

router = APIRouter(tags=["chat"])

_SHARE_TTL = timedelta(minutes=30)
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _purge_expired(db: Session, dynamic_id: str) -> None:
    now = datetime.utcnow()
    db.query(ChatMessage).filter(
        ChatMessage.dynamic_id == dynamic_id,
        ChatMessage.expires_at.isnot(None),
        ChatMessage.expires_at < now,
    ).delete(synchronize_session=False)
    db.query(ChatKeyTransfer).filter(
        ChatKeyTransfer.dynamic_id == dynamic_id,
        ChatKeyTransfer.redeemed_at.is_(None),
        ChatKeyTransfer.expires_at < now,
    ).delete(synchronize_session=False)


def _message_out(message: ChatMessage, viewer: Membership) -> ChatMessageOut:
    sender = message.sender_membership_id
    display = "You"
    if hasattr(message, "sender") and message.sender:
        display = message.sender.display_name
    # System events: show live membership name (or Game via body [[from:]])
    if message.message_type == ChatMessageType.system and hasattr(message, "sender") and message.sender:
        display = message.sender.display_name
    payload = {}
    raw = getattr(message, "payload_json", None) or ""
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                payload = data
        except json.JSONDecodeError:
            payload = {}
    return ChatMessageOut(
        id=message.id,
        sender_display_name=display if sender != viewer.id or message.message_type == ChatMessageType.system else "You",
        is_yours=sender == viewer.id,
        message_type=message.message_type,
        body=message.body,
        body_encrypted=message.body_encrypted,
        image_data=message.image_data,
        image_blurred=message.image_blurred,
        image_locked=bool(getattr(message, "image_locked", False)),
        image_unlock_granted=bool(getattr(message, "image_unlock_granted", False)),
        action=getattr(message, "action", None) or "",
        payload=payload,
        created_at=message.created_at,
    )


def _new_share_code(db: Session) -> str:
    for _ in range(12):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        exists = db.query(ChatKeyTransfer).filter(ChatKeyTransfer.code == code).first()
        if not exists:
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate share code",
    )


def _chat_settings_out(dynamic: Dynamic, membership: Membership) -> ChatSettingsOut:
    return ChatSettingsOut(
        retain_history=bool(dynamic.chat_retain_history),
        e2e_enabled=bool(dynamic.chat_e2e_enabled),
        key_configured=bool((getattr(dynamic, "chat_shared_key", None) or "").strip()),
        expire_hours=int(dynamic.chat_expire_hours or DEFAULT_CHAT_EXPIRE_HOURS),
        system_events=bool(getattr(dynamic, "chat_system_events", True)),
        push_enabled=bool(getattr(dynamic, "chat_push_enabled", True)),
        you_are_dominant=is_dominant(membership),
        chastity_sub_can_delete_breaks=bool(
            getattr(dynamic, "chastity_sub_can_delete_breaks", True)
        ),
        clear_dom_only=bool(getattr(dynamic, "chat_clear_dom_only", False)),
    )


@router.get("/dynamics/{dynamic_id}/chat/settings", response_model=ChatSettingsOut)
def get_chat_settings(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSettingsOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return _chat_settings_out(dynamic, membership)


@router.put("/dynamics/{dynamic_id}/chat/settings", response_model=ChatSettingsOut)
def update_chat_settings(
    dynamic_id: str,
    payload: ChatSettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSettingsOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    was_retain = bool(dynamic.chat_retain_history)

    if payload.retain_history is not None and payload.retain_history != was_retain:
        require_dom_for_setting(membership, "chat.retain_history")
        dynamic.chat_retain_history = payload.retain_history
    if payload.system_events is not None and payload.system_events != bool(
        getattr(dynamic, "chat_system_events", True)
    ):
        require_dom_for_setting(membership, "chat.system_events")
        dynamic.chat_system_events = payload.system_events
    if payload.chastity_sub_can_delete_breaks is not None:
        require_dom_for_setting(membership, "chastity.sub_can_delete_breaks")
        dynamic.chastity_sub_can_delete_breaks = payload.chastity_sub_can_delete_breaks
    if payload.clear_dom_only is not None and payload.clear_dom_only != bool(
        getattr(dynamic, "chat_clear_dom_only", False)
    ):
        require_dom_for_setting(membership, "chat.clear_dom_only")
        dynamic.chat_clear_dom_only = bool(payload.clear_dom_only)
    if payload.e2e_enabled is not None:
        dynamic.chat_e2e_enabled = payload.e2e_enabled
    if payload.expire_hours is not None:
        dynamic.chat_expire_hours = payload.expire_hours
    if payload.push_enabled is not None:
        dynamic.chat_push_enabled = payload.push_enabled

    if was_retain and not bool(dynamic.chat_retain_history):
        db.query(ChatMessage).filter(ChatMessage.dynamic_id == dynamic_id).delete(
            synchronize_session=False
        )
    db.commit()
    return _chat_settings_out(dynamic, membership)


@router.post("/dynamics/{dynamic_id}/chat/clear")
def clear_chat_history(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if bool(getattr(dynamic, "chat_clear_dom_only", False)) and not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can clear chat for this dynamic.",
        )
    deleted = (
        db.query(ChatMessage)
        .filter(ChatMessage.dynamic_id == dynamic_id)
        .delete(synchronize_session=False)
    )
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"cleared chat history ({deleted} message(s))",
        force=True,
    )
    db.commit()
    return {"ok": True, "deleted": deleted}


@router.get("/dynamics/{dynamic_id}/chat/key", response_model=ChatSharedKeyOut)
def get_shared_chat_key(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSharedKeyOut:
    """Return the shared chat key for any member (same pattern as shared AI key)."""
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not dynamic.chat_e2e_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encrypted chat is not enabled for this dynamic",
        )
    key = (getattr(dynamic, "chat_shared_key", None) or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No shared chat key yet — turn on encryption from a device to create one",
        )
    return ChatSharedKeyOut(key=key, configured=True)


@router.put("/dynamics/{dynamic_id}/chat/key", response_model=ChatSharedKeyOut)
def put_shared_chat_key(
    dynamic_id: str,
    payload: ChatSharedKeyIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSharedKeyOut:
    """Upload/set the shared chat key. First writer wins; later uploads must match."""
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    new_key = payload.key.strip()
    existing = (getattr(dynamic, "chat_shared_key", None) or "").strip()
    if existing and existing != new_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A shared chat key already exists for this dynamic",
        )
    if not existing:
        dynamic.chat_shared_key = new_key
        if not dynamic.chat_e2e_enabled:
            dynamic.chat_e2e_enabled = True
        db.commit()
    return ChatSharedKeyOut(key=new_key if existing else dynamic.chat_shared_key, configured=True)


@router.post(
    "/dynamics/{dynamic_id}/chat/key-share",
    response_model=ChatKeyShareOut,
    status_code=status.HTTP_201_CREATED,
)
def share_chat_key(
    dynamic_id: str,
    payload: ChatKeyShareIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatKeyShareOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not dynamic.chat_e2e_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enable encrypted chat before sharing a key",
        )
    # Prefer seeding the shared key when missing (legacy share codes still work).
    key = payload.key.strip()
    if not (getattr(dynamic, "chat_shared_key", None) or "").strip():
        dynamic.chat_shared_key = key

    _purge_expired(db, dynamic_id)
    code = _new_share_code(db)
    expires_at = datetime.utcnow() + _SHARE_TTL
    db.add(
        ChatKeyTransfer(
            dynamic_id=dynamic_id,
            code=code,
            key_payload=key,
            created_by_membership_id=membership.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return ChatKeyShareOut(
        code=code,
        expires_at=expires_at,
        redeem_hint="Settings → Privacy & security → Redeem partner key",
    )


@router.post("/dynamics/{dynamic_id}/chat/key-redeem", response_model=ChatKeyRedeemOut)
def redeem_chat_key(
    dynamic_id: str,
    payload: ChatKeyRedeemIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatKeyRedeemOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)

    code = payload.code.strip().upper()
    transfer = (
        db.query(ChatKeyTransfer)
        .filter(
            ChatKeyTransfer.dynamic_id == dynamic_id,
            ChatKeyTransfer.code == code,
        )
        .first()
    )
    if transfer is None:
        # Fall back to shared key if encryption is already set up server-side.
        if dynamic is not None:
            shared = (getattr(dynamic, "chat_shared_key", None) or "").strip()
            if shared:
                return ChatKeyRedeemOut(key=shared)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired code")
    if transfer.redeemed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code already used")
    if transfer.expires_at < datetime.utcnow():
        db.delete(transfer)
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired code")

    transfer.redeemed_at = datetime.utcnow()
    transfer.redeemed_by_membership_id = membership.id
    key = transfer.key_payload
    if dynamic is not None and not (getattr(dynamic, "chat_shared_key", None) or "").strip():
        dynamic.chat_shared_key = key
        dynamic.chat_e2e_enabled = True
    db.commit()
    return ChatKeyRedeemOut(key=key)


@router.get("/dynamics/{dynamic_id}/chat/messages", response_model=list[ChatMessageOut])
def list_messages(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChatMessageOut]:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    _purge_expired(db, dynamic_id)
    db.commit()

    messages = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.sender))
        .filter(ChatMessage.dynamic_id == dynamic_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(200)
        .all()
    )
    return [_message_out(m, membership) for m in messages]


@router.post("/dynamics/{dynamic_id}/chat/typing", status_code=status.HTTP_204_NO_CONTENT)
def post_typing(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    membership = get_membership(dynamic_id, user, db)
    mark_typing(dynamic_id, membership.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dynamics/{dynamic_id}/chat/presence")
def get_presence(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    ids = active_typers(dynamic_id, exclude_membership_id=membership.id)
    if not ids:
        return {"typing": []}
    rows = (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id, Membership.id.in_(ids))
        .all()
    )
    by_id = {m.id: m for m in rows}
    typing = [
        {"membership_id": mid, "display_name": by_id[mid].display_name if mid in by_id else "Partner"}
        for mid in ids
        if mid in by_id
    ]
    return {"typing": typing}


@router.post(
    "/dynamics/{dynamic_id}/chat/messages",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    dynamic_id: str,
    payload: ChatMessageCreate,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatMessageOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    if payload.message_type == ChatMessageType.text:
        if dynamic.chat_e2e_enabled:
            if not payload.body_encrypted.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Encrypted body required when end-to-end mode is on",
                )
        elif not payload.body.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message body required",
            )

    if payload.message_type == ChatMessageType.image and not payload.image_data.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image data required",
        )

    image_locked = bool(payload.image_locked) and is_dominant(membership)
    if image_locked and payload.message_type != ChatMessageType.image:
        image_locked = False

    expires_at = None
    if not dynamic.chat_retain_history:
        hours = max(1, int(dynamic.chat_expire_hours or DEFAULT_CHAT_EXPIRE_HOURS))
        expires_at = datetime.utcnow() + timedelta(hours=hours)

    message = ChatMessage(
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        message_type=payload.message_type,
        body="" if dynamic.chat_e2e_enabled else payload.body.strip(),
        body_encrypted=payload.body_encrypted.strip() if dynamic.chat_e2e_enabled else "",
        image_data=payload.image_data.strip(),
        image_blurred=payload.image_blurred if payload.message_type == ChatMessageType.image else False,
        image_locked=image_locked,
        image_unlock_granted=False,
        action=(payload.action or "").strip()[:64],
        payload_json=json.dumps(payload.payload or {}, ensure_ascii=False)
        if payload.payload
        else "",
        expires_at=expires_at,
    )
    db.add(message)
    db.flush()

    if payload.message_type == ChatMessageType.image and payload.save_to_vault:
        encrypted = (payload.vault_image_encrypted or "").strip()
        if not encrypted and (payload.image_data or "").strip():
            # Client failed to encrypt — still archive so the vault is usable.
            encrypted = f"ubetra:plain:{payload.image_data.strip()}"
        if encrypted:
            db.add(
                VaultImage(
                    dynamic_id=dynamic_id,
                    uploaded_by_membership_id=membership.id,
                    source_chat_message_id=message.id,
                    title="From chat",
                    image_encrypted=encrypted,
                    image_blurred=payload.image_blurred,
                )
            )

    db.commit()
    db.refresh(message)
    message.sender = membership

    preview_body = payload.body.strip() if payload.message_type == ChatMessageType.text else ""
    if dynamic.chat_e2e_enabled:
        preview_body = ""
    background_tasks.add_task(
        notify_chat_push_async,
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        message_type=payload.message_type,
        body=preview_body,
        e2e_enabled=bool(dynamic.chat_e2e_enabled),
    )

    return _message_out(message, membership)


@router.post(
    "/dynamics/{dynamic_id}/settings-requests",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def create_settings_request(
    dynamic_id: str,
    payload: SettingsRequestCreate,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatMessageOut:
    membership = get_membership(dynamic_id, user, db)
    if is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keyholders can change settings directly.",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    label = (payload.setting_label or setting_label(payload.setting_key)).strip()
    note = (payload.note or "").strip()
    body_lines = [f"Settings request: {label}"]
    if payload.requested_value is not None:
        body_lines.append(f"Requested: {payload.requested_value}")
    if note:
        body_lines.append(note)
    body = "\n".join(body_lines)

    expires_at = None
    if not dynamic.chat_retain_history:
        hours = max(1, int(dynamic.chat_expire_hours or DEFAULT_CHAT_EXPIRE_HOURS))
        expires_at = datetime.utcnow() + timedelta(hours=hours)

    message = ChatMessage(
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        message_type=ChatMessageType.text,
        body=body,
        action="settings_request",
        payload_json=json.dumps(
            {
                "status": "pending",
                "setting_key": payload.setting_key,
                "setting_label": label,
                "requested_value": payload.requested_value,
                "note": note,
            },
            ensure_ascii=False,
        ),
        expires_at=expires_at,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    message.sender = membership

    background_tasks.add_task(
        notify_chat_push_async,
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        message_type=ChatMessageType.text,
        body=f"Settings request: {label}",
        e2e_enabled=False,
    )
    return _message_out(message, membership)


@router.post(
    "/dynamics/{dynamic_id}/chat/messages/{message_id}/resolve-settings-request",
    response_model=ChatMessageOut,
)
def resolve_settings_request(
    dynamic_id: str,
    message_id: str,
    payload: SettingsRequestResolve,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatMessageOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can resolve settings requests.",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    message = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.sender))
        .filter(ChatMessage.id == message_id, ChatMessage.dynamic_id == dynamic_id)
        .first()
    )
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if (message.action or "") != "settings_request":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not a settings request")

    data = {}
    if message.payload_json:
        try:
            data = json.loads(message.payload_json) or {}
        except json.JSONDecodeError:
            data = {}
    if data.get("status") and data.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already resolved")

    setting_key = str(data.get("setting_key") or "")
    label = str(data.get("setting_label") or setting_label(setting_key))
    requester = message.sender.display_name if message.sender else "partner"

    if payload.decision == "deny":
        summary = f"{membership.display_name} denied settings request from {requester}: {label}"
        data["status"] = "denied"
    else:
        value = payload.value if payload.value is not None else data.get("requested_value")
        change = apply_setting(db, dynamic, setting_key=setting_key, value=value)
        summary = f"{membership.display_name} approved settings request from {requester}: {change}"
        data["status"] = "approved"
        data["applied_value"] = value

    message.message_type = ChatMessageType.system
    message.body = summary
    message.action = "settings_request_resolved"
    message.payload_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    db.refresh(message)
    return _message_out(message, membership)


@router.post(
    "/dynamics/{dynamic_id}/chat/messages/{message_id}/request-image-unlock",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def request_image_unlock(
    dynamic_id: str,
    message_id: str,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatMessageOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    image_msg = (
        db.query(ChatMessage)
        .filter(ChatMessage.id == message_id, ChatMessage.dynamic_id == dynamic_id)
        .first()
    )
    if image_msg is None or image_msg.message_type != ChatMessageType.image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    if not bool(getattr(image_msg, "image_locked", False)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not locked")
    if bool(getattr(image_msg, "image_unlock_granted", False)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already unlocked")
    if image_msg.sender_membership_id == membership.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You sent this image — no unlock needed",
        )

    pending = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.dynamic_id == dynamic_id,
            ChatMessage.action == "image_unlock_request",
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(20)
        .all()
    )
    for row in pending:
        try:
            data = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            data = {}
        if data.get("image_message_id") == message_id and data.get("status", "pending") == "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Unlock already requested",
            )

    expires_at = None
    if not dynamic.chat_retain_history:
        hours = max(1, int(dynamic.chat_expire_hours or DEFAULT_CHAT_EXPIRE_HOURS))
        expires_at = datetime.utcnow() + timedelta(hours=hours)

    request_msg = ChatMessage(
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        message_type=ChatMessageType.text,
        body=f"{membership.display_name} requested unlock for a locked image",
        action="image_unlock_request",
        payload_json=json.dumps(
            {
                "status": "pending",
                "image_message_id": message_id,
            },
            ensure_ascii=False,
        ),
        expires_at=expires_at,
    )
    db.add(request_msg)
    db.commit()
    db.refresh(request_msg)
    request_msg.sender = membership

    background_tasks.add_task(
        notify_chat_push_async,
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        message_type=ChatMessageType.text,
        body="Image unlock requested",
        e2e_enabled=False,
    )
    return _message_out(request_msg, membership)


@router.post(
    "/dynamics/{dynamic_id}/chat/messages/{message_id}/resolve-image-unlock",
    response_model=ChatMessageOut,
)
def resolve_image_unlock(
    dynamic_id: str,
    message_id: str,
    payload: ImageUnlockResolve,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatMessageOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can resolve unlock requests.",
        )

    request_msg = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.sender))
        .filter(ChatMessage.id == message_id, ChatMessage.dynamic_id == dynamic_id)
        .first()
    )
    if request_msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if (request_msg.action or "") != "image_unlock_request":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not an unlock request")

    data = {}
    if request_msg.payload_json:
        try:
            data = json.loads(request_msg.payload_json) or {}
        except json.JSONDecodeError:
            data = {}
    if data.get("status") and data.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already resolved")

    image_id = str(data.get("image_message_id") or "")
    image_msg = (
        db.query(ChatMessage)
        .filter(ChatMessage.id == image_id, ChatMessage.dynamic_id == dynamic_id)
        .first()
        if image_id
        else None
    )
    requester = request_msg.sender.display_name if request_msg.sender else "partner"

    if payload.decision == "deny":
        data["status"] = "denied"
        summary = f"{membership.display_name} denied image unlock for {requester}"
    else:
        if image_msg is None or image_msg.message_type != ChatMessageType.image:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        image_msg.image_unlock_granted = True
        data["status"] = "approved"
        summary = f"{membership.display_name} unlocked an image for {requester}"

    request_msg.message_type = ChatMessageType.system
    request_msg.body = summary
    request_msg.action = "image_unlock_resolved"
    request_msg.payload_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    db.refresh(request_msg)
    return _message_out(request_msg, membership)
