from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, User
from ..schemas import InterviewMessageOut, InterviewOut, InterviewReplyIn
from ..services.interview import (
    can_manually_complete,
    complete_interview,
    get_interview_messages,
    reply_to_interview,
    start_interview,
)

router = APIRouter(prefix="/dynamics", tags=["interview"])


def _interview_out(membership, messages) -> InterviewOut:
    return InterviewOut(
        completed=membership.interview_completed,
        summary=membership.interview_summary or "",
        message_count=len(messages),
        can_mark_complete=can_manually_complete(messages) or membership.interview_completed,
        messages=[
            InterviewMessageOut(
                id=m.id,
                role=m.role.value,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.get("/{dynamic_id}/interview", response_model=InterviewOut)
def get_interview(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewOut:
    membership = get_membership(dynamic_id, user, db)
    messages = get_interview_messages(db, membership.id)
    return _interview_out(membership, messages)


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
