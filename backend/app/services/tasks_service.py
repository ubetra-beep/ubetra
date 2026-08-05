from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChatMessage,
    ChatMessageType,
    Membership,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    TaskVisibility,
)
from ..schemas import TaskListOut, TaskOut
from ..services.tags import tags_to_list


_LINK_RE = re.compile(r"\[\[(?:from|ubetra):[^\]]+\]\]")


def resolve_due_at(
    *,
    due_at: datetime | None,
    due_in_amount: int | None,
    due_in_unit: str | None,
) -> datetime | None:
    if due_at is not None:
        return due_at
    if not due_in_amount or not due_in_unit:
        return None
    unit = due_in_unit.lower()
    delta = {
        "minutes": timedelta(minutes=due_in_amount),
        "hours": timedelta(hours=due_in_amount),
        "days": timedelta(days=due_in_amount),
        "weeks": timedelta(weeks=due_in_amount),
    }.get(unit)
    if delta is None:
        return None
    return datetime.utcnow() + delta


def advance_due_date(current: datetime, recurrence: TaskRecurrence) -> datetime:
    if recurrence == TaskRecurrence.daily:
        return current + timedelta(days=1)
    if recurrence == TaskRecurrence.weekly:
        return current + timedelta(days=7)
    if recurrence == TaskRecurrence.monthly:
        return current + timedelta(days=30)
    return current


def schedule_next_occurrence(task: Task, *, from_time: datetime | None = None) -> None:
    if task.recurrence == TaskRecurrence.none:
        task.next_due_at = None
        return
    base = from_time or task.next_due_at or task.due_at or datetime.utcnow()
    task.completed_at = None
    task.next_due_at = advance_due_date(base, task.recurrence)


def task_visible(task: Task, tasks: list[Task], viewer: Membership) -> bool:
    viewer_role = viewer.role
    if getattr(task, "is_private", False):
        if task.created_by_membership_id == viewer.id:
            return True
        if task.assigned_to_membership_id == viewer.id:
            return True
        return False
    if viewer_role == PartnerRole.dominant:
        return True
    if task.approval_status != TaskApprovalStatus.approved:
        return True
    if task.visibility == TaskVisibility.visible:
        return True
    index = next(i for i, t in enumerate(tasks) if t.id == task.id)
    if index == 0:
        return True
    prior = tasks[index - 1]
    return prior.completed_at is not None


def task_out(
    task: Task,
    tasks: list[Task],
    viewer: Membership,
    memberships: dict[str, Membership] | None = None,
) -> TaskOut:
    hidden = not task_visible(task, tasks, viewer)
    content = task.content if not hidden else "Complete the prior task to reveal this one."
    assignee_id = getattr(task, "assigned_to_membership_id", None)
    assignee_name = None
    if assignee_id and memberships:
        m = memberships.get(assignee_id)
        assignee_name = m.display_name if m else None
    elif assignee_id and task.assigned_to is not None:
        assignee_name = task.assigned_to.display_name
    return TaskOut(
        id=task.id,
        position=task.position,
        content=content,
        visibility=task.visibility,
        completed_at=task.completed_at,
        hidden=hidden,
        tags=tags_to_list(task.tags),
        approval_status=task.approval_status,
        source=task.source,
        recurrence=task.recurrence,
        due_at=task.due_at,
        next_due_at=task.next_due_at,
        act_id=task.act_id,
        assigned_to_membership_id=assignee_id,
        assigned_to_display_name=assignee_name,
        is_private=bool(getattr(task, "is_private", False)),
        public_code_word=task.public_code_word or "",
        google_task_id=task.google_task_id or "",
        google_synced=bool((task.google_task_id or "").strip()),
        paused=bool(getattr(task, "paused", False)),
        makeup_status=(getattr(task, "makeup_status", None) or "none"),
        makeup_note=(getattr(task, "makeup_note", None) or ""),
        makeup_requested_at=getattr(task, "makeup_requested_at", None),
        makeup_granted_at=getattr(task, "makeup_granted_at", None),
    )


def task_list_out(task_list: TaskList, viewer: Membership) -> TaskListOut:
    memberships = {
        m.id: m
        for m in (
            task_list.dynamic.memberships
            if getattr(task_list, "dynamic", None) is not None
            else []
        )
    }
    tasks = sorted(task_list.tasks, key=lambda t: t.position)
    rows_src = []
    for t in tasks:
        if getattr(t, "is_private", False) and not task_visible(t, tasks, viewer):
            continue
        rows_src.append(t)
    task_rows = [task_out(task, tasks, viewer, memberships) for task in rows_src]
    approved = [t for t in rows_src if t.approval_status == TaskApprovalStatus.approved]
    all_done = bool(approved) and all(t.completed_at for t in approved)
    return TaskListOut(
        id=task_list.id,
        title=task_list.title,
        created_at=task_list.created_at,
        status="completed" if all_done else "active",
        tasks=task_rows,
    )


def can_complete_task(task: Task, membership: Membership) -> bool:
    if getattr(task, "paused", False):
        return False
    if membership.role == PartnerRole.dominant:
        return True
    assignee = getattr(task, "assigned_to_membership_id", None)
    if assignee:
        return assignee == membership.id
    if getattr(task, "is_private", False):
        return task.created_by_membership_id == membership.id
    return membership.role == PartnerRole.submissive


