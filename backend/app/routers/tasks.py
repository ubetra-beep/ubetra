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
    TaskCalendarItem,
    TaskCalendarOut,
    TaskItemCreate,
    TaskListCreate,
    TaskListOut,
)
from ..services.tags import tags_to_list, tags_to_string
from ..services.tasks_service import (
    ack_inbox,
    build_inbox,
    can_complete_task,
    resolve_due_at,
    schedule_next_occurrence,
    task_list_out,
    task_visible,
)
from ..services.chat_events import post_system_event, task_snippet
from ..services.google_tasks import (
    complete_google_task,
    push_task_to_google,
    sync_target_user,
)


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
    return TagPresetsOut(presets=merged)


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
    dynamic.tag_presets = tags_to_string(payload.presets)
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

    if not task_visible(task, tasks, membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task is hidden")

    if task.completed_at is None:
        completed_at = datetime.utcnow()
        if task.recurrence != TaskRecurrence.none:
            schedule_next_occurrence(task, from_time=task.next_due_at or task.due_at or completed_at)
            _maybe_push_task(db, task_list.dynamic_id, user, task)
        else:
            task.completed_at = completed_at
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
