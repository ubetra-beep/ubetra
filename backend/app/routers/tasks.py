from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import (
    Dynamic,
    Membership,
    OrgTrackingEntry,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    TaskSource,
    User,
)
from ..schemas import (
    InboxOut,
    TagPresetsOut,
    TagPresetsUpdate,
    TaskBulkActionIn,
    TaskCalendarItem,
    TaskCalendarOut,
    TaskItemCreate,
    TaskItemUpdate,
    TaskListCreate,
    TaskListOut,
    TaskMakeupAssistOut,
    TaskMakeupRequestIn,
    TaskMakeupReviewIn,
)
from ..services.tags import tags_to_list, tags_to_string
from ..services.tasks_service import (
    ack_inbox,
    build_inbox,
    can_complete_task,
    clear_makeup,
    resolve_due_at,
    schedule_next_occurrence,
    task_list_out,
    task_needs_makeup,
    task_visible,
)
from ..services.chat_events import post_system_event, task_snippet
from ..services.google_tasks import (
    complete_google_task,
    push_task_to_google,
    sync_target_user,
)
from ..services.llm import generate_text, is_llm_configured
from ..services.context import build_dynamic_context


def _maybe_push_task(db: Session, dynamic_id: str, actor: User, task: Task) -> None:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        return
    owner = sync_target_user(db, dynamic_id, actor)
    try:
        push_task_to_google(db, owner=owner, actor=actor, dynamic=dynamic, task=task)
    except Exception:
        # Google sync is best-effort; UBETRA tasks still work offline.
        pass


def _maybe_complete_google(db: Session, dynamic_id: str, actor: User, task: Task) -> None:
    owner = sync_target_user(db, dynamic_id, actor)
    try:
        complete_google_task(owner, task)
    except Exception:
        pass

router = APIRouter(tags=["tasks"])


def _named_list(db: Session, dynamic_id: str, membership: Membership, title: str) -> TaskList:
    task_list = (
        db.query(TaskList)
        .filter(
            TaskList.dynamic_id == dynamic_id,
            TaskList.title == title,
        )
        .first()
    )
    if task_list is None:
        task_list = TaskList(
            dynamic_id=dynamic_id,
            title=title,
            created_by_membership_id=membership.id,
        )
        db.add(task_list)
        db.flush()
    return task_list


def _sub_requests_list(db: Session, dynamic_id: str, membership: Membership) -> TaskList:
    return _named_list(db, dynamic_id, membership, "Sub requests")


def _dom_reminders_list(db: Session, dynamic_id: str, membership: Membership) -> TaskList:
    return _named_list(db, dynamic_id, membership, "My reminders")


def _task_list_query(db: Session, task_list_id: str) -> TaskList | None:
    return (
        db.query(TaskList)
        .options(
            joinedload(TaskList.tasks).joinedload(Task.assigned_to),
            joinedload(TaskList.dynamic).joinedload(Dynamic.memberships),
        )
        .filter(TaskList.id == task_list_id)
        .first()
    )


def _effective_due(task: Task) -> datetime | None:
    return task.next_due_at or task.due_at


def _membership_in_dynamic(db: Session, dynamic_id: str, membership_id: str | None) -> bool:
    if not membership_id:
        return True
    row = (
        db.query(Membership)
        .filter(Membership.id == membership_id, Membership.dynamic_id == dynamic_id)
        .first()
    )
    return row is not None


