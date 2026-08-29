from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, User
from ..schemas import InterviewAnswersIn, InterviewMessageOut, InterviewOut, InterviewReplyIn
from ..services.interview import (
    INTERVIEW_PROMPTS,
    can_manually_complete,
    complete_interview,
    get_interview_messages,
    interview_uses_form,
    parse_interview_answers,
    reply_to_interview,
    save_interview_answers,
    start_interview,
)

router = APIRouter(prefix="/dynamics", tags=["interview"])


def _interview_out(membership, messages, *, user: User, dynamic: Dynamic | None) -> InterviewOut:
    form = interview_uses_form(user, dynamic)
    answers = parse_interview_answers(getattr(membership, "interview_answers", None))
    filled = sum(1 for p in INTERVIEW_PROMPTS if (answers.get(p["id"]) or "").strip())
    return InterviewOut(
        completed=membership.interview_completed,
        summary=membership.interview_summary or "",
        message_count=len(messages),
        can_mark_complete=(
            (filled >= 2 or membership.interview_completed)
            if form
            else (can_manually_complete(messages) or membership.interview_completed)
        ),
        messages=[
            InterviewMessageOut(
                id=m.id,
                role=m.role.value,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
        mode="form" if form else "chat",
        prompts=list(INTERVIEW_PROMPTS),
        answers=answers,
    )


@router.get("/{dynamic_id}/interview", response_model=InterviewOut)
def get_interview(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    messages = get_interview_messages(db, membership.id)
    return _interview_out(membership, messages, user=user, dynamic=dynamic)


@router.post("/{dynamic_id}/interview/start", response_model=InterviewMessageOut)
def begin_interview(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewMessageOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    message = start_interview(db, user=user, dynamic=dynamic, membership=membership)
    return InterviewMessageOut(
        id=message.id,
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
    )


@router.post("/{dynamic_id}/interview/reply", response_model=InterviewOut)
def send_interview_reply(
    dynamic_id: str,
    payload: InterviewReplyIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    reply_to_interview(
        db,
        user=user,
        dynamic=dynamic,
        membership=membership,
        user_message=payload.message,
    )
    db.refresh(membership)
    return get_interview(dynamic_id, user, db)


@router.put("/{dynamic_id}/interview/answers", response_model=InterviewOut)
def put_interview_answers(
    dynamic_id: str,
    payload: InterviewAnswersIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    save_interview_answers(
        db,
        user=user,
        dynamic=dynamic,
        membership=membership,
        answers=payload.answers,
        complete=payload.complete,
    )
    db.refresh(membership)
    return get_interview(dynamic_id, user, db)


@router.post("/{dynamic_id}/interview/complete", response_model=InterviewOut)
def mark_interview_complete(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    complete_interview(db, user=user, dynamic=dynamic, membership=membership)
    db.refresh(membership)
    return get_interview(dynamic_id, user, db)
