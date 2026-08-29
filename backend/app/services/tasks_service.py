from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChatMessage,
    ChatMessageType,
    Dynamic,
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


from ..timeutil import as_naive_utc


def relative_delta(amount: int | None, unit: str | None):
    if not amount or not unit:
        return None
    unit = unit.lower()
    return {
        "minutes": timedelta(minutes=amount),
        "hours": timedelta(hours=amount),
        "days": timedelta(days=amount),
        "weeks": timedelta(weeks=amount),
    }.get(unit)


def resolve_due_at(
    *,
    due_at: datetime | None,
    due_in_amount: int | None,
    due_in_unit: str | None,
) -> datetime | None:
    if due_at is not None:
        return as_naive_utc(due_at)
    delta = relative_delta(due_in_amount, due_in_unit)
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
    task.auto_punish_applied_at = None


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
        created_by_membership_id=task.created_by_membership_id,
        created_by_display_name=(
            memberships.get(task.created_by_membership_id).display_name
            if task.created_by_membership_id and memberships and memberships.get(task.created_by_membership_id)
            else None
        ),
        is_private=bool(getattr(task, "is_private", False)),
        public_code_word=task.public_code_word or "",
        google_task_id=task.google_task_id or "",
        google_synced=bool((task.google_task_id or "").strip()),
        paused=bool(getattr(task, "paused", False)),
        makeup_status=(getattr(task, "makeup_status", None) or "none"),
        makeup_note=(getattr(task, "makeup_note", None) or ""),
        makeup_requested_at=getattr(task, "makeup_requested_at", None),
        makeup_granted_at=getattr(task, "makeup_granted_at", None),
        web_url=(getattr(task, "web_url", None) or ""),
        web_minutes=getattr(task, "web_minutes", None),
        change_request_type=(getattr(task, "change_request_type", None) or ""),
        change_request_note=(getattr(task, "change_request_note", None) or ""),
        change_request_proposed_content=(getattr(task, "change_request_proposed_content", None) or ""),
        change_request_at=getattr(task, "change_request_at", None),
        auto_punish_applied_at=getattr(task, "auto_punish_applied_at", None),
        completed_late=bool(getattr(task, "completed_late", False)),
        late_ack_at=getattr(task, "late_ack_at", None),
        late_ack_action=(getattr(task, "late_ack_action", None) or ""),
        remind_at=getattr(task, "remind_at", None),
        remind_every_minutes=getattr(task, "remind_every_minutes", None),
        due_notify_lead_minutes=getattr(task, "due_notify_lead_minutes", None),
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


DEFAULT_AI_SHARE_FLAGS = {
    "journals": True,
    "stories": True,
    "scenes": True,
    "agreements": True,
    "tracking": True,
}


def parse_ai_share_flags(raw: str | None) -> dict:
    data = dict(DEFAULT_AI_SHARE_FLAGS)
    text = (raw or "").strip()
    if not text:
        return data
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return data
    if not isinstance(parsed, dict):
        return data
    for key in DEFAULT_AI_SHARE_FLAGS:
        if key in parsed:
            data[key] = bool(parsed[key])
    return data


def parse_auto_punish_rules(raw: str | None) -> dict:
    text = (raw or "").strip()
    out = {"enabled": False, "rules": []}
    if not text:
        return out
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, dict):
        return out
    out["enabled"] = bool(data.get("enabled"))
    rules = []
    for raw_rule in data.get("rules") or []:
        if not isinstance(raw_rule, dict):
            continue
        tag = str(raw_rule.get("tag") or "").strip().lower()
        goal_id = str(raw_rule.get("goal_id") or "").strip()
        rtype = str(raw_rule.get("requirement_type") or "").strip()
        try:
            add = float(raw_rule.get("add") or 0)
        except (TypeError, ValueError):
            continue
        if not tag or not goal_id or not rtype or add <= 0:
            continue
        rules.append({"tag": tag, "goal_id": goal_id, "requirement_type": rtype, "add": add})
    out["rules"] = rules
    return out


def serialize_auto_punish_rules(data: dict) -> str:
    parsed = parse_auto_punish_rules(json.dumps(data if isinstance(data, dict) else {}))
    return json.dumps(parsed)


def apply_due_auto_punish(db: Session, dynamic_id: str) -> list[dict]:
    """Apply tag-based goal bumps the first time a task is overdue. Returns missing-tag alerts."""
    from .punishments import apply_requirement_bumps
    from .chastity_goals import parse_goals
    from .tags import tags_to_list

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        return []
    cfg = parse_auto_punish_rules(getattr(dynamic, "auto_punish_rules", None))
    if not cfg["enabled"]:
        return []
    rules_by_tag: dict[str, list[dict]] = {}
    for rule in cfg["rules"]:
        rules_by_tag.setdefault(rule["tag"], []).append(rule)
    goals = (parse_goals(getattr(dynamic, "chastity_goals", None)).get("goals") or [])
    active_goal_ids = {g["id"] for g in goals if g.get("active")}
    now = datetime.utcnow()
    missing: list[dict] = []
    dirty = False
    lists = (
        db.query(TaskList)
        .options(joinedload(TaskList.tasks))
        .filter(TaskList.dynamic_id == dynamic_id)
        .all()
    )
    for task_list in lists:
        for task in task_list.tasks:
            if task.completed_at or getattr(task, "paused", False):
                continue
            if task.approval_status != TaskApprovalStatus.approved:
                continue
            if getattr(task, "auto_punish_applied_at", None):
                continue
            due = task.next_due_at or task.due_at
            if due is None or due > now:
                continue
            tags = tags_to_list(task.tags)
            matched = []
            unmatched = []
            for tag in tags:
                key = tag.lower()
                if key in rules_by_tag:
                    matched.extend(rules_by_tag[key])
                else:
                    unmatched.append(tag)
            if not tags:
                unmatched = ["(untagged)"]
            adjustments = []
            for rule in matched:
                if rule["goal_id"] not in active_goal_ids:
                    unmatched.append(rule["tag"])
                    continue
                adjustments.append(
                    {
                        "goal_id": rule["goal_id"],
                        "requirement_type": rule["requirement_type"],
                        "add": rule["add"],
                    }
                )
            if adjustments:
                applied = apply_requirement_bumps(dynamic, adjustments)
                if applied:
                    task.auto_punish_applied_at = now
                    dirty = True
            if unmatched and not adjustments:
                missing.append(
                    {
                        "task_id": task.id,
                        "content": (task.content or "")[:160],
                        "tags": unmatched,
                    }
                )
    if dirty:
        db.add(dynamic)
        db.flush()
    return missing


