from datetime import datetime

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import (
    ActOfSubmission,
    ActStatus,
    Dynamic,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    TaskSource,
    TaskVisibility,
    User,
)
from ..schemas import (
    AssistantStatusOut,
    AssistantTaskCreate,
    PlaytimeFeedbackOut,
    PlaytimeFeedbackRequest,
    PlaytimeSceneOut,
    PlaytimeSceneRequest,
    PlaytimeSubjectOut,
    PlaytimeSubjectsOut,
    PlaytimeSubjectsRequest,
    RecommendationOut,
    SpinWheelSuggestOut,
    SpinWheelSuggestRequest,
    SpinWheelOptionOut,
    SpinPostOrgasmTasksOut,
    SpinNextWaitRequest,
    SpinNextWaitOut,
    SpinMidgameCheckOut,
    SpinGameOut,
    SpinPostOrgasmSetup,
    SpinPostOrgasmSpinOut,
    SpinFulfillRequest,
    SpinFulfillOut,
    TaskListOut,
)
from ..services.chat_events import post_system_event, task_snippet
from ..services.context import build_dynamic_context, compute_overlap, get_memberships, response_map
from ..services.llm import generate_recommendation, is_llm_configured, resolve_llm_config
from ..services.playtime import EFFORT_LABELS, LEAN_LABELS, generate_playtime_scene, generate_playtime_subjects
from ..services.spin_session import (
    announce_shared_outcome,
    configure_post_orgasm,
    end_session,
    ensure_session,
    fulfill_spin_outcome,
    get_active_session,
    session_view,
    spin_post_orgasm,
    update_secret,
)
from ..services.spin_wheel import (
    build_spin_presets,
    days_since_last_orgasm,
    full_orgasms_since,
    generate_post_orgasm_tasks,
    generate_spin_extra_ideas,
    next_wait_day_choices,
    partner_names,
)
from ..services.tags import tags_to_string
from ..services.tasks_service import task_list_out

router = APIRouter(prefix="/dynamics", tags=["assistant"])


def _require_playtime_ready(membership, user: User, dynamic: Dynamic | None) -> None:
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if not membership.interview_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your dynamic interview first so scenes match what you want.",
        )
    if not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add your API key in Settings before using Playtime.",
        )


def _playtime_context(db: Session, dynamic: Dynamic, membership, user: User) -> str:
    return build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=bool(user.assistant_include_tracking),
    )


def _validate_effort_lean(effort: str, lean: str) -> None:
    if effort not in EFFORT_LABELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid effort level")
    if lean not in LEAN_LABELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid desire lean")


