from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Agreement, Dynamic, Membership, PartnerRole, User
from ..schemas import (
    AgreementCreate,
    AgreementListOut,
    AgreementOut,
    AgreementUpdate,
    SuggestedAgreementOut,
    SuggestedAgreementsOut,
)
from ..services.context import build_dynamic_context, get_memberships
from ..services.llm import generate_text, is_llm_configured

router = APIRouter(prefix="/dynamics", tags=["agreements"])


def _agreement_out(agreement: Agreement, db: Session) -> AgreementOut:
    pending_by_name = None
    if agreement.pending_by_membership_id:
        pending_by = db.get(Membership, agreement.pending_by_membership_id)
        pending_by_name = pending_by.display_name if pending_by else None
    return AgreementOut(
        id=agreement.id,
        title=agreement.title,
        approved_content=agreement.approved_content,
        pending_content=agreement.pending_content,
        has_approved=bool(agreement.approved_content.strip()),
        has_pending=bool(agreement.pending_content.strip()),
        pending_by_display_name=pending_by_name,
        pending_at=agreement.pending_at,
        approved_at=agreement.approved_at,
        position=agreement.position,
        created_at=agreement.created_at,
    )


def _list_out(agreements: list[Agreement], membership: Membership, db: Session) -> AgreementListOut:
    items = [_agreement_out(a, db) for a in agreements]
    return AgreementListOut(
        agreements=items,
        approved_count=sum(1 for a in items if a.has_approved),
        pending_count=sum(1 for a in items if a.has_pending),
        you_are_dominant=membership.role == PartnerRole.dominant,
    )


def _next_position(db: Session, dynamic_id: str) -> int:
    current = (
        db.query(func.max(Agreement.position))
        .filter(Agreement.dynamic_id == dynamic_id)
        .scalar()
    )
    return (current or 0) + 1


def _apply_dom_approval(agreement: Agreement, membership: Membership, content: str) -> None:
    agreement.approved_content = content
    agreement.pending_content = ""
    agreement.pending_by_membership_id = None
    agreement.pending_at = None
    agreement.approved_at = datetime.utcnow()
    agreement.approved_by_membership_id = membership.id
    agreement.updated_at = datetime.utcnow()


def _set_pending(agreement: Agreement, membership: Membership, content: str) -> None:
    agreement.pending_content = content
    agreement.pending_by_membership_id = membership.id
    agreement.pending_at = datetime.utcnow()
    agreement.updated_at = datetime.utcnow()


