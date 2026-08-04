from __future__ import annotations

import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ChatMessageType, Dynamic, Membership, NativePushToken, PushSubscription, User
from .fcm import fcm_configured, send_fcm_data_message
from .vapid import is_configured, vapid_contact, vapid_private_key

logger = logging.getLogger(__name__)


def _subscription_info(sub: PushSubscription) -> dict[str, Any]:
    return {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }


def send_web_push(subscription: PushSubscription, payload: dict[str, Any]) -> str:
    """Send a push. Returns 'ok', 'stale' (drop subscription), or 'error' (keep)."""
    if not is_configured():
        return "error"
    try:
        webpush(
            subscription_info=_subscription_info(subscription),
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key(),
            vapid_claims={"sub": vapid_contact()},
            # Keep undelivered pushes so Android/FCM can wake the device later.
            ttl=86400,
            # High urgency helps Android leave Doze sooner for chat/call alerts.
            headers={"Urgency": "high", "Topic": str(payload.get("tag") or "ubetra")[:32]},
        )
        return "ok"
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        # Gone / not found / forbidden = browser dropped the subscription.
        if status in (401, 403, 404, 410):
            logger.info("Web push stale subscription (%s): %s", status, subscription.endpoint[:80])
            return "stale"
        logger.warning("Web push failed (%s): %s", status, exc)
        return "error"
    except Exception as exc:
        logger.warning("Web push error: %s", exc)
        return "error"


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
    stale_native: list[NativePushToken] = []
    for user_id in partner_user_ids:
        user = db.get(User, user_id)
        if user is None or not bool(getattr(user, "push_enabled", True)):
            continue
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        for sub in subs:
            if send_web_push(sub, payload) == "stale":
                stale.append(sub)
        for native in db.query(NativePushToken).filter(NativePushToken.user_id == user_id).all():
            result = send_fcm_data_message(
                native.token,
                title=title,
                body=preview,
                data={
                    "url": payload["url"],
                    "dynamic_id": dynamic_id,
                    "tag": payload["tag"],
                    "kind": "chat",
                },
                kind="chat",
            )
            if result == "stale":
                stale_native.append(native)

    for sub in stale:
        db.delete(sub)
    for native in stale_native:
        db.delete(native)
    if stale or stale_native:
        db.commit()


def _notify_users_payload(
    db: Session,
    *,
    user_ids: set[str],
    title: str,
    body: str,
    url: str,
    tag: str,
    dynamic_id: str,
    kind: str = "chat",
) -> None:
    stale: list[PushSubscription] = []
    stale_native: list[NativePushToken] = []
    payload = {
        "title": title,
        "body": body,
        "url": url,
        "dynamic_id": dynamic_id,
        "tag": tag,
        "kind": kind,
    }
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is None or not bool(getattr(user, "push_enabled", True)):
            continue
        for sub in db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all():
            if send_web_push(sub, payload) == "stale":
                stale.append(sub)
        for native in db.query(NativePushToken).filter(NativePushToken.user_id == user_id).all():
            result = send_fcm_data_message(
                native.token,
                title=title,
                body=body,
                data={
                    "url": url,
                    "dynamic_id": dynamic_id,
                    "tag": tag,
                    "kind": kind,
                },
                kind=kind,
            )
            if result == "stale":
                stale_native.append(native)
    for sub in stale:
        db.delete(sub)
    for native in stale_native:
        db.delete(native)
    if stale or stale_native:
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

    _notify_users_payload(
        db,
        user_ids=partner_user_ids,
        title=title[:80] or "Playtime",
        body=(body or "")[:160],
        url=url or f"/#/dynamic/{dynamic_id}/assistant/games/spin",
        tag=f"ubetra-playtime-{dynamic_id}",
        dynamic_id=dynamic_id,
        kind="chat",
    )


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

    _notify_users_payload(
        db,
        user_ids=keyholder_user_ids,
        title=title[:80] or "Chastity",
        body=(body or "")[:160],
        url=url or f"/#/dynamic/{dynamic_id}/chastity",
        tag=tag or f"ubetra-chastity-timer-{dynamic_id}",
        dynamic_id=dynamic_id,
        kind="chat",
    )