from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal
from ..models import Dynamic, Membership, PartnerRole, Task, TaskApprovalStatus, TaskList
from ..timeutil import as_naive_utc
from .push import notify_task_push
from .tasks_service import (
    daily_occurrence_ready,
    default_reminder_offsets,
    parse_reminder_offsets,
    relative_delta,
    reset_due_reminders,
    task_visible,
)

logger = logging.getLogger(__name__)

OVERDUE_GRACE = timedelta(minutes=2)

_stop = threading.Event()
_thread: threading.Thread | None = None


def assignee_user_ids(db: Session, task: Task, dynamic_id: str) -> set[str]:
    members = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    assigned = getattr(task, "assigned_to_membership_id", None)
    if assigned:
        return {m.user_id for m in members if m.id == assigned}
    if getattr(task, "is_private", False):
        return {m.user_id for m in members if m.id == task.created_by_membership_id}
    return {m.user_id for m in members if m.role == PartnerRole.submissive}


def _snippet(task: Task) -> str:
    return (task.content or "Task").strip().replace("\n", " ")[:80]


def _assignee_name(members: list[Membership], task: Task) -> str:
    assigned = getattr(task, "assigned_to_membership_id", None)
    member = next((m for m in members if m.id == assigned), None) if assigned else None
    if member is None:
        member = next((m for m in members if m.role == PartnerRole.submissive), None)
    return (getattr(member, "display_name", None) or "Your sub").strip() or "Your sub"


def duration_label(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes >= 1440 and minutes % 1440 == 0:
        n = minutes // 1440
        return f"{n} day" if n == 1 else f"{n} days"
    if minutes >= 60 and minutes % 60 == 0:
        n = minutes // 60
        return f"{n} hour" if n == 1 else f"{n} hours"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def task_reminder_offsets(task: Task, dynamic: Dynamic) -> list[int]:
    own = parse_reminder_offsets(getattr(task, "reminder_offsets", None))
    if own is not None:
        return own
    return default_reminder_offsets(dynamic)


def _sent_offsets(task: Task, due: datetime) -> list[int] | None:
    raw = getattr(task, "due_reminders_sent", None) or ""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("due") != due.isoformat():
        return None
    return [int(x) for x in (data.get("sent") or []) if isinstance(x, (int, float))]


def _task_url(dynamic_id: str, task: Task) -> str:
    return f"/#/dynamic/{dynamic_id}/tasks?task={task.id}"


def notify_task_assigned(db: Session, *, dynamic_id: str, task: Task) -> None:
    if task.approval_status != TaskApprovalStatus.approved:
        return
    if getattr(task, "paused", False) or task.completed_at:
        return
    if getattr(task, "available_notified_at", None):
        return
    user_ids = assignee_user_ids(db, task, dynamic_id)
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
    snippet = _snippet(task)
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


def notify_task_completed(db: Session, *, dynamic_id: str, task: Task, actor: Membership) -> None:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None or not bool(getattr(dynamic, "task_complete_notify", True)):
        return
    if getattr(task, "is_private", False):
        return
    members = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    keyholder_ids = {
        m.user_id for m in members if m.role == PartnerRole.dominant and m.id != actor.id
    }
    if not keyholder_ids:
        return
    name = (getattr(actor, "display_name", None) or "Your sub").strip() or "Your sub"
    notify_task_push(
        db,
        dynamic_id=dynamic_id,
        user_ids=keyholder_ids,
        title="Task completed",
        body=f"{name}: {_snippet(task)}",
        url=_task_url(dynamic_id, task),
        tag=f"ubetra-done-{task.id}",
    )


def notify_task_overdue(
    db: Session,
    *,
    dynamic_id: str,
    task: Task,
    members: list[Membership],
    user_ids: set[str],
) -> None:
    snippet = _snippet(task)
    if user_ids:
        notify_task_push(
            db,
            dynamic_id=dynamic_id,
            user_ids=user_ids,
            title="Task overdue",
            body=snippet,
            url=_task_url(dynamic_id, task),
            tag=f"ubetra-overdue-{task.id}",
        )
    if getattr(task, "is_private", False):
        return
    keyholder_ids = {
        m.user_id for m in members if m.role == PartnerRole.dominant
    } - user_ids
    if not keyholder_ids:
        return
    notify_task_push(
        db,
        dynamic_id=dynamic_id,
        user_ids=keyholder_ids,
        title=f"{_assignee_name(members, task)} is late",
        body=snippet,
        url=f"/#/dynamic/{dynamic_id}/tasks?task={task.id}&overdue=1",
        tag=f"ubetra-overdue-kh-{task.id}",
    )


def _process_due_reminders(
    db: Session,
    *,
    dynamic_id: str,
    task: Task,
    due: datetime,
    offsets: list[int],
    user_ids: set[str],
    now: datetime,
) -> bool:
    sent = _sent_offsets(task, due)
    if sent is None:
        legacy = None if getattr(task, "due_reminders_sent", None) else getattr(task, "due_soon_notified_at", None)
        sent = [o for o in offsets if legacy is not None and due - timedelta(minutes=o) <= legacy]
    crossed = [
        o for o in offsets
        if o not in sent and due - timedelta(minutes=o) <= now <= due + OVERDUE_GRACE
    ]
    if not crossed:
        return False
    if due <= now:
        title = "Task due now"
    else:
        remaining = int((due - now).total_seconds() + 59) // 60
        title = f"Task due in {duration_label(remaining)}"
    notify_task_push(
        db,
        dynamic_id=dynamic_id,
        user_ids=user_ids,
        title=title,
        body=_snippet(task),
        url=_task_url(dynamic_id, task),
        tag=f"ubetra-task-due-{task.id}",
    )
    task.due_reminders_sent = json.dumps(
        {"due": due.isoformat(), "sent": sorted(set(sent) | set(crossed), reverse=True)}
    )
    task.due_soon_notified_at = now
    return True


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
        viewer = next((m for m in members if m.role == PartnerRole.submissive), None)
        for task in ordered:
            if task.completed_at or getattr(task, "paused", False):
                continue
            if task.approval_status != TaskApprovalStatus.approved:
                continue
            if viewer and not getattr(task, "is_private", False) and not task_visible(task, ordered, viewer):
                continue
            if not daily_occurrence_ready(task, now):
                continue
            due = task.next_due_at or task.due_at
            user_ids = assignee_user_ids(db, task, task_list.dynamic_id)
            snippet = _snippet(task)
            url = _task_url(task_list.dynamic_id, task)

            if due is not None:
                offsets = task_reminder_offsets(task, dynamic)
                if offsets and _process_due_reminders(
                    db,
                    dynamic_id=task_list.dynamic_id,
                    task=task,
                    due=due,
                    offsets=offsets,
                    user_ids=user_ids,
                    now=now,
                ):
                    dirty = True
                notified = getattr(task, "overdue_notified_at", None)
                if now >= due + OVERDUE_GRACE and (notified is None or notified < due):
                    notify_task_overdue(
                        db,
                        dynamic_id=task_list.dynamic_id,
                        task=task,
                        members=members,
                        user_ids=user_ids,
                    )
                    task.overdue_notified_at = now
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
    from .chastity_goals import poll_goal_progress

    poll_goal_progress(db)


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
    reset_due_reminders(task)
