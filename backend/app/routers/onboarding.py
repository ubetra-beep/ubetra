from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Dynamic, Membership, User
from ..schemas import OnboardingCompleteOut, OnboardingStatusOut, SptiUpdate

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _primary_membership(db: Session, user_id: str) -> tuple[Membership | None, Dynamic | None]:
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user_id)
        .order_by(Membership.created_at)
        .first()
    )
    if membership is None:
        return None, None
    dynamic = db.get(Dynamic, membership.dynamic_id)
    return membership, dynamic


@router.get("/status", response_model=OnboardingStatusOut)
def onboarding_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OnboardingStatusOut:
    membership, dynamic = _primary_membership(db, user.id)
    spti_data = (membership.spti_data or "") if membership else ""
    spti_skipped = spti_data == "__skipped__"
    api_skipped = bool(dynamic and (dynamic.shared_llm_model or "") == "__skipped__")
    return OnboardingStatusOut(
        onboarding_completed=bool(user.onboarding_completed),
        has_dynamic=membership is not None,
        dynamic_id=membership.dynamic_id if membership else None,
        dynamic_name=dynamic.name if dynamic else None,
        invite_code=dynamic.invite_code if dynamic else None,
        shared_llm_configured=bool(dynamic and (dynamic.shared_llm_api_key or "").strip()),
        api_skipped=api_skipped,
        spti_completed=bool(membership and membership.spti_completed_at),
        spti_skipped=spti_skipped,
        survey_submitted=bool(membership and membership.survey_submitted),
        survey_skipped=bool(membership and membership.survey_skipped),
    )


@router.post("/skip-api", response_model=OnboardingStatusOut)
def skip_api(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OnboardingStatusOut:
    membership, dynamic = _primary_membership(db, user.id)
    if membership is None or dynamic is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create or join a dynamic before skipping API setup",
        )
    if not (dynamic.shared_llm_api_key or "").strip():
        dynamic.shared_llm_model = "__skipped__"
        db.commit()
    return onboarding_status(user, db)


@router.post("/skip-survey", response_model=OnboardingStatusOut)
def skip_survey(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OnboardingStatusOut:
    membership, _dynamic = _primary_membership(db, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create or join a dynamic before skipping the kink survey",
        )
    membership.survey_skipped = True
    db.commit()
    return onboarding_status(user, db)


@router.put("/spti", response_model=OnboardingStatusOut)
def save_spti(
    payload: SptiUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OnboardingStatusOut:
    membership, _dynamic = _primary_membership(db, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create or join a dynamic before saving SPTI results",
        )
    if payload.skipped:
        membership.spti_data = "__skipped__"
        membership.spti_completed_at = None
    else:
        data = payload.results.strip()
        if not data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Paste SPTI results or skip")
        membership.spti_data = data
        membership.spti_completed_at = datetime.utcnow()
    db.commit()
    return onboarding_status(user, db)


@router.post("/complete", response_model=OnboardingCompleteOut)
def complete_onboarding(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OnboardingCompleteOut:
    membership, _dynamic = _primary_membership(db, user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create or join a dynamic first",
        )
    user.onboarding_completed = True
    db.commit()
    return OnboardingCompleteOut(
        onboarding_completed=True,
        dynamic_id=membership.dynamic_id,
    )
