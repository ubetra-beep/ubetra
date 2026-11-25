"""Idempotent phone retries for chastity and tracking writes.

A repeated client_event_id returns the row already stored. When both sides
edited the same record, the newer updated_at wins. An older retry does not
overwrite a newer server row, and the phone keeps any local row it has not
pushed yet.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import ClientEvent


def clean_client_event_id(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_event_id is too long",
        )
    return text


def naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def incoming_is_older(current: datetime | None, incoming: datetime | None) -> bool:
    current_n = naive_utc(current)
    incoming_n = naive_utc(incoming)
    if current_n is None or incoming_n is None:
        return False
    return incoming_n < current_n


def remembered_resource_id(db: Session, dynamic_id: str, client_event_id: str | None) -> str | None:
    cid = clean_client_event_id(client_event_id)
    if not cid:
        return None
    row = db.get(ClientEvent, cid)
    if row is None:
        return None
    if row.dynamic_id != dynamic_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_event_id belongs to another dynamic",
        )
    return row.resource_id or ""


def remember_client_event(
    db: Session,
    *,
    dynamic_id: str,
    client_event_id: str | None,
    kind: str,
    resource_id: str,
    updated_at: datetime | None = None,
) -> None:
    cid = clean_client_event_id(client_event_id)
    if not cid or db.get(ClientEvent, cid) is not None:
        return
    db.add(
        ClientEvent(
            client_event_id=cid,
            dynamic_id=dynamic_id,
            kind=kind,
            resource_id=resource_id,
            updated_at=naive_utc(updated_at) or datetime.utcnow(),
        )
    )


def stamp_updated_at(current: datetime | None, incoming: datetime | None) -> datetime:
    incoming_n = naive_utc(incoming)
    if incoming_n is not None:
        return incoming_n
    return naive_utc(current) or datetime.utcnow()
