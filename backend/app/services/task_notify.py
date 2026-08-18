from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal
from ..models import Dynamic, Membership, PartnerRole, Task, TaskApprovalStatus, TaskList
from ..timeutil import as_naive_utc
from .push import notify_task_push
from .tasks_service import relative_delta, task_visible

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def _assignee_user_ids(db: Session, task: Task, dynamic_id: str) -> set[str]:
    members = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    assigned = getattr(task, "assigned_to_membership_id", None)
    if assigned:
        return {m.user_id for m in members if m.id == assigned}
    if getattr(task, "is_private", False):
        return {m.user_id for m in members if m.id == task.created_by_membership_id}
    return {m.user_id for m in members if m.role == PartnerRole.submissive}


def _task_url(dynamic_id: str, task: Task) -> str:
    return f"/#/dynamic/{dynamic_id}/tasks?task={task.id}"


def notify_task_assigned(db: Session, *, dynamic_id: str, task: Task) -> None:
    if task.approval_status != TaskApprovalStatus.approved:
        return
    if getattr(task, "paused", False) or task.completed_at:
        return
    if getattr(task, "available_notified_at", None):
        return
    user_ids = _assignee_user_ids(db, task, dynamic_id)
    if not user_ids:
        return
    snippet = (task.content or "New task").strip().replace("\n", " ")[:80]
    notify_task_push(
        db,
        dynamic_id=dynamic_id,
        user_ids=user_ids,
        title="New task",
        body=snippet or "A task was added for you",
        url=_task_url(dynamic_id, task),
        tag=f"ubetra-task-{task.id}",
    )
    task.available_notified_at = datetime.utcnow()


def notify_task_available(db: Session, *, dynamic_id: str, task: Task) -> None:
    notify_task_assigned(db, dynamic_id=dynamic_id, task=task)


def notify_late_complete(db: Session, *, dynamic_id: str, task: Task) -> None:
    snippet = (task.content or "Task").strip().replace("\n", " ")[:80]
    notify_task_push(
        db,
        dynamic_id=dynamic_id,
        user_ids=None,
        keyholders_only=True,
        title="Task completed late",
        body=snippet or "A task was completed after it was due",
        url=_task_url(dynamic_id, task),
        tag=f"ubetra-task-late-{task.id}",
    )


def process_task_notifications(db: Session) -> None:
    now = datetime.utcnow()
    lists = (
        db.query(TaskList)
        .options(joinedload(TaskList.tasks), joinedload(TaskList.dynamic))
        .all()
    )
    dirty = False
    for task_list in lists:
        dynamic = task_list.dynamic or db.get(Dynamic, task_list.dynamic_id)
        if dynamic is None or not bool(getattr(dynamic, "task_push_enabled", True)):
            continue
        ordered = sorted(task_list.tasks, key=lambda t: t.position)
        members = list(dynamic.memberships or [])
        default_lead = int(getattr(dynamic, "task_due_lead_minutes", None) or 15)
        for task in ordered:
            if task.completed_at or getattr(task, "paused", False):
                continue
            if task.approval_status != TaskApprovalStatus.approved:
                continue
            viewer = next((m for m in members if m.role == PartnerRole.submissive), None)
            if viewer and not task_visible(task, ordered, viewer):
                continue
            due = task.next_due_at or task.due_at
            lead = task.due_notify_lead_minutes
            if lead is None:
                lead = default_lead
            lead = max(0, int(lead))
            user_ids = _assignee_user_ids(db, task, task_list.dynamic_id)
            snippet = (task.content or "Task").strip().replace("\n", " ")[:80]
            url = _task_url(task_list.dynamic_id, task)

            if due is not None and not getattr(task, "due_soon_notified_at", None):
                window_start = due - timedelta(minutes=lead or 0)
                if window_start <= now <= due + timedelta(minutes=2):
                    title = "Task due now" if due <= now else "Task due soon"
                    notify_task_push(
                        db,
                        dynamic_id=task_list.dynamic_id,
                        user_ids=user_ids,
                        title=title,
                        body=snippet,
                        url=url,
                        tag=f"ubetra-task-due-{task.id}",
                    )
                    task.due_soon_notified_at = now
                    dirty = True

            remind_at = getattr(task, "remind_at", None)
            if remind_at is not None and remind_at <= now:
                notify_task_push(
                    db,
                    dynamic_id=task_list.dynamic_id,
                    user_ids=user_ids,
                    title="Task reminder",
                    body=snippet,
                    url=url,
                    tag=f"ubetra-task-remind-{task.id}",
                )
                every = getattr(task, "remind_every_minutes", None)
                if every and every > 0:
                    nxt = now + timedelta(minutes=int(every))
                    due_cap = due
                    task.remind_at = nxt if (due_cap is None or nxt <= due_cap + timedelta(minutes=5)) else None
                    if task.remind_at is None:
                        task.remind_every_minutes = None
                else:
                    task.remind_at = None
                    task.remind_every_minutes = None
                dirty = True
    if dirty:
        db.commit()


def start_task_notify_loop() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def _loop() -> None:
        while not _stop.wait(40):
            db = SessionLocal()
            try:
                process_task_notifications(db)
            except Exception:
                logger.exception("task notify scan failed")
            finally:
                db.close()

    _thread = threading.Thread(target=_loop, name="ubetra-task-notify", daemon=True)
    _thread.start()


def stop_task_notify_loop() -> None:
    _stop.set()


def set_task_remind(
    task: Task,
    *,
    in_amount: int,
    in_unit: str,
    every_amount: int | None = None,
    every_unit: str | None = None,
) -> None:
    delta = relative_delta(in_amount, in_unit)
    if delta is None:
        return
    task.remind_at = datetime.utcnow() + delta
    every = relative_delta(every_amount, every_unit) if every_amount and every_unit else None
    task.remind_every_minutes = int(every.total_seconds() // 60) if every else None


def reset_due_notice(task: Task, *, due_at: datetime | None) -> None:
    task.due_at = as_naive_utc(due_at) if due_at is not None else due_at
    task.due_soon_notified_at = None