def task_needs_makeup(task: Task, *, now: datetime | None = None) -> bool:
    """Overdue incomplete tasks require makeup grant before complete (unless already granted)."""
    if task.completed_at or task.approval_status != TaskApprovalStatus.approved:
        return False
    if getattr(task, "paused", False):
        return False
    due = task.next_due_at or task.due_at
    if due is None:
        return False
    now = now or datetime.utcnow()
    if due > now:
        return False
    status = (getattr(task, "makeup_status", None) or "none").lower()
    return status != "granted"


def clear_makeup(task: Task) -> None:
    task.makeup_status = "none"
    task.makeup_note = ""
    task.makeup_requested_at = None
    task.makeup_granted_at = None


def build_inbox(db: Session, dynamic_id: str, membership: Membership) -> dict:
    """Pending frosted-overlay items: activity since ack + tasks due soon."""
    since = membership.inbox_acked_at or (datetime.utcnow() - timedelta(days=14))
    now = datetime.utcnow()
    soon = now + timedelta(hours=24)

    items: list[dict] = []

    events = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.dynamic_id == dynamic_id,
            ChatMessage.message_type == ChatMessageType.system,
            ChatMessage.created_at > since,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(40)
        .all()
    )
    for msg in events:
        action = (msg.action or "").strip()
        if not action:
            continue
        # Punishment inbox is keyholder-only (dedicated rows below).
        if action.startswith("punishment") and membership.role != PartnerRole.dominant:
            continue
        body = _clean_event_body(msg.body or "")
        path = ""
        if msg.payload_json:
            try:
                path = (json.loads(msg.payload_json) or {}).get("path") or ""
            except Exception:
                path = ""
        items.append(
            {
                "id": f"evt-{msg.id}",
                "kind": action,
                "title": _event_title(action, body),
                "body": body,
                "occurred_at": msg.created_at,
                "path": path or _event_path(dynamic_id, action),
            }
        )

    lists = (
        db.query(TaskList)
        .options(joinedload(TaskList.tasks))
        .filter(TaskList.dynamic_id == dynamic_id)
        .all()
    )
    for task_list in lists:
        ordered = sorted(task_list.tasks, key=lambda t: t.position)
        for task in ordered:
            if task.completed_at:
                continue
            if getattr(task, "paused", False):
                continue
            if task.approval_status != TaskApprovalStatus.approved:
                continue
            if not task_visible(task, ordered, membership):
                continue
            due = task.next_due_at or task.due_at
            if due is None or due > soon:
                continue
            assignee = getattr(task, "assigned_to_membership_id", None)
            if assignee and assignee != membership.id:
                continue
            if not assignee:
                if getattr(task, "is_private", False):
                    if task.created_by_membership_id != membership.id:
                        continue
                elif membership.role != PartnerRole.submissive:
                    continue
            overdue = due <= now
            items.append(
                {
                    "id": f"task-{task.id}",
                    "kind": "task_overdue" if overdue else "task_due_soon",
                    "title": "Task overdue" if overdue else "Task due soon",
                    "body": task.content[:200],
                    "occurred_at": due,
                    "path": f"/dynamic/{dynamic_id}/tasks",
                    "task_id": task.id,
                }
            )

    items.sort(key=lambda i: (i.get("occurred_at") or datetime.min).isoformat(), reverse=True)

    # Keyholder: pending confessions + due reminders (also via dedicated rows)
    from .punishments import inbox_items_for_member

    punish_items = inbox_items_for_member(db, dynamic_id, membership)
    if punish_items:
        # Prefer dedicated punishment items; drop duplicate chat events of the same kind
        items = [i for i in items if i.get("kind") not in {"punishment_pending", "punishment_self_report"}]
        items = [*punish_items, *items]
        items.sort(key=lambda i: (i.get("occurred_at") or datetime.min).isoformat(), reverse=True)

    return {
        "acked_at": membership.inbox_acked_at,
        "items": items[:50],
    }


def _clean_event_body(body: str) -> str:
    return _LINK_RE.sub("", body).strip()


def _event_title(action: str, body: str) -> str:
    labels = {
        "lockup_ended": "Chastity unlock / release",
        "lockup_started": "Chastity lockup started",
        "orgasm_logged": "Orgasm logged",
        "play_logged": "Play logged",
        "feelings_logged": "Feelings logged",
        "punishment_pending": "Punishment needed",
        "punishment_assigned": "Punishment assigned",
        "punishment_covered": "Punishment covered",
    }
    if action in labels:
        return labels[action]
    if action:
        return action.replace("_", " ").title()
    return "Activity"


def _event_path(dynamic_id: str, action: str) -> str:
    if action in {"lockup_ended", "lockup_started"} or "lockup" in (action or ""):
        return f"/dynamic/{dynamic_id}/chastity"
    if action in {"orgasm_logged", "play_logged"}:
        return f"/dynamic/{dynamic_id}/tracking"
    if action == "feelings_logged":
        return f"/dynamic/{dynamic_id}/feelings"
    if "punishment" in (action or ""):
        return f"/dynamic/{dynamic_id}/punishment"
    return f"/dynamic/{dynamic_id}/track"

def ack_inbox(membership: Membership) -> None:
    membership.inbox_acked_at = datetime.utcnow()