def auto_punish_inbox_items(dynamic_id: str, membership: Membership, missing: list[dict]) -> list[dict]:
    if membership.role != PartnerRole.dominant or not missing:
        return []
    items = []
    for row in missing:
        tags = ", ".join(row.get("tags") or []) or "untagged"
        items.append(
            {
                "id": f"autopunish-missing-{row['task_id']}",
                "kind": "auto_punish_unconfigured",
                "title": "Auto-punish needs a goal",
                "body": f"Missed task “{row['content']}” has no auto-punish rule for {tags}.",
                "occurred_at": datetime.utcnow(),
                "path": f"/dynamic/{dynamic_id}/tasks?tab=goals&focus=autopunish",
                "task_id": row["task_id"],
            }
        )
    return items


def change_request_inbox_items(db: Session, dynamic_id: str, membership: Membership) -> list[dict]:
    if membership.role != PartnerRole.dominant:
        return []
    items = []
    lists = (
        db.query(TaskList)
        .options(joinedload(TaskList.tasks))
        .filter(TaskList.dynamic_id == dynamic_id)
        .all()
    )
    for task_list in lists:
        for task in task_list.tasks:
            kind = (getattr(task, "change_request_type", None) or "").strip().lower()
            if kind not in {"edit", "remove"}:
                continue
            verb = "edit" if kind == "edit" else "remove"
            items.append(
                {
                    "id": f"task-change-{task.id}",
                    "kind": "task_change_request",
                    "title": f"Task {verb} requested",
                    "body": (task.content or "")[:200],
                    "occurred_at": getattr(task, "change_request_at", None) or datetime.utcnow(),
                    "path": f"/dynamic/{dynamic_id}/tasks?task={task.id}",
                    "task_id": task.id,
                }
            )
    return items


def build_inbox(db: Session, dynamic_id: str, membership: Membership) -> dict:
    """Pending frosted-overlay items: activity since ack + tasks due soon."""
    since = membership.inbox_acked_at or (datetime.utcnow() - timedelta(days=14))
    now = datetime.utcnow()
    soon = now + timedelta(hours=24)

    items: list[dict] = []

    dynamic = db.get(Dynamic, dynamic_id)
    notify_feelings = bool(getattr(dynamic, "feelings_notify_inbox", False)) if dynamic else False

    events = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.dynamic_id == dynamic_id,
            ChatMessage.message_type == ChatMessageType.system,
            ChatMessage.cleared_at.is_(None),
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
        if action == "feelings_logged" and not notify_feelings:
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
                    "path": f"/dynamic/{dynamic_id}/tasks?task={task.id}",
                    "task_id": task.id,
                    "task_list_id": task_list.id,
                }
            )

    if membership.role == PartnerRole.dominant:
        for task_list in lists:
            for task in task_list.tasks:
                if not task.completed_at:
                    continue
                if not bool(getattr(task, "completed_late", False)):
                    continue
                if getattr(task, "late_ack_at", None):
                    continue
                items.append(
                    {
                        "id": f"late-{task.id}",
                        "kind": "task_completed_late",
                        "title": "Task completed late",
                        "body": (task.content or "")[:200],
                        "occurred_at": task.completed_at,
                        "path": f"/dynamic/{dynamic_id}/tasks?task={task.id}",
                        "task_id": task.id,
                        "task_list_id": task_list.id,
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

    missing = apply_due_auto_punish(db, dynamic_id)
    extra = [
        *auto_punish_inbox_items(dynamic_id, membership, missing),
        *change_request_inbox_items(db, dynamic_id, membership),
    ]
    if extra:
        items = [*extra, *items]
        items.sort(key=lambda i: (i.get("occurred_at") or datetime.min).isoformat(), reverse=True)
        db.commit()
    elif missing is not None:
        db.commit()

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
        "task_completed_late": "Task completed late",
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
    if action == "task_completed_late" or (action or "").startswith("task"):
        return f"/dynamic/{dynamic_id}/tasks"
    if "punishment" in (action or ""):
        return f"/dynamic/{dynamic_id}/punishment"
    return f"/dynamic/{dynamic_id}/track"

def ack_inbox(membership: Membership) -> None:
    membership.inbox_acked_at = datetime.utcnow()
