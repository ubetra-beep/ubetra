from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import (
    Dynamic,
    Interest,
    InterestCategory,
    InterestResponse,
    InterestValue,
    Membership,
    PartnerRole,
    User,
)
from ..schemas import (
    InterestCategoryOut,
    InterestOut,
    InterestResponsesUpdate,
    InterestsBundle,
    KinkExamplesOut,
    ShareKinksUpdate,
    SubmissionSummary,
)
from ..services.context import POSITIVE, build_dynamic_context, compute_overlap, response_map
from ..services.llm import generate_text, is_llm_configured

router = APIRouter(prefix="/dynamics", tags=["interests"])

POSITIVE_VALUES = POSITIVE


def _label_for_role(interest: Interest, role: PartnerRole) -> str:
    if role == PartnerRole.submissive and interest.submissive_display_override:
        return interest.submissive_display_override
    return interest.display_copy


def _interest_out(interest: Interest) -> InterestOut:
    return InterestOut(
        id=interest.id,
        display_copy=interest.display_copy,
        submissive_display_override=interest.submissive_display_override,
        description=interest.description,
        display_order=interest.display_order,
    )


def _partner_membership(memberships: list[Membership], yours: Membership) -> Membership | None:
    for m in memberships:
        if m.id != yours.id:
            return m
    return None


def _dominant_membership(memberships: list[Membership]) -> Membership | None:
    return next((m for m in memberships if m.role == PartnerRole.dominant), None)


def _dynamic_sharing_enabled(memberships: list[Membership]) -> bool:
    dominant = _dominant_membership(memberships)
    return bool(dominant and dominant.share_kinks)


def _response_map(db: Session, membership_id: str) -> dict[str, InterestValue]:
    rows = (
        db.query(InterestResponse)
        .filter(InterestResponse.membership_id == membership_id)
        .all()
    )
    return {row.interest_id: row.value for row in rows}


def _submission_summary(
    membership: Membership, responses: dict[str, InterestValue]
) -> SubmissionSummary:
    positive_count = sum(1 for v in responses.values() if v in POSITIVE_VALUES)
    return SubmissionSummary(
        submitted=membership.survey_submitted,
        submitted_at=membership.survey_submitted_at,
        response_count=positive_count if membership.survey_submitted else len(responses),
    )


def _compute_overlap(
    your_responses: dict[str, InterestValue],
    partner_responses: dict[str, InterestValue],
) -> list[str]:
    return compute_overlap(your_responses, partner_responses)


