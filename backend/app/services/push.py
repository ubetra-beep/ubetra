from __future__ import annotations

import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ChatMessageType, Dynamic, Membership, PushSubscription, User
from .vapid import is_configured, vapid_contact, vapid_private_key

logger = logging.getLogger(__name__)


def _subscription_info(sub: PushSubscription) -> dict[str, Any]:
    return {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }


def send_web_push(subscription: PushSubscription, payload: dict[str, Any]) -> bool:
    if not is_configured():
        return False
    try:
        webpush(
            subscription_info=_subscription_info(subscription),
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key(),
            vapid_claims={"sub": vapid_contact()},
        )
        return True
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            return False
        logger.warning("Web push failed: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Web push error: %s", exc)
        return False


def _message_preview(
    message_type: ChatMessageType,
    *,
    body: str,
    e2e_enabled: bool,
    sender_name: str,
) -> tuple[str, str]:
    if message_type == ChatMessageType.image:
        return f"{sender_name}", "Sent an image"
    if e2e_enabled or not body.strip():
        return f"{sender_name}", "New encrypted message"
    preview = body.strip().replace("\n", " ")
    if len(preview) > 120:
        preview = f"{preview[:119]}…"
    return f"{sender_name}", preview


def notify_chat_push(
    db: Session,
    *,
    dynamic_id: str,
    sender_membership_id: str,
    message_type: ChatMessageType,
    body: str,
    e2e_enabled: bool,
) -> None:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None or not bool(getattr(dynamic, "chat_push_enabled", True)):
        return

    sender = db.get(Membership, sender_membership_id)
    if sender is None:
        return

    if message_type == ChatMessageType.system:
        return

    partner_user_ids = {
        m.user_id
        for m in db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
        if m.id != sender_membership_id
    }
    if not partner_user_ids:
        return

    title, preview = _message_preview(
        message_type,
        body=body,
        e2e_enabled=e2e_enabled,
        sender_name=sender.display_name,
    )
    payload = {
        "title": title,
        "body": preview,
        "url": f"/#/chat/{dynamic_id}",
        "dynamic_id": dynamic_id,
        "tag": f"ubetra-chat-{dynamic_id}",
    }

    stale: list[PushSubscription] = []
    for user_id in partner_user_ids:
        user = db.get(User, user_id)
        if user is None or not bool(getattr(user, "push_enabled", True)):
            continue
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        for sub in subs:
            if not send_web_push(sub, payload):
                stale.append(sub)

    for sub in stale:
        db.delete(sub)
    if stale:
        db.commit()


def notify_chat_push_async(
    *,
    dynamic_id: str,
    sender_membership_id: str,
    message_type: ChatMessageType,
    body: str,
    e2e_enabled: bool,
) -> None:
    db = SessionLocal()
    try:
        notify_chat_push(
            db,
            dynamic_id=dynamic_id,
            sender_membership_id=sender_membership_id,
            message_type=message_type,
            body=body,
            e2e_enabled=e2e_enabled,
        )
    finally:
        db.close()


def notify_playtime_push(
    db: Session,
    *,
    dynamic_id: str,
    sender_membership_id: str,
    title: str,
    body: str,
    url: str | None = None,
) -> None:
    """Push for shared (non-hidden) playtime outcomes — always notifies the partner."""
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None or not bool(getattr(dynamic, "chat_push_enabled", True)):
        return

    partner_user_ids = {
        m.user_id
        for m in db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
        if m.id != sender_membership_id
    }
    if not partner_user_ids:
        return

    payload = {
        "title": title[:80] or "Playtime",
        "body": (body or "")[:160],
        "url": url or f"/#/dynamic/{dynamic_id}/assistant/games/spin",
        "dynamic_id": dynamic_id,
        "tag": f"ubetra-playtime-{dynamic_id}",
    }

    stale: list[PushSubscription] = []
    for user_id in partner_user_ids:
        user = db.get(User, user_id)
        if user is None or not bool(getattr(user, "push_enabled", True)):
            continue
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        for sub in subs:
            if not send_web_push(sub, payload):
                stale.append(sub)

    for sub in stale:
        db.delete(sub)
    if stale:
        db.commit()


def notify_playtime_push_async(
    *,
    dynamic_id: str,
    sender_membership_id: str,
    title: str,
    body: str,
    url: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        notify_playtime_push(
            db,
            dynamic_id=dynamic_id,
            sender_membership_id=sender_membership_id,
            title=title,
            body=body,
            url=url,
        )
    finally:
        db.close()


def notify_keyholders_push(
    db: Session,
    *,
    dynamic_id: str,
    title: str,
    body: str,
    url: str | None = None,
    tag: str | None = None,
) -> None:
    """Push only to dominant / keyholder memberships in the dynamic."""
    from ..models import PartnerRole

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None or not bool(getattr(dynamic, "chat_push_enabled", True)):
        return

    keyholder_user_ids = {
        m.user_id
        for m in db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
        if m.role == PartnerRole.dominant
    }
    if not keyholder_user_ids:
        return

    payload = {
        "title": title[:80] or "Chastity",
        "body": (body or "")[:160],
        "url": url or f"/#/dynamic/{dynamic_id}/chastity",
        "dynamic_id": dynamic_id,
        "tag": tag or f"ubetra-chastity-timer-{dynamic_id}",
    }

    stale: list[PushSubscription] = []
    for user_id in keyholder_user_ids:
        user = db.get(User, user_id)
        if user is None or not bool(getattr(user, "push_enabled", True)):
            continue
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        for sub in subs:
            if not send_web_push(sub, payload):
                stale.append(sub)

    for sub in stale:
        db.delete(sub)
    if stale:
        db.commit()