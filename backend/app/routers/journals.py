"""Journal entries for the Knowledge / context section."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, JournalEntry, User
from ..schemas import (
    JournalAssistOut,
    JournalAssistRequest,
    JournalEntryCreate,
    JournalEntryOut,
    JournalEntryUpdate,
)
from ..services.context import build_dynamic_context
from ..services.llm import generate_text, is_llm_configured

router = APIRouter(prefix="/dynamics", tags=["journal"])


def _entry_out(entry: JournalEntry) -> JournalEntryOut:
    return JournalEntryOut(
        id=entry.id,
        title=entry.title or "",
        body=entry.body or "",
        use_for_ai=bool(entry.use_for_ai),
        llm_assisted=bool(entry.llm_assisted),
        author_display_name=entry.membership.display_name if entry.membership else "Partner",
        membership_id=entry.membership_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/{dynamic_id}/journal", response_model=list[JournalEntryOut])
def list_journal_entries(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[JournalEntryOut]:
    get_membership(dynamic_id, user, db)
    rows = (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.membership))
        .filter(JournalEntry.dynamic_id == dynamic_id)
        .order_by(JournalEntry.updated_at.desc())
        .limit(100)
        .all()
    )
    return [_entry_out(row) for row in rows]


@router.post(
    "/{dynamic_id}/journal",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_journal_entry(
    dynamic_id: str,
    payload: JournalEntryCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> JournalEntryOut:
    membership = get_membership(dynamic_id, user, db)
    now = datetime.utcnow()
    entry = JournalEntry(
        dynamic_id=dynamic_id,
        membership_id=membership.id,
        title=(payload.title or "").strip()[:200] or "Journal entry",
        body=(payload.body or "").strip(),
        use_for_ai=bool(payload.use_for_ai),
        llm_assisted=bool(payload.llm_assisted),
        created_at=now,
        updated_at=now,
    )
    db.add(entry)
    db.commit()
    entry = (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.membership))
        .filter(JournalEntry.id == entry.id)
        .one()
    )
    return _entry_out(entry)


@router.patch("/{dynamic_id}/journal/{entry_id}", response_model=JournalEntryOut)
def update_journal_entry(
    dynamic_id: str,
    entry_id: str,
    payload: JournalEntryUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> JournalEntryOut:
    membership = get_membership(dynamic_id, user, db)
    entry = (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.membership))
        .filter(JournalEntry.id == entry_id, JournalEntry.dynamic_id == dynamic_id)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if entry.membership_id != membership.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own journal entries.",
        )
    if payload.title is not None:
        entry.title = payload.title.strip()[:200] or entry.title
    if payload.body is not None:
        entry.body = payload.body.strip()
    if payload.use_for_ai is not None:
        entry.use_for_ai = bool(payload.use_for_ai)
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return _entry_out(entry)


@router.delete(
    "/{dynamic_id}/journal/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_journal_entry(
    dynamic_id: str,
    entry_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    membership = get_membership(dynamic_id, user, db)
    entry = (
        db.query(JournalEntry)
        .filter(JournalEntry.id == entry_id, JournalEntry.dynamic_id == dynamic_id)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if entry.membership_id != membership.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own journal entries.",
        )
    db.delete(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{dynamic_id}/journal/assist", response_model=JournalAssistOut)
def assist_journal(
    dynamic_id: str,
    payload: JournalAssistRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> JournalAssistOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure an AI key in Settings before using journal assist.",
        )
    draft = (payload.draft or "").strip()
    user_prompt = (
        "Help with private journaling. Rewrite or expand the draft based on the request. "
        "Return only the journal text, no preamble.\n\n"
        f"Request: {payload.prompt.strip()}\n\n"
        f"Current draft:\n{draft or '(empty)'}"
    )
    ctx = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=False,
    )
    text = generate_text(
        user=user,
        user_prompt=user_prompt,
        dynamic_context=ctx,
        system_instruction="You are a discreet journaling assistant. Keep the user's voice. Adults only.",
        dynamic=dynamic,
    )
    return JournalAssistOut(text=(text or "").strip())