@router.get("/dynamics/{dynamic_id}/tags", response_model=TagPresetsOut)
def get_tag_presets(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagPresetsOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    presets = tags_to_list(dynamic.tag_presets)
    task_presets = tags_to_list(
        getattr(dynamic, "task_tag_presets", None)
        or "Domestic,Health / Hygiene,Sensual,Sexual"
    )
    org_tags: set[str] = set()
    for row in db.query(OrgTrackingEntry.tags).filter(
        OrgTrackingEntry.dynamic_id == dynamic_id
    ):
        org_tags.update(tags_to_list(row[0] or ""))
    task_tags: set[str] = set()
    for row in (
        db.query(Task.tags)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(TaskList.dynamic_id == dynamic_id)
    ):
        task_tags.update(tags_to_list(row[0] or ""))
    merged = list(dict.fromkeys([*presets, *sorted(org_tags | task_tags)]))
    return TagPresetsOut(presets=merged, task_presets=task_presets)


@router.put("/dynamics/{dynamic_id}/tags", response_model=TagPresetsOut)
def update_tag_presets(
    dynamic_id: str,
    payload: TagPresetsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagPresetsOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can edit tag presets",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if payload.presets is not None:
        dynamic.tag_presets = tags_to_string(payload.presets)
    if payload.task_presets is not None:
        dynamic.task_tag_presets = tags_to_string(payload.task_presets)
    db.commit()
    return get_tag_presets(dynamic_id, user, db)


@router.get("/dynamics/{dynamic_id}/inbox", response_model=InboxOut)
def get_inbox(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InboxOut:
    membership = get_membership(dynamic_id, user, db)
    return InboxOut(**build_inbox(db, dynamic_id, membership))


@router.post("/dynamics/{dynamic_id}/inbox/ack", response_model=InboxOut)
def post_inbox_ack(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InboxOut:
    membership = get_membership(dynamic_id, user, db)
    ack_inbox(membership)
    db.commit()
    db.refresh(membership)
    return InboxOut(**build_inbox(db, dynamic_id, membership))


@router.get("/dynamics/{dynamic_id}/tasks", response_model=list[TaskListOut])
def list_task_lists(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TaskListOut]:
    membership = get_membership(dynamic_id, user, db)
    lists = (
        db.query(TaskList)
        .options(
            joinedload(TaskList.tasks).joinedload(Task.assigned_to),
            joinedload(TaskList.dynamic).joinedload(Dynamic.memberships),
        )
        .filter(TaskList.dynamic_id == dynamic_id)
        .order_by(TaskList.created_at.desc())
        .all()
    )
    return [task_list_out(task_list, membership) for task_list in lists]


@router.get("/dynamics/{dynamic_id}/tasks/calendar", response_model=TaskCalendarOut)
def task_calendar(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
) -> TaskCalendarOut:
    membership = get_membership(dynamic_id, user, db)
    _ = membership
    window_start = start or datetime.utcnow() - timedelta(days=7)
    window_end = end or datetime.utcnow() + timedelta(days=60)

    rows = (
        db.query(Task, TaskList)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(TaskList.dynamic_id == dynamic_id)
        .all()
    )
    items: list[TaskCalendarItem] = []
    for task, task_list in rows:
        if task.approval_status == TaskApprovalStatus.rejected:
            continue
        due = _effective_due(task)
        if due is None:
            continue
        if task.recurrence == TaskRecurrence.none:
            if window_start <= due <= window_end:
                items.append(
                    TaskCalendarItem(
                        task_id=task.id,
                        task_list_id=task_list.id,
                        list_title=task_list.title,
                        content=task.content,
                        tags=tags_to_list(task.tags),
                        due_at=due,
                        recurrence=task.recurrence,
                        approval_status=task.approval_status,
                        source=task.source,
                        completed_at=task.completed_at,
                    )
                )
        else:
            cursor = task.due_at or due
            if cursor is None:
                continue
            while cursor <= window_end:
                if cursor >= window_start:
                    completed = task.completed_at if cursor == _effective_due(task) else None
                    items.append(
                        TaskCalendarItem(
                            task_id=task.id,
                            task_list_id=task_list.id,
                            list_title=task_list.title,
                            content=task.content,
                            tags=tags_to_list(task.tags),
                            due_at=cursor,
                            recurrence=task.recurrence,
                            approval_status=task.approval_status,
                            source=task.source,
                            completed_at=completed,
                        )
                    )
                cursor = cursor + (
                    timedelta(days=1)
                    if task.recurrence == TaskRecurrence.daily
                    else timedelta(days=7)
                    if task.recurrence == TaskRecurrence.weekly
                    else timedelta(days=30)
                )
    items.sort(key=lambda i: i.due_at)
    return TaskCalendarOut(items=items)


@router.post(
    "/dynamics/{dynamic_id}/tasks",
    response_model=TaskListOut,
    status_code=status.HTTP_201_CREATED,
)
def create_task_list(
    dynamic_id: str,
    payload: TaskListCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can create task lists",
        )

    default_assignee = payload.assigned_to_membership_id
    if not _membership_in_dynamic(db, dynamic_id, default_assignee):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignee")

    task_list = TaskList(
        dynamic_id=dynamic_id,
        title=payload.title,
        created_by_membership_id=membership.id,
    )
    db.add(task_list)
    db.flush()

    created_tasks: list[Task] = []
    for index, task_payload in enumerate(payload.tasks):
        assignee = task_payload.assigned_to_membership_id or default_assignee
        if not _membership_in_dynamic(db, dynamic_id, assignee):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignee")
        is_private = bool(task_payload.is_private or payload.is_private)
        due = resolve_due_at(
            due_at=task_payload.due_at,
            due_in_amount=task_payload.due_in_amount or payload.due_in_amount,
            due_in_unit=task_payload.due_in_unit or payload.due_in_unit,
        )
        next_due = due
        if task_payload.recurrence != TaskRecurrence.none and next_due is None:
            next_due = datetime.utcnow()
        task = Task(
            task_list_id=task_list.id,
            position=index,
            content=task_payload.content,
            visibility=task_payload.visibility,
            tags=tags_to_string(task_payload.tags),
            approval_status=TaskApprovalStatus.approved,
            source=TaskSource.dom,
            created_by_membership_id=membership.id,
            recurrence=task_payload.recurrence,
            due_at=due,
            next_due_at=next_due if task_payload.recurrence != TaskRecurrence.none else None,
            assigned_to_membership_id=assignee,
            is_private=is_private,
        )
        db.add(task)
        created_tasks.append(task)

    post_system_event(
        db,
        dynamic_id,
        membership,
        f'created task list "{payload.title}" ({len(payload.tasks)} tasks)',
    )
    db.flush()
    for task in created_tasks:
        _maybe_push_task(db, dynamic_id, user, task)
    db.commit()
    task_list = _task_list_query(db, task_list.id)
    return task_list_out(task_list, membership)


@router.post(
    "/dynamics/{dynamic_id}/tasks/items",
    response_model=TaskListOut,
    status_code=status.HTTP_201_CREATED,
)
def add_task_item(
    dynamic_id: str,
    payload: TaskItemCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    membership = get_membership(dynamic_id, user, db)
    due = resolve_due_at(
        due_at=payload.due_at,
        due_in_amount=payload.due_in_amount,
        due_in_unit=payload.due_in_unit,
    )
    next_due = due
    if payload.recurrence != TaskRecurrence.none and next_due is None:
        next_due = datetime.utcnow()

    if membership.role == PartnerRole.submissive:
        task_list = _sub_requests_list(db, dynamic_id, membership)
        approval = TaskApprovalStatus.pending
        source = TaskSource.sub
        assignee = payload.assigned_to_membership_id or membership.id
        is_private = False
        event_text = f"requested task (pending approval): {task_snippet(payload.content)}"
    elif membership.role == PartnerRole.dominant:
        assignee = payload.assigned_to_membership_id
        if not _membership_in_dynamic(db, dynamic_id, assignee):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignee")
        is_private = bool(payload.is_private)
        if payload.task_list_id:
            task_list = _task_list_query(db, payload.task_list_id)
            if task_list is None or task_list.dynamic_id != dynamic_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")
        elif is_private or (assignee and assignee == membership.id):
            task_list = _dom_reminders_list(db, dynamic_id, membership)
            if assignee is None:
                assignee = membership.id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Choose a task list, or mark the task private for My reminders",
            )
        approval = TaskApprovalStatus.approved
        source = TaskSource.dom
        event_text = f"added task: {task_snippet(payload.content)}"
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    # Reload with tasks for position count if needed
    if not hasattr(task_list, "tasks") or task_list.tasks is None:
        task_list = _task_list_query(db, task_list.id)
    position = len(task_list.tasks or [])
    db.add(
        Task(
            task_list_id=task_list.id,
            position=position,
            content=payload.content,
            visibility=payload.visibility,
            tags=tags_to_string(payload.tags),
            approval_status=approval,
            source=source,
            created_by_membership_id=membership.id,
            recurrence=payload.recurrence,
            due_at=due,
            next_due_at=next_due if payload.recurrence != TaskRecurrence.none else None,
            assigned_to_membership_id=assignee,
            is_private=is_private,
        )
    )
    post_system_event(db, dynamic_id, membership, event_text)
    db.commit()
    task_list = _task_list_query(db, task_list.id)
    return task_list_out(task_list, membership)


@router.get("/tasks/{task_list_id}", response_model=TaskListOut)
def get_task_list(
    task_list_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")

    membership = get_membership(task_list.dynamic_id, user, db)
    return task_list_out(task_list, membership)


@router.patch("/tasks/{task_list_id}/items/{task_id}/complete", response_model=TaskListOut)
def complete_task(
    task_list_id: str,
    task_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")

    membership = get_membership(task_list.dynamic_id, user, db)

    tasks = sorted(task_list.tasks, key=lambda t: t.position)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task.approval_status != TaskApprovalStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Task must be approved before completion",
        )

    if not can_complete_task(task, membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to complete this task",
        )

    if task_needs_makeup(task) and membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This overdue task needs a make-up grant before it can be completed",
        )
    if task_needs_makeup(task) and membership.role == PartnerRole.dominant:
        # Dom completing overdue counts as granting make-up.
        task.makeup_status = "granted"
        task.makeup_granted_at = datetime.utcnow()

    if not task_visible(task, tasks, membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task is hidden")

    if task.completed_at is None:
        completed_at = datetime.utcnow()
        if task.recurrence != TaskRecurrence.none:
            schedule_next_occurrence(task, from_time=task.next_due_at or task.due_at or completed_at)
            clear_makeup(task)
            _maybe_push_task(db, task_list.dynamic_id, user, task)
        else:
            task.completed_at = completed_at
            clear_makeup(task)
            _maybe_complete_google(db, task_list.dynamic_id, user, task)
        post_system_event(
            db,
            task_list.dynamic_id,
            membership,
            f"completed task: {task_snippet(task.content)}",
        )
        db.commit()

    task_list = _task_list_query(db, task_list_id)
    return task_list_out(task_list, membership)


@router.patch(
    "/tasks/{task_list_id}/items/{task_id}/approval",
    response_model=TaskListOut,
)
def review_task(
    task_list_id: str,
    task_id: str,
    approved: Annotated[bool, Query()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")

    membership = get_membership(task_list.dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can approve tasks",
        )

    task = next((t for t in task_list.tasks if t.id == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task.approval_status = (
        TaskApprovalStatus.approved if approved else TaskApprovalStatus.rejected
    )
    verb = "approved" if approved else "rejected"
    post_system_event(
        db,
        task_list.dynamic_id,
        membership,
        f"{verb} task: {task_snippet(task.content)}",
    )
    if approved:
        _maybe_push_task(db, task_list.dynamic_id, user, task)
    db.commit()

    task_list = _task_list_query(db, task_list_id)
    return task_list_out(task_list, membership)


@router.delete("/tasks/{task_list_id}/items/{task_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_task(
    task_list_id: str,
    task_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")

    membership = get_membership(task_list.dynamic_id, user, db)
    task = next((t for t in task_list.tasks if t.id == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    is_owner = task.created_by_membership_id == membership.id
    if membership.role != PartnerRole.dominant and not (task.is_private and is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can remove tasks",
        )

    snippet = task_snippet(task.content)
    db.delete(task)
    post_system_event(
        db,
        task_list.dynamic_id,
        membership,
        f"removed task: {snippet}",
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_task_or_404(task_list: TaskList, task_id: str) -> Task:
    task = next((t for t in task_list.tasks if t.id == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.patch("/tasks/{task_list_id}/items/{task_id}", response_model=TaskListOut)
def update_task_item(
    task_list_id: str,
    task_id: str,
    payload: TaskItemUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")
    membership = get_membership(task_list.dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can edit tasks",
        )
    task = _get_task_or_404(task_list, task_id)
    if payload.content is not None:
        task.content = payload.content.strip()
    if payload.tags is not None:
        task.tags = tags_to_string(payload.tags)
    if payload.paused is not None:
        task.paused = bool(payload.paused)
    if payload.recurrence is not None:
        task.recurrence = payload.recurrence
        if payload.recurrence == TaskRecurrence.none:
            task.next_due_at = None
        elif task.next_due_at is None:
            task.next_due_at = task.due_at or datetime.utcnow()
    post_system_event(
        db,
        task_list.dynamic_id,
        membership,
        f"updated task: {task_snippet(task.content)}",
    )
    db.commit()
    task_list = _task_list_query(db, task_list_id)
    return task_list_out(task_list, membership)


@router.post("/tasks/{task_list_id}/items/{task_id}/makeup-request", response_model=TaskListOut)
def request_task_makeup(
    task_list_id: str,
    task_id: str,
    payload: TaskMakeupRequestIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")
    membership = get_membership(task_list.dynamic_id, user, db)
    task = _get_task_or_404(task_list, task_id)
    if not can_complete_task(task, membership) and membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your task")
    if task.completed_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task already completed")
    due = _effective_due(task)
    if due is None or due > datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Make-up is only for overdue tasks",
        )
    task.makeup_status = "pending"
    task.makeup_note = (payload.note or "").strip()
    task.makeup_requested_at = datetime.utcnow()
    task.makeup_granted_at = None
    post_system_event(
        db,
        task_list.dynamic_id,
        membership,
        f"requested make-up for task: {task_snippet(task.content)}",
    )
    db.commit()
    task_list = _task_list_query(db, task_list_id)
    return task_list_out(task_list, membership)


@router.post("/tasks/{task_list_id}/items/{task_id}/makeup-review", response_model=TaskListOut)
def review_task_makeup(
    task_list_id: str,
    task_id: str,
    payload: TaskMakeupReviewIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")
    membership = get_membership(task_list.dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can review make-up requests",
        )
    task = _get_task_or_404(task_list, task_id)
    note = (payload.note or "").strip()
    if payload.approved:
        task.makeup_status = "granted"
        task.makeup_granted_at = datetime.utcnow()
        if note:
            task.makeup_note = note
        verb = "granted make-up for"
    else:
        task.makeup_status = "denied"
        task.makeup_granted_at = None
        if note:
            task.makeup_note = note
        verb = "denied make-up for"
    post_system_event(
        db,
        task_list.dynamic_id,
        membership,
        f"{verb} task: {task_snippet(task.content)}",
    )
    db.commit()
    task_list = _task_list_query(db, task_list_id)
    return task_list_out(task_list, membership)


@router.post(
    "/tasks/{task_list_id}/items/{task_id}/makeup-assist",
    response_model=TaskMakeupAssistOut,
)
def assist_task_makeup_note(
    task_list_id: str,
    task_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskMakeupAssistOut:
    task_list = _task_list_query(db, task_list_id)
    if task_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task list not found")
    membership = get_membership(task_list.dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can use make-up assist",
        )
    task = _get_task_or_404(task_list, task_id)
    dynamic = db.get(Dynamic, task_list.dynamic_id)
    if dynamic is None or not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI is not configured for this dynamic",
        )
    ctx = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=False,
    )
    prompt = f"""Draft a short Domme note for granting a make-up on a missed task.

Task: {task.content}
Sub request note: {(task.makeup_note or '').strip() or '(none)'}
Recurrence: {task.recurrence.value if hasattr(task.recurrence, 'value') else task.recurrence}

Write 2-4 sentences in assistant-domme tone: acknowledge the miss, set clear expectations for the make-up, and keep it firm but caring. Output only the note text."""
    note = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=ctx,
        dynamic=dynamic,
        tool_id="tasks",
        db=db,
    )
    return TaskMakeupAssistOut(note=(note or "").strip())


@router.post("/dynamics/{dynamic_id}/tasks/bulk", response_model=list[TaskListOut])
def bulk_task_action(
    dynamic_id: str,
    payload: TaskBulkActionIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TaskListOut]:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can bulk-edit tasks",
        )
    lists = (
        db.query(TaskList)
        .options(
            joinedload(TaskList.tasks).joinedload(Task.assigned_to),
            joinedload(TaskList.dynamic).joinedload(Dynamic.memberships),
        )
        .filter(TaskList.dynamic_id == dynamic_id)
        .all()
    )
    by_id: dict[str, tuple[TaskList, Task]] = {}
    for task_list in lists:
        for task in task_list.tasks:
            by_id[task.id] = (task_list, task)

    touched_list_ids: set[str] = set()
    tag = (payload.tag or "").strip()
    for task_id in payload.task_ids:
        pair = by_id.get(task_id)
        if not pair:
            continue
        task_list, task = pair
        if payload.action == "pause":
            task.paused = True
        elif payload.action == "unpause":
            task.paused = False
        elif payload.action == "remove_future":
            # Keep history of completed one-shots; stop recurring series.
            if task.recurrence != TaskRecurrence.none:
                task.recurrence = TaskRecurrence.none
                task.next_due_at = None
                task.paused = False
                if not task.completed_at:
                    # Cancel open future by marking done without rolling.
                    task.completed_at = datetime.utcnow()
                    clear_makeup(task)
        elif payload.action == "apply_tag":
            if not tag:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="tag is required for apply_tag",
                )
            existing = tags_to_list(task.tags)
            if tag not in existing:
                existing.append(tag)
                task.tags = tags_to_string(existing)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown action")
        touched_list_ids.add(task_list.id)

    if touched_list_ids:
        post_system_event(
            db,
            dynamic_id,
            membership,
            f"bulk task action ({payload.action}) on {len(touched_list_ids)} list(s)",
        )
        db.commit()

    out = []
    for list_id in touched_list_ids:
        refreshed = _task_list_query(db, list_id)
        if refreshed:
            out.append(task_list_out(refreshed, membership))
    return out
