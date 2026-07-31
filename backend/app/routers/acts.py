from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import ActOfSubmission, ActStatus, Dynamic, Membership, PartnerRole, Task, TaskApprovalStatus, TaskList, TaskRecurrence, TaskSource, TaskVisibility, User
from ..schemas import ActCategoryOut, ActOfSubmissionOut, ActRequestIn, ActRespondRequest, ActToTaskCreate, ActVerifyRequest, TaskListOut
from ..services.act_catalog import find_act_category, generate_act_catalog, maybe_generate_act_catalog, parse_act_catalog
from ..services.tags import tags_to_string
from ..services.tasks_service import task_list_out
from ..services.chat_events import post_system_event, task_snippet
from ..services.context import CORE_KNOWLEDGE_FIELDS, build_dynamic_context, get_or_create_core_knowledge
from ..services.llm import generate_act_of_submission

router = APIRouter(tags=["acts"])


def _act_to_out(act: ActOfSubmission) -> ActOfSubmissionOut:
    return ActOfSubmissionOut(
        id=act.id,
        status=act.status,
        hint_text=act.hint_text,
        act_type_id=act.act_type_id or "",
        act_type_title=act.act_type_title or "",
        sub_response_text=act.sub_response_text,
        sub_rating=act.sub_rating,
        dom_verified=act.dom_verified,
        dom_notes=act.dom_notes,
        requested_by_display_name=act.requested_by.display_name,
        created_at=act.created_at,
        completed_at=act.completed_at,
        verified_at=act.verified_at,
    )


@router.get("/dynamics/{dynamic_id}/acts/catalog", response_model=list[ActCategoryOut])
def get_act_catalog(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ActCategoryOut]:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    maybe_generate_act_catalog(db, user=user, dynamic=dynamic)
    db.refresh(dynamic)
    return [ActCategoryOut(**cat) for cat in parse_act_catalog(dynamic.act_categories)]


@router.post("/dynamics/{dynamic_id}/acts/catalog/generate", response_model=list[ActCategoryOut])
def regenerate_act_catalog(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ActCategoryOut]:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    try:
        categories = generate_act_catalog(db, user=user, dynamic=dynamic)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [ActCategoryOut(**cat) for cat in categories]


@router.get("/dynamics/{dynamic_id}/acts", response_model=list[ActOfSubmissionOut])
def list_acts(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ActOfSubmissionOut]:
    get_membership(dynamic_id, user, db)
    acts = (
        db.query(ActOfSubmission)
        .options(joinedload(ActOfSubmission.requested_by))
        .filter(ActOfSubmission.dynamic_id == dynamic_id)
        .order_by(ActOfSubmission.created_at.desc())
        .limit(30)
        .all()
    )
    return [_act_to_out(act) for act in acts]


@router.post(
    "/dynamics/{dynamic_id}/acts",
    response_model=ActOfSubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
def request_act(
    dynamic_id: str,
    payload: ActRequestIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ActOfSubmissionOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.submissive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submissive partner can request an act of submission",
        )
    if not membership.interview_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your dynamic interview first so acts match what you want.",
        )

    record = get_or_create_core_knowledge(db, membership)
    if not record.submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Submit your core knowledge before requesting acts.",
        )

    valid_keys = set(CORE_KNOWLEDGE_FIELDS.keys())
    focus = [key for key in payload.knowledge_focus if key in valid_keys]
    if not focus:
        focus = [
            key
            for key in valid_keys
            if getattr(record, key, "").strip()
        ]
    if not focus:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fill in core knowledge fields before requesting acts.",
        )

    active = (
        db.query(ActOfSubmission)
        .filter(
            ActOfSubmission.dynamic_id == dynamic_id,
            ActOfSubmission.status == ActStatus.active,
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active act already exists. Complete it before requesting another.",
        )

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    maybe_generate_act_catalog(db, user=user, dynamic=dynamic)
    db.refresh(dynamic)

    act_type = find_act_category(dynamic, payload.act_type_id.strip()) if payload.act_type_id.strip() else None
    if parse_act_catalog(dynamic.act_categories) and act_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose an act type before requesting.",
        )

    context = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        knowledge_focus_fields=focus,
        include_tracking=bool(user.assistant_include_tracking),
    )
    hint = generate_act_of_submission(
        user=user,
        dynamic_context=context,
        submissive_name=membership.display_name,
        dynamic=dynamic,
        act_type=act_type,
    )

    act = ActOfSubmission(
        dynamic_id=dynamic_id,
        requested_by_membership_id=membership.id,
        hint_text=hint,
        knowledge_focus=",".join(focus),
        act_type_id=act_type["id"] if act_type else "",
        act_type_title=act_type["title"] if act_type else "",
        status=ActStatus.active,
    )
    db.add(act)
    post_system_event(db, dynamic_id, membership, "requested an act of submission")
    db.commit()
    act = (
        db.query(ActOfSubmission)
        .options(joinedload(ActOfSubmission.requested_by))
        .filter(ActOfSubmission.id == act.id)
        .one()
    )
    return _act_to_out(act)