@router.get("/{dynamic_id}/assistant/status", response_model=AssistantStatusOut)
def assistant_status(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AssistantStatusOut:
    membership = get_membership(dynamic_id, user, db)
    memberships = get_memberships(db, dynamic_id)
    you = membership
    partner = next((m for m in memberships if m.id != membership.id), None)

    overlap_count = 0
    if partner and you.survey_submitted and partner.survey_submitted:
        overlap_count = len(
            compute_overlap(response_map(db, you.id), response_map(db, partner.id))
        )

    active_act = (
        db.query(ActOfSubmission)
        .filter(
            ActOfSubmission.dynamic_id == dynamic_id,
            ActOfSubmission.status == ActStatus.active,
        )
        .order_by(ActOfSubmission.created_at.desc())
        .first()
    )

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    llm = resolve_llm_config(user, dynamic)
    return AssistantStatusOut(
        llm_configured=is_llm_configured(user, dynamic),
        llm_provider=llm.provider,
        llm_model=llm.model,
        using_server_default=llm.using_server_default,
        your_core_knowledge_submitted=bool(you.core_knowledge and you.core_knowledge.submitted),
        partner_core_knowledge_submitted=bool(
            partner and partner.core_knowledge and partner.core_knowledge.submitted
        ),
        your_survey_submitted=you.survey_submitted,
        partner_survey_submitted=partner.survey_submitted if partner else False,
        your_interview_completed=you.interview_completed,
        partner_interview_completed=partner.interview_completed if partner else False,
        shared_interest_count=overlap_count,
        active_act_id=active_act.id if active_act else None,
    )


@router.post("/{dynamic_id}/playtime/subjects", response_model=PlaytimeSubjectsOut)
def playtime_subjects(
    dynamic_id: str,
    payload: PlaytimeSubjectsRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlaytimeSubjectsOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    _validate_effort_lean(payload.effort, payload.lean)

    subjects = generate_playtime_subjects(
        user=user,
        dynamic_context=_playtime_context(db, dynamic, membership, user),
        effort=payload.effort,
        lean=payload.lean,
        dynamic=dynamic,
        exclude_subjects=payload.exclude_subjects,
        note=payload.note,
    )
    return PlaytimeSubjectsOut(
        effort=payload.effort,
        lean=payload.lean,
        subjects=[PlaytimeSubjectOut(**s) for s in subjects],
    )


@router.post("/{dynamic_id}/playtime/scene", response_model=PlaytimeSceneOut)
def playtime_scene(
    dynamic_id: str,
    payload: PlaytimeSceneRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlaytimeSceneOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    _validate_effort_lean(payload.effort, payload.lean)
    if not payload.subject.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick a subject first")

    scene = generate_playtime_scene(
        user=user,
        dynamic_context=_playtime_context(db, dynamic, membership, user),
        effort=payload.effort,
        lean=payload.lean,
        subject=payload.subject.strip(),
        dynamic=dynamic,
        avoid_summary=payload.avoid_summary,
        note=payload.note,
    )
    return PlaytimeSceneOut(
        effort=payload.effort,
        lean=payload.lean,
        subject=scene["subject"],
        title=scene["title"],
        summary=scene["summary"],
        body=scene["body"],
    )


@router.post("/{dynamic_id}/playtime/feedback", response_model=PlaytimeFeedbackOut)
def playtime_feedback(
    dynamic_id: str,
    payload: PlaytimeFeedbackRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlaytimeFeedbackOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    _validate_effort_lean(payload.effort, payload.lean)

    if payload.rating is not None and (payload.rating < 1 or payload.rating > 5):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rating must be 1–5")

    if payload.reject and payload.regenerate:
        avoid = payload.scene_summary or payload.scene_title
        scene = generate_playtime_scene(
            user=user,
            dynamic_context=_playtime_context(db, dynamic, membership, user),
            effort=payload.effort,
            lean=payload.lean,
            subject=payload.subject.strip(),
            dynamic=dynamic,
            avoid_summary=avoid,
            note=payload.note,
        )
        return PlaytimeFeedbackOut(
            recorded=True,
            message="New scene generated",
            scene=PlaytimeSceneOut(
                effort=payload.effort,
                lean=payload.lean,
                subject=scene["subject"],
                title=scene["title"],
                summary=scene["summary"],
                body=scene["body"],
            ),
        )

    if payload.rating is not None:
        stars = "★" * payload.rating + "☆" * (5 - payload.rating)
        post_system_event(
            db,
            dynamic_id,
            membership,
            f"rated a Playtime scene {stars}: {payload.scene_title or payload.subject}",
        )
        db.commit()
        return PlaytimeFeedbackOut(
            recorded=True,
            message=f"Saved rating ({payload.rating}/5). Enjoy playtime.",
        )

    if payload.reject:
        return PlaytimeFeedbackOut(recorded=True, message="Noted — try another scene when ready.")

    return PlaytimeFeedbackOut(recorded=True, message="Thanks for the feedback.")


@router.post("/{dynamic_id}/playtime/spin/suggestions", response_model=SpinWheelSuggestOut)
def playtime_spin_suggestions(
    dynamic_id: str,
    payload: SpinWheelSuggestRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinWheelSuggestOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)

    memberships = get_memberships(db, dynamic_id)
    dominant_name, submissive_name = partner_names(memberships)
    options = build_spin_presets(dominant_name=dominant_name)
    try:
        extras = generate_spin_extra_ideas(
            user=user,
            dynamic_context=_playtime_context(db, dynamic, membership, user),
            dynamic=dynamic,
            faces=payload.faces,
            dominant_name=dominant_name,
            submissive_name=submissive_name,
        )
        options.extend(extras)
    except HTTPException:
        pass

    return SpinWheelSuggestOut(
        faces=payload.faces,
        dominant_name=dominant_name,
        submissive_name=submissive_name,
        days_since_last_orgasm=days_since_last_orgasm(db, dynamic_id, memberships),
        options=[SpinWheelOptionOut(**item) for item in options],
    )


@router.post("/{dynamic_id}/playtime/spin/post-orgasm-tasks", response_model=SpinPostOrgasmTasksOut)
def playtime_spin_post_orgasm_tasks(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinPostOrgasmTasksOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    memberships = get_memberships(db, dynamic_id)
    dominant_name, submissive_name = partner_names(memberships)
    try:
        tasks = generate_post_orgasm_tasks(
            user=user,
            dynamic_context=_playtime_context(db, dynamic, membership, user),
            dynamic=dynamic,
            dominant_name=dominant_name,
            submissive_name=submissive_name,
        )
    except HTTPException:
        from ..services.spin_wheel import POST_ORGASM_PRESETS

        tasks = [dict(item, source="preset") for item in POST_ORGASM_PRESETS]

    return SpinPostOrgasmTasksOut(
        dominant_name=dominant_name,
        submissive_name=submissive_name,
        days_since_last_orgasm=days_since_last_orgasm(db, dynamic_id, memberships),
        tasks=tasks,
    )


@router.post("/{dynamic_id}/playtime/spin/next-wait", response_model=SpinNextWaitOut)
def playtime_spin_next_wait(
    dynamic_id: str,
    payload: SpinNextWaitRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinNextWaitOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    direction = payload.direction.strip().lower()
    if direction not in {"longer", "shorter"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="direction must be longer or shorter",
        )
    return SpinNextWaitOut(
        verified_wait_days=payload.verified_wait_days,
        direction=direction,
        day_choices=next_wait_day_choices(payload.verified_wait_days, direction),
    )


@router.get("/{dynamic_id}/playtime/spin/midgame", response_model=SpinMidgameCheckOut)
def playtime_spin_midgame(
    dynamic_id: str,
    since: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinMidgameCheckOut:
    """Check orgasm tracker for a full orgasm logged while a spin game was in play."""
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid since timestamp",
        ) from exc

    memberships = get_memberships(db, dynamic_id)
    return SpinMidgameCheckOut(
        in_play_relevant=True,
        days_since_last_orgasm=days_since_last_orgasm(db, dynamic_id, memberships),
        full_orgasms=full_orgasms_since(db, dynamic_id, memberships, since=since_dt),
    )


@router.get("/{dynamic_id}/playtime/spin/game", response_model=SpinGameOut)
def playtime_spin_game(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinGameOut:
    membership = get_membership(dynamic_id, user, db)
    session = get_active_session(db, dynamic_id)
    if session is None:
        return SpinGameOut(status="none", your_role=membership.role.value, public={})
    view = session_view(session, membership)
    return SpinGameOut(**view)


@router.post("/{dynamic_id}/playtime/spin/game/ensure", response_model=SpinGameOut)
def playtime_spin_game_ensure(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinGameOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role.value != "dominant":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder starts this game")
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    session = ensure_session(db, dynamic_id=dynamic_id, membership=membership)
    db.commit()
    db.refresh(session)
    return SpinGameOut(**session_view(session, membership))


@router.put("/{dynamic_id}/playtime/spin/game/secret", response_model=SpinGameOut)
def playtime_spin_game_secret(
    dynamic_id: str,
    payload: dict,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinGameOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role.value != "dominant":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hidden game state is keyholder-only")
    session = ensure_session(db, dynamic_id=dynamic_id, membership=membership)
    update_secret(session, payload if isinstance(payload, dict) else {})
    db.commit()
    db.refresh(session)
    return SpinGameOut(**session_view(session, membership))


@router.post("/{dynamic_id}/playtime/spin/game/clear", response_model=SpinGameOut)
def playtime_spin_game_clear(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinGameOut:
    """Keyholder ends the current spin game so a fresh one can start."""
    membership = get_membership(dynamic_id, user, db)
    if membership.role.value != "dominant":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can clear the game")
    session = get_active_session(db, dynamic_id)
    if session is not None:
        end_session(session)
        db.commit()
    return SpinGameOut(status="none", your_role=membership.role.value, public={}, can_spin_post_orgasm=False)

@router.post("/{dynamic_id}/playtime/spin/post-orgasm/setup", response_model=SpinGameOut)
def playtime_post_orgasm_setup(
    dynamic_id: str,
    payload: SpinPostOrgasmSetup,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinGameOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role.value != "dominant":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder configures post-orgasm tasks")
    dynamic = db.get(Dynamic, dynamic_id)
    _require_playtime_ready(membership, user, dynamic)
    session = ensure_session(db, dynamic_id=dynamic_id, membership=membership)
    post = configure_post_orgasm(
        session,
        task_pool=payload.task_pool,
        task_count=payload.task_count,
        use_wheel=payload.use_wheel,
        spinner=payload.spinner,
        manual_picks=payload.manual_picks,
    )
    if not payload.use_wheel and post.get("results"):
        titles = ", ".join(r.get("title", "") for r in post["results"])
        announce_shared_outcome(
            db,
            dynamic_id=dynamic_id,
            membership=membership,
            text=f"Playtime post-orgasm task(s): {titles}",
        )
    db.commit()
    db.refresh(session)
    return SpinGameOut(**session_view(session, membership))


@router.post("/{dynamic_id}/playtime/spin/post-orgasm/spin", response_model=SpinPostOrgasmSpinOut)
def playtime_post_orgasm_spin(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinPostOrgasmSpinOut:
    membership = get_membership(dynamic_id, user, db)
    session = get_active_session(db, dynamic_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active spin game")
    result = spin_post_orgasm(db, session, membership)
    db.commit()
    return SpinPostOrgasmSpinOut(**result)


@router.post("/{dynamic_id}/playtime/spin/fulfill", response_model=SpinFulfillOut)
def playtime_spin_fulfill(
    dynamic_id: str,
    payload: SpinFulfillRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SpinFulfillOut:
    """Log orgasm/chastity tracking when a spin outcome is fulfilled (Game chat notify)."""
    membership = get_membership(dynamic_id, user, db)
    if membership.role.value != "dominant":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can fulfill spin outcomes")
    result = fulfill_spin_outcome(
        db,
        dynamic_id=dynamic_id,
        membership=membership,
        kind=payload.kind,
        count=payload.count,
        unit=payload.unit,
    )
    db.commit()
    return SpinFulfillOut(**result)


@router.post("/{dynamic_id}/playtime/spin/announce")
def playtime_spin_announce(
    dynamic_id: str,
    payload: dict,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Post a shared (non-hidden) playtime outcome to chat + push."""
    membership = get_membership(dynamic_id, user, db)
    text = str((payload or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text required")
    push_url = str((payload or {}).get("push_url") or "").strip() or None
    announce_shared_outcome(
        db,
        dynamic_id=dynamic_id,
        membership=membership,
        text=text[:500],
        push_url=push_url,
    )
    db.commit()
    return {"ok": True}


@router.post("/{dynamic_id}/assistant/recommendation", response_model=RecommendationOut)
def create_recommendation(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    focus: str = "",
) -> RecommendationOut:
    membership = get_membership(dynamic_id, user, db)
    if not membership.interview_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your dynamic interview first so suggestions match what you want.",
        )

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    context = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=bool(user.assistant_include_tracking),
    )
    raw = generate_recommendation(user=user, dynamic_context=context, focus=focus, dynamic=dynamic)

    category = "Recommendation"
    hint = ""
    response = raw
    for line in raw.splitlines():
        lower = line.lower().strip()
        if lower.startswith("category:"):
            category = line.split(":", 1)[1].strip() or category
        elif lower.startswith("idea:"):
            hint = line.split(":", 1)[1].strip()
        elif lower.startswith("why it fits:") and hint:
            response = f"{hint}\n\n{line.split(':', 1)[1].strip()}"
    if not hint:
        hint = raw.split("\n", 1)[0][:120]

    return RecommendationOut(
        category_name=category,
        hint_text=hint,
        response_text=response,
    )


@router.post(
    "/{dynamic_id}/assistant/tasks",
    response_model=TaskListOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assistant_task(
    dynamic_id: str,
    payload: AssistantTaskCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    membership = get_membership(dynamic_id, user, db)
    if not membership.interview_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your dynamic interview first.",
        )

    task_list = (
        db.query(TaskList)
        .filter(TaskList.dynamic_id == dynamic_id, TaskList.title == "Assistant tasks")
        .first()
    )
    if task_list is None:
        task_list = TaskList(
            dynamic_id=dynamic_id,
            title="Assistant tasks",
            created_by_membership_id=membership.id,
        )
        db.add(task_list)
        db.flush()

    next_due = payload.due_at
    if payload.recurrence != TaskRecurrence.none and next_due is None:
        next_due = datetime.utcnow()

    position = db.query(Task).filter(Task.task_list_id == task_list.id).count()
    db.add(
        Task(
            task_list_id=task_list.id,
            position=position,
            content=payload.content.strip(),
            visibility=TaskVisibility.visible,
            tags=tags_to_string(payload.tags),
            approval_status=TaskApprovalStatus.approved,
            source=TaskSource.assistant,
            created_by_membership_id=membership.id,
            recurrence=payload.recurrence,
            due_at=payload.due_at,
            next_due_at=next_due if payload.recurrence != TaskRecurrence.none else None,
        )
    )
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"assigned task (assistant): {task_snippet(payload.content)}",
    )
    db.commit()

    task_list = (
        db.query(TaskList)
        .options(joinedload(TaskList.tasks))
        .filter(TaskList.id == task_list.id)
        .one()
    )
    return task_list_out(task_list, membership)
