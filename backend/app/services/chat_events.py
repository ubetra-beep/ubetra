from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import ChatMessage, ChatMessageType, Dynamic, Membership


def _truncate(text: str, limit: int = 72) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def post_system_event(
    db: Session,
    dynamic_id: str,
    actor: Membership,
    text: str,
    *,
    from_label: str | None = None,
    action: str = "",
    payload: dict | None = None,
) -> None:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None or not bool(getattr(dynamic, "chat_system_events", True)):
        return

    expires_at = None
    if not dynamic.chat_retain_history:
        hours = max(1, int(dynamic.chat_expire_hours or 24))
        expires_at = datetime.utcnow() + timedelta(hours=hours)

    body = text.strip()
    if from_label:
        body = f"[[from:{from_label.strip()}]]{body}"

    db.add(
        ChatMessage(
            dynamic_id=dynamic_id,
            sender_membership_id=actor.id,
            message_type=ChatMessageType.system,
            body=body,
            action=(action or "").strip()[:64],
            payload_json=json.dumps(payload or {}, ensure_ascii=False) if payload else "",
            expires_at=expires_at,
        )
    )


def post_activity_event(
    db: Session,
    *,
    dynamic_id: str,
    actor: Membership,
    action: str,
    text: str,
    path: str,
    link_label: str = "Open",
    subject_membership_id: str | None = None,
    from_label: str | None = None,
    extra: dict | None = None,
) -> None:
    """Structured, clickable activity log for chat."""
    link = f"[[ubetra:{path}|{link_label}]]"
    body = f"{text.strip()} {link}".strip()
    payload = {
        "path": path,
        "link_label": link_label,
        "subject_membership_id": subject_membership_id,
        **(extra or {}),
    }
    post_system_event(
        db,
        dynamic_id,
        actor,
        body,
        from_label=from_label,
        action=action,
        payload=payload,
    )


def task_snippet(content: str) -> str:
    return f"“{_truncate(content)}”"
