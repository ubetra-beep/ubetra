from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, Membership, User
from ..schemas import (
    CoreKnowledgeFieldOption,
    CoreKnowledgeOut,
    CoreKnowledgePartnerStatus,
    CoreKnowledgeUpdate,
    SptiOut,
    SptiUpdate,
)
from ..services.context import CORE_KNOWLEDGE_FIELDS, core_knowledge_to_out, get_or_create_core_knowledge
from ..services.core_knowledge_from_interview import populate_core_knowledge_from_interview

router = APIRouter(prefix="/dynamics", tags=["core-knowledge"])


def _core_knowledge_out(record, membership: Membership) -> CoreKnowledgeOut:
    out = core_knowledge_to_out(record, is_yours=True)
    return CoreKnowledgeOut(
        **out.model_dump(),
        interview_completed=membership.interview_completed,
    )


@router.get("/{dynamic_id}/core-knowledge/me", response_model=CoreKnowledgeOut)
def get_my_core_knowledge(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoreKnowledgeOut:
    membership = get_membership(dynamic_id, user, db)
    record = get_or_create_core_knowledge(db, membership)
    db.commit()
    return _core_knowledge_out(record, membership)


@router.put("/{dynamic_id}/core-knowledge/me", response_model=CoreKnowledgeOut)
def save_my_core_knowledge(
    dynamic_id: str,
    payload: CoreKnowledgeUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoreKnowledgeOut:
    membership = get_membership(dynamic_id, user, db)
    record = get_or_create_core_knowledge(db, membership)
    record.relationship_context = payload.relationship_context.strip()
    record.distance = payload.distance.strip()
    record.space = payload.space.strip()
    record.budget = payload.budget.strip()
    record.about_you = payload.about_you.strip()
    record.desires = payload.desires.strip()
    record.submitted = False
    record.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return _core_knowledge_out(record, membership)


@router.post("/{dynamic_id}/core-knowledge/me/from-interview", response_model=CoreKnowledgeOut)
def populate_core_knowledge_from_interview_endpoint(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    overwrite: bool = False,
) -> CoreKnowledgeOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    record, _used_llm = populate_core_knowledge_from_interview(
        db,
        user=user,
        dynamic=dynamic,
        membership=membership,
        overwrite=overwrite,
    )
    record.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return _core_knowledge_out(record, membership)


@router.post("/{dynamic_id}/core-knowledge/me/submit", response_model=CoreKnowledgeOut)
def submit_my_core_knowledge(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoreKnowledgeOut:
    membership = get_membership(dynamic_id, user, db)
    record = get_or_create_core_knowledge(db, membership)
    if not any(
        [
            record.relationship_context.strip(),
            record.about_you.strip(),
            record.desires.strip(),
        ]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fill in at least relationship, about you, or desires before submitting.",
        )
    record.submitted = True
    record.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return _core_knowledge_out(record, membership)


@router.get("/{dynamic_id}/spti/me", response_model=SptiOut)
def get_my_spti(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SptiOut:
    membership = get_membership(dynamic_id, user, db)
    data = membership.spti_data or ""
    skipped = data == "__skipped__"
    return SptiOut(
        completed=bool(membership.spti_completed_at),
        skipped=skipped,
        results="" if skipped else data,
        completed_at=membership.spti_completed_at,
    )


@router.put("/{dynamic_id}/spti/me", response_model=SptiOut)
def save_my_spti(
    dynamic_id: str,
    payload: SptiUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SptiOut:
    membership = get_membership(dynamic_id, user, db)
    if payload.skipped:
        membership.spti_data = "__skipped__"
        membership.spti_completed_at = None
    else:
        data = payload.results.strip()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Paste SPTI results or mark as skipped",
            )
        membership.spti_data = data
        membership.spti_completed_at = datetime.utcnow()
    db.commit()
    return get_my_spti(dynamic_id, user, db)


@router.get(
    "/{dynamic_id}/core-knowledge/partner-status",
    response_model=CoreKnowledgePartnerStatus,
)
def get_partner_core_knowledge_status(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoreKnowledgePartnerStatus:
    membership = get_membership(dynamic_id, user, db)
    partner = (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id, Membership.id != membership.id)
        .first()
    )
    if partner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No partner in this dynamic yet.",
        )
    knowledge = partner.core_knowledge
    return CoreKnowledgePartnerStatus(
        display_name=partner.display_name,
        submitted=bool(knowledge and knowledge.submitted),
        updated_at=knowledge.updated_at if knowledge else None,
    )


@router.get(
    "/{dynamic_id}/core-knowledge/me/act-focus-options",
    response_model=list[CoreKnowledgeFieldOption],
)
def get_act_focus_options(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CoreKnowledgeFieldOption]:
    membership = get_membership(dynamic_id, user, db)
    record = get_or_create_core_knowledge(db, membership)
    db.commit()
    options = []
    for key, label in CORE_KNOWLEDGE_FIELDS.items():
        value = getattr(record, key, "").strip()
        if record.submitted and value:
            options.append(
                CoreKnowledgeFieldOption(key=key, label=label, has_content=True)
            )
    return options
