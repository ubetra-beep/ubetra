"""Journal entries for the Knowledge / context section."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, JournalEntry, PartnerRole, User
from ..schemas import (
    JournalAssistOut,
    JournalAssistRequest,
    JournalDommeReviewOut,
    JournalDommeReviewRequest,
    JournalEntryCreate,
    JournalEntryOut,
    JournalEntryUpdate,
)
from ..services.chat_events import post_system_event
from ..services.context import build_dynamic_context
from ..services.llm import generate_text, is_llm_configured

router = APIRouter(prefix="/dynamics", tags=["journal"])

JOURNAL_SYSTEM_INSTRUCTION = (
    "You are a discreet private journaling assistant. Help the writer reflect, expand, or "
    "polish their own journal entry. Keep their voice and intent. Never role-play as their "
    "dominant/keyholder here — that happens elsewhere in the app. Adults only."
)


def _entry_out(entry: JournalEntry, *, requesting_membership_id: str | None = None) -> JournalEntryOut:
    is_author = requesting_membership_id is not None and entry.membership_id == requesting_membership_id
    hidden = not is_author and not bool(entry.partner_visible)
    return JournalEntryOut(
        id=entry.id,
        title="Private entry" if hidden else (entry.title or ""),
        body="" if hidden else (entry.body or ""),
        use_for_ai=bool(entry.use_for_ai),
        llm_assisted=bool(entry.llm_assisted),
        partner_visible=bool(entry.partner_visible),
        is_private_to_others=hidden,
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
    membership = get_membership(dynamic_id, user, db)
    rows = (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.membership))
        .filter(JournalEntry.dynamic_id == dynamic_id)
        .order_by(JournalEntry.updated_at.desc())
        .limit(100)
        .all()
    )
    return [_entry_out(row, requesting_membership_id=membership.id) for row in rows]


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
        partner_visible=bool(payload.partner_visible),
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
    return _entry_out(entry, requesting_membership_id=membership.id)


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
    if payload.partner_visible is not None:
        entry.partner_visible = bool(payload.partner_visible)
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return _entry_out(entry, requesting_membership_id=membership.id)


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
        include_tracking=bool(payload.context_flags and payload.context_flags.tracking),
        context_flags=payload.context_flags,
    )
    text = generate_text(
        user=user,
        user_prompt=user_prompt,
        dynamic_context=ctx,
        system_instruction=JOURNAL_SYSTEM_INSTRUCTION,
        dynamic=dynamic,
    )
    return JournalAssistOut(text=(text or "").strip())


@router.post("/{dynamic_id}/journal/{entry_id}/domme-review", response_model=JournalDommeReviewOut)
def domme_review_journal(
    dynamic_id: str,
    entry_id: str,
    payload: JournalDommeReviewRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> JournalDommeReviewOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can request a domme review.",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    entry = (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.membership))
        .filter(JournalEntry.id == entry_id, JournalEntry.dynamic_id == dynamic_id)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if not entry.partner_visible and entry.membership_id != membership.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This entry is private.")
    if not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure an AI key in Settings before using domme review.",
        )

    author_name = entry.membership.display_name if entry.membership else "Your partner"
    ctx = build_dynamic_context(db, dynamic, requesting_membership_id=membership.id, include_tracking=False)
    prompt = (
        f"Your partner ({author_name}) shared this journal entry titled \"{entry.title or 'Untitled'}\" "
        "with you as their keyholder/domme:\n\n"
        f"{(entry.body or '').strip() or '(empty)'}\n\n"
        "Write a short, in-character review as their dominant: what stands out about their headspace, "
        "and 1-2 concrete follow-up prompts, tasks, or reactions you could give them. Keep it under 180 words."
    )
    text = generate_text(user=user, user_prompt=prompt, dynamic_context=ctx, dynamic=dynamic)
    summary = (text or "").strip()
    if payload.post_system_event:
        post_system_event(
            db,
            dynamic_id,
            membership,
            f"reviewed {author_name}'s journal entry \"{entry.title or 'Untitled'}\"",
        )
    db.commit()
    return JournalDommeReviewOut(summary=summary)