@router.get("/{dynamic_id}/agreements", response_model=AgreementListOut)
def list_agreements(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AgreementListOut:
    membership = get_membership(dynamic_id, user, db)
    agreements = (
        db.query(Agreement)
        .filter(Agreement.dynamic_id == dynamic_id)
        .order_by(Agreement.position, Agreement.created_at)
        .all()
    )
    return _list_out(agreements, membership, db)


@router.post(
    "/{dynamic_id}/agreements",
    response_model=AgreementOut,
    status_code=status.HTTP_201_CREATED,
)
def create_agreement(
    dynamic_id: str,
    payload: AgreementCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AgreementOut:
    membership = get_membership(dynamic_id, user, db)
    content = payload.content.strip()
    agreement = Agreement(
        dynamic_id=dynamic_id,
        title=payload.title.strip(),
        created_by_membership_id=membership.id,
        position=_next_position(db, dynamic_id),
    )

    if membership.role == PartnerRole.dominant and payload.approve_now:
        agreement.title = payload.title.strip()
        _apply_dom_approval(agreement, membership, content)
    else:
        _set_pending(agreement, membership, content)

    db.add(agreement)
    db.commit()
    db.refresh(agreement)
    return _agreement_out(agreement, db)


@router.put("/{dynamic_id}/agreements/{agreement_id}", response_model=AgreementOut)
def update_agreement(
    dynamic_id: str,
    agreement_id: str,
    payload: AgreementUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AgreementOut:
    membership = get_membership(dynamic_id, user, db)
    agreement = (
        db.query(Agreement)
        .filter(Agreement.id == agreement_id, Agreement.dynamic_id == dynamic_id)
        .first()
    )
    if agreement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agreement not found")

    content = payload.content.strip()
    if payload.title is not None:
        agreement.title = payload.title.strip()

    if membership.role == PartnerRole.dominant and payload.approve_now:
        _apply_dom_approval(agreement, membership, content)
    else:
        _set_pending(agreement, membership, content)

    db.commit()
    db.refresh(agreement)
    return _agreement_out(agreement, db)


@router.post("/{dynamic_id}/agreements/{agreement_id}/approve", response_model=AgreementOut)
def approve_agreement(
    dynamic_id: str,
    agreement_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AgreementOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can approve agreements.",
        )
    agreement = (
        db.query(Agreement)
        .filter(Agreement.id == agreement_id, Agreement.dynamic_id == dynamic_id)
        .first()
    )
    if agreement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agreement not found")
    if not agreement.pending_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending changes to approve.",
        )
    _apply_dom_approval(agreement, membership, agreement.pending_content.strip())
    db.commit()
    db.refresh(agreement)
    return _agreement_out(agreement, db)


@router.post("/{dynamic_id}/agreements/{agreement_id}/reject", response_model=AgreementOut)
def reject_agreement(
    dynamic_id: str,
    agreement_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AgreementOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can reject pending changes.",
        )
    agreement = (
        db.query(Agreement)
        .filter(Agreement.id == agreement_id, Agreement.dynamic_id == dynamic_id)
        .first()
    )
    if agreement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agreement not found")

    agreement.pending_content = ""
    agreement.pending_by_membership_id = None
    agreement.pending_at = None
    agreement.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(agreement)
    return _agreement_out(agreement, db)


@router.delete("/{dynamic_id}/agreements/{agreement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agreement(
    dynamic_id: str,
    agreement_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    membership = get_membership(dynamic_id, user, db)
    agreement = (
        db.query(Agreement)
        .filter(Agreement.id == agreement_id, Agreement.dynamic_id == dynamic_id)
        .first()
    )
    if agreement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agreement not found")

    if agreement.approved_content.strip() and membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant can remove approved agreements.",
        )

    db.delete(agreement)
    db.commit()


def _partner_profile_ready(membership: Membership) -> bool:
    return bool(membership.spti_completed_at) or membership.interview_completed


@router.post("/{dynamic_id}/agreements/suggest", response_model=SuggestedAgreementsOut)
def suggest_agreements(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SuggestedAgreementsOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    memberships = get_memberships(db, dynamic_id)
    if len(memberships) < 2:
        return SuggestedAgreementsOut(
            items=[],
            ready=False,
            reason="Both partners must join the dynamic before generating suggestions.",
        )
    if not all(_partner_profile_ready(m) for m in memberships):
        return SuggestedAgreementsOut(
            items=[],
            ready=False,
            reason="Both partners need SPTI results or a completed dynamic interview first.",
        )
    if not is_llm_configured(user, dynamic):
        return SuggestedAgreementsOut(
            items=[],
            ready=False,
            reason="Configure an AI API key for this dynamic first.",
        )

    context = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=bool(user.assistant_include_tracking),
    )
    prompt = """Based on both partners' profiles, suggest 4–6 practical ground-rule agreements for this consensual BDSM dynamic.

Each agreement should be specific to their stated preferences — not generic BDSM boilerplate.

Format exactly like this for each item (no numbering):
TITLE: <short title>
CONTENT: <2-4 sentences>
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        dynamic=dynamic,
        tool_id="agreements",
        db=db,
    )

    items: list[SuggestedAgreementOut] = []
    current_title = None
    current_content: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:"):
            if current_title and current_content:
                items.append(
                    SuggestedAgreementOut(
                        title=current_title,
                        content=" ".join(current_content).strip(),
                    )
                )
            current_title = stripped.split(":", 1)[1].strip()
            current_content = []
        elif stripped.upper().startswith("CONTENT:"):
            current_content.append(stripped.split(":", 1)[1].strip())
        elif current_title and stripped:
            current_content.append(stripped)
    if current_title and current_content:
        items.append(
            SuggestedAgreementOut(
                title=current_title,
                content=" ".join(current_content).strip(),
            )
        )

    if not items:
        return SuggestedAgreementsOut(
            items=[],
            ready=True,
            reason="Could not parse suggestions — try again.",
        )
    return SuggestedAgreementsOut(items=items[:6], ready=True)