@router.get("/acts/{act_id}", response_model=ActOfSubmissionOut)
def get_act(
    act_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ActOfSubmissionOut:
    act = (
        db.query(ActOfSubmission)
        .options(joinedload(ActOfSubmission.requested_by))
        .filter(ActOfSubmission.id == act_id)
        .first()
    )
    if act is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Act not found")
    get_membership(act.dynamic_id, user, db)
    return _act_to_out(act)


@router.patch("/acts/{act_id}/respond", response_model=ActOfSubmissionOut)
def respond_to_act(
    act_id: str,
    payload: ActRespondRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ActOfSubmissionOut:
    act = (
        db.query(ActOfSubmission)
        .options(joinedload(ActOfSubmission.requested_by))
        .filter(ActOfSubmission.id == act_id)
        .first()
    )
    if act is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Act not found")

    membership = get_membership(act.dynamic_id, user, db)
    if membership.role != PartnerRole.submissive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submissive partner can complete an act",
        )
    if act.status != ActStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Act is not active")

    act.sub_response_text = payload.response_text.strip()
    act.sub_rating = payload.rating
    act.status = ActStatus.completed
    act.completed_at = datetime.utcnow()
    post_system_event(db, act.dynamic_id, membership, "completed an act of submission")
    db.commit()
    db.refresh(act)
    return _act_to_out(act)


@router.post("/acts/{act_id}/convert-to-task", response_model=TaskListOut)
def convert_act_to_task(
    act_id: str,
    payload: ActToTaskCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    act = (
        db.query(ActOfSubmission)
        .filter(ActOfSubmission.id == act_id)
        .first()
    )
    if act is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Act not found")

    membership = get_membership(act.dynamic_id, user, db)
    if act.status not in (ActStatus.completed, ActStatus.verified):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only completed or verified acts can become tasks",
        )

    existing = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(Task.act_id == act_id, TaskList.dynamic_id == act.dynamic_id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This act was already converted to a task",
        )

    task_list = (
        db.query(TaskList)
        .filter(TaskList.dynamic_id == act.dynamic_id, TaskList.title == "From acts")
        .first()
    )
    if task_list is None:
        task_list = TaskList(
            dynamic_id=act.dynamic_id,
            title="From acts",
            created_by_membership_id=membership.id,
        )
        db.add(task_list)
        db.flush()

    next_due = payload.due_at
    if payload.recurrence != TaskRecurrence.none and next_due is None:
        next_due = datetime.utcnow()

    approval = TaskApprovalStatus.approved
    source = TaskSource.act
    if membership.role == PartnerRole.submissive:
        approval = TaskApprovalStatus.pending
        source = TaskSource.sub

    position = db.query(Task).filter(Task.task_list_id == task_list.id).count()
    db.add(
        Task(
            task_list_id=task_list.id,
            position=position,
            content=act.hint_text,
            visibility=TaskVisibility.visible,
            tags=tags_to_string(payload.tags),
            approval_status=approval,
            source=source,
            created_by_membership_id=membership.id,
            recurrence=payload.recurrence,
            due_at=payload.due_at,
            next_due_at=next_due if payload.recurrence != TaskRecurrence.none else None,
            act_id=act.id,
        )
    )
    post_system_event(
        db,
        act.dynamic_id,
        membership,
        f"converted act to repeating task: {task_snippet(act.hint_text)}",
    )
    db.commit()

    task_list = (
        db.query(TaskList)
        .options(joinedload(TaskList.tasks))
        .filter(TaskList.id == task_list.id)
        .one()
    )
    return task_list_out(task_list, membership)


@router.patch("/acts/{act_id}/verify", response_model=ActOfSubmissionOut)
def verify_act(
    act_id: str,
    payload: ActVerifyRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ActOfSubmissionOut:
    act = (
        db.query(ActOfSubmission)
        .options(joinedload(ActOfSubmission.requested_by))
        .filter(ActOfSubmission.id == act_id)
        .first()
    )
    if act is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Act not found")

    membership = get_membership(act.dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can verify an act",
        )
    if act.status != ActStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Act must be completed before verification",
        )

    act.dom_verified = payload.approved
    act.dom_notes = payload.notes.strip() or None
    act.status = ActStatus.verified
    act.verified_at = datetime.utcnow()
    verdict = "approved" if payload.approved else "sent back for more work on"
    post_system_event(db, act.dynamic_id, membership, f"{verdict} an act of submission")
    db.commit()
    db.refresh(act)
    return _act_to_out(act)