@router.get("/{dynamic_id}/interests", response_model=InterestsBundle)
def get_interests(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterestsBundle:
    membership = get_membership(dynamic_id, user, db)
    dynamic_memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    partner = _partner_membership(dynamic_memberships, membership)

    categories = (
        db.query(InterestCategory)
        .options(joinedload(InterestCategory.interests))
        .order_by(InterestCategory.display_order)
        .all()
    )
    category_out = []
    interest_by_id: dict[str, Interest] = {}
    for cat in categories:
        interests = sorted(cat.interests, key=lambda i: i.display_order)
        for interest in interests:
            interest_by_id[interest.id] = interest
        category_out.append(
            InterestCategoryOut(
                id=cat.id,
                name=cat.name,
                description=cat.description,
                display_order=cat.display_order,
                interests=[_interest_out(i) for i in interests],
            )
        )

    your_responses = _response_map(db, membership.id)
    partner_raw = _response_map(db, partner.id) if partner else {}
    sharing_enabled = _dynamic_sharing_enabled(dynamic_memberships)
    you_share = bool(membership.role == PartnerRole.dominant and membership.share_kinks)
    partner_shares = sharing_enabled
    partner_responses = partner_raw if sharing_enabled else {}
    overlap_ids = (
        _compute_overlap(your_responses, partner_raw)
        if (
            partner
            and partner.survey_submitted
            and membership.survey_submitted
            and sharing_enabled
        )
        else []
    )

    overlap_details = []
    for interest_id in overlap_ids:
        interest = interest_by_id.get(interest_id)
        if interest:
            labeled = InterestOut(
                id=interest.id,
                display_copy=_label_for_role(interest, membership.role),
                submissive_display_override=interest.submissive_display_override,
                description=interest.description,
                display_order=interest.display_order,
            )
            overlap_details.append(labeled)

    partner_summary = (
        _submission_summary(partner, partner_raw)
        if partner
        else SubmissionSummary(submitted=False, submitted_at=None, response_count=0)
    )
    if partner and partner.survey_submitted and not sharing_enabled:
        # Hide counts so private answers are not leaked.
        partner_summary = SubmissionSummary(
            submitted=True,
            submitted_at=partner.survey_submitted_at,
            response_count=0,
        )

    return InterestsBundle(
        categories=category_out,
        your_responses=your_responses,
        partner_responses=partner_responses,
        partner_submission=partner_summary,
        your_submission=_submission_summary(membership, your_responses),
        your_share_kinks=you_share,
        partner_share_kinks=partner_shares,
        sharing_enabled=sharing_enabled,
        overlap=overlap_ids,
        overlap_details=overlap_details,
    )


@router.put("/{dynamic_id}/interests", response_model=InterestsBundle)
def save_interests(
    dynamic_id: str,
    payload: InterestResponsesUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterestsBundle:
    membership = get_membership(dynamic_id, user, db)
    valid_ids = {row.id for row in db.query(Interest.id).all()}

    for interest_id, value in payload.responses.items():
        if interest_id not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown interest: {interest_id}",
            )
        existing = (
            db.query(InterestResponse)
            .filter(
                InterestResponse.membership_id == membership.id,
                InterestResponse.interest_id == interest_id,
            )
            .first()
        )
        if existing:
            existing.value = value
            existing.updated_at = datetime.utcnow()
        else:
            db.add(
                InterestResponse(
                    membership_id=membership.id,
                    interest_id=interest_id,
                    value=value,
                )
            )

    membership.survey_submitted = False
    membership.survey_submitted_at = None
    db.commit()
    return get_interests(dynamic_id, user, db)


@router.put("/{dynamic_id}/interests/share", response_model=InterestsBundle)
def update_share_kinks(
    dynamic_id: str,
    payload: ShareKinksUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterestsBundle:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        if payload.share_kinks:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the dominant can enable kink sharing",
            )
        membership.share_kinks = False
    else:
        membership.share_kinks = bool(payload.share_kinks)
    db.commit()
    return get_interests(dynamic_id, user, db)


@router.post("/{dynamic_id}/interests/submit", response_model=InterestsBundle)
def submit_interests(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterestsBundle:
    membership = get_membership(dynamic_id, user, db)
    responses = _response_map(db, membership.id)
    if not responses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Answer at least one interest before submitting",
        )

    membership.survey_submitted = True
    membership.survey_submitted_at = datetime.utcnow()
    membership.survey_skipped = False
    db.commit()
    return get_interests(dynamic_id, user, db)


@router.get("/{dynamic_id}/interests/{interest_id}/examples", response_model=KinkExamplesOut)
def kink_examples(
    dynamic_id: str,
    interest_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> KinkExamplesOut:
    membership = get_membership(dynamic_id, user, db)
    if not membership.spti_completed_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete the SPTI test first (or paste results) to get tailored examples.",
        )
    interest = db.get(Interest, interest_id)
    if interest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interest not found")

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure an AI API key before requesting examples.",
        )

    label = _label_for_role(interest, membership.role)
    context = build_dynamic_context(db, dynamic, requesting_membership_id=membership.id)
    prompt = f"""The user is rating kink interests in a survey. For the interest "{label}" ({interest.description or "no description"}), give 2–3 brief, concrete examples of how this might look in a consensual scene or dynamic.

Tailor examples to their SPTI profile and stated preferences in context. Keep each example to 1–2 sentences. Use a simple bullet list with "- " prefix."""

    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        dynamic=dynamic,
        tool_id="interests",
        db=db,
    )
    examples = [
        line.lstrip("-• ").strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().lower().startswith("example")
    ]
    examples = [e for e in examples if e][:3]
    if not examples:
        examples = [raw.strip()[:400]] if raw.strip() else []
    return KinkExamplesOut(examples=examples)
