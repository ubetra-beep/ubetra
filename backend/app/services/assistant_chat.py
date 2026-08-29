"""Assistant Domme conversation subjects, threads, and suggestion parsing."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import (
    AssistantChangeLog,
    AssistantMessage,
    AssistantThread,
    Dynamic,
    Membership,
    PartnerRole,
    PunishmentReport,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    TaskSource,
    TaskVisibility,
    User,
)
from .assistant_permissions import authorize_suggestion
from .chat_events import post_system_event, task_snippet
from .chastity_goals import REQUIREMENT_TYPES, parse_goals, serialize_goals
from .context_maps import build_assistant_context
from .features import OPTIONAL_FEATURES
from .llm import generate_text, is_llm_configured
from .page_capabilities import route_key_from_parts
from .punishments import mark_covered
from .settings_policy import apply_setting
from .standing_targets import METRICS, parse_standing_targets, serialize_standing_targets
from .tags import tags_to_string

SUBJECTS = [
    {
        "id": "what_can_you_do",
        "title": "What can assistant do?",
        "blurb": "Capabilities, example prompts, and confirm-to-apply cards.",
        "always": True,
    },
    {
        "id": "open_chat",
        "title": "Open conversation",
        "blurb": "Ask anything about this dynamic. The assistant can see enabled menus and shared data.",
        "always": True,
    },
    {
        "id": "this_page",
        "title": "This page",
        "blurb": "What you can do on the screen you are on, and a next step.",
        "always": True,
    },
    {
        "id": "goal_coach",
        "title": "Goal coach",
        "blurb": "Gift goals and standing targets — easier vs tighter this day, week, or month.",
        "always": True,
    },
    {
        "id": "feature_audit",
        "title": "Feature audit",
        "blurb": "Enabled modules vs last used. Offer to turn unused ones off.",
        "always": True,
    },
    {
        "id": "orgasm_review",
        "title": "Orgasm review",
        "blurb": "Both partners this window vs last. Offer an easier path and a tighter path.",
        "always": True,
    },
    {
        "id": "chastity_review",
        "title": "Chastity review",
        "blurb": "Lockup hours, percent locked, breaks — what to try next.",
        "always": True,
    },
    {
        "id": "suggest_tease",
        "title": "Suggest a tease",
        "blurb": "One concrete tease, then ask if it appeals or they want another direction.",
        "always": True,
    },
    {
        "id": "suggest_punishment",
        "title": "Suggest a punishment",
        "blurb": "Only if a confession is pending. Otherwise say none is waiting.",
        "always": True,
    },
    {
        "id": "suggest_service",
        "title": "Suggest service",
        "blurb": "Domestic, sexual, sensual, or degrading — matching limits.",
        "always": True,
    },
    {
        "id": "confession",
        "title": "Review a confession",
        "blurb": "Look at journals, history, and goals before you decide how to move forward.",
    },
    {
        "id": "task_drought",
        "title": "Task drought",
        "blurb": "Few or no open tasks for the sub.",
    },
    {
        "id": "orgasm_balance",
        "title": "Orgasm balance",
        "blurb": "Sub orgasms rising versus the keyholder — ask if that is intentional.",
    },
    {
        "id": "lockup_trend",
        "title": "Lockup trend",
        "blurb": "Lockup time has been falling — ask if that is intentional.",
    },
    {
        "id": "inbox",
        "title": "Inbox",
        "blurb": "Overdue work, late completes, make-up, and pending punishments.",
    },
    {
        "id": "journal_review",
        "title": "Journal review",
        "blurb": "New partner-visible journal entries.",
    },
    {
        "id": "goal_progress",
        "title": "Goal progress",
        "blurb": "Gift goals that are stalled or ready to grant.",
    },
    {
        "id": "scene_ideas",
        "title": "Scene ideas",
        "blurb": "Jump into Playtime scene builder with a suggested lean.",
    },
]

SUBJECT_BY_ID = {row["id"]: row for row in SUBJECTS}

SUGGESTION_TYPES = {
    "create_task",
    "adjust_target",
    "create_standing_target",
    "adjust_gift_goal",
    "toggle_feature",
    "assign_punishment_task",
    "open_path",
    "open_scene",
}

SUGGESTIONS_RE = re.compile(
    r"SUGGESTIONS:\s*```(?:json)?\s*(\[.*?\])\s*```",
    re.IGNORECASE | re.DOTALL,
)
SUGGESTIONS_BARE_RE = re.compile(
    r"SUGGESTIONS:\s*(\[[\s\S]*\])\s*$",
    re.IGNORECASE,
)

CHAT_SYSTEM = """You are the Assistant Domme co-pilot for the KEYHOLDER only.

Stay in scope of this app. Use the live feature list: never invent a menu that is OFF.
Partner Chat transcripts are private — you cannot read them and must not pretend you can.
Do not lock, unlock, complete tasks, or message the sub. The keyholder applies suggestion cards.

Invent a specific idea from live data. Do not only recycle interview or kink text.
Ask whether the idea appeals, or whether they want another direction.
Always offer a fork: easier vs more challenging for this day / week / month.

When you propose a concrete next step the keyholder can tap, end your message with:

SUGGESTIONS:
```json
[{"type":"create_task","content":"…","tags":["Sexual"]}]
```

Allowed suggestion types:
- create_task: content (required), tags (optional list)
- assign_punishment_task: content, tags, report_id (optional), mark_covered (bool)
- adjust_target: target_id, and optionally weight (1-5), target (number), direction
- create_standing_target: metric, target, weight, direction, window_days, title
- adjust_gift_goal: goal_id, and optionally title, requirement_type, add
- toggle_feature: feature_id (optional modules only), enabled (bool)
- open_path: path (app hash path starting with /dynamic/), label
- open_scene: label (optional) — sends them to scene builder

A compact catalog of app areas is always provided. Use live packs listed for the CURRENT area key.
Do not assume numbers for packs that were not included this turn. If they ask about another area, use the catalog one-liner and offer open_path so they open that screen (live packs load there).
Do not request or invent a full data dump. Follow-up turns refresh live metrics only.

Keep replies under 250 words unless they ask for more.
"""

SUBJECT_PREAMBLES = {
    "what_can_you_do": (
        "Explain what you can do in this app, list example prompts, and mention that "
        "mutations need the keyholder's Apply (and their permission grants). "
        "Include demo-style suggestion cards they can tap."
    ),
    "open_chat": "The keyholder opened a freeform conversation.",
    "this_page": "Help with the current screen. Be specific about buttons and flows that exist there.",
    "goal_coach": (
        "Coach gift goals and standing targets together. Comment on task/reward ratios, window lengths, "
        "and weights. Propose an easier fork and a tighter fork for day, week, and month."
    ),
    "feature_audit": (
        "Compare enabled optional features to last-used timestamps. Name unused or under-used modules. "
        "Offer toggle_feature to disable ones they are not using. Do not disable core menus."
    ),
    "orgasm_review": (
        "Review both partners' orgasms this window vs last. Ask if the split is intentional. "
        "Offer two paths: ease (more sub orgasms / looser ratio) vs tighten (denial / more to keyholder)."
    ),
    "chastity_review": (
        "Review lockup hours, percent locked, and breaks. Offer options to try. Do not lock or unlock."
    ),
    "suggest_tease": (
        "Give ONE concrete tease for tonight or this week. Then ask: does this appeal, or another direction?"
    ),
    "suggest_punishment": (
        "If a pending confession exists, suggest a specific punishment task matching limits. "
        "If none is pending, say so — do not invent a confession."
    ),
    "suggest_service": (
        "Pick a lane: domestic / sexual / sensual / degrading. Match interviews and agreements. "
        "Offer the idea, then ask if they want a different lane."
    ),
    "confession": (
        "A submissive confessed. Review the confession text, recent journals, tracking, and goals. "
        "Offer an opinion on how to move forward (goal bump, punishment task, conversation, or mark covered). "
        "Do not assign anything until they apply a suggestion."
    ),
    "task_drought": (
        "There are few or no open tasks. Ask whether that is intentional. Suggest 2–4 assignable tasks "
        "that fit interviews and agreements if they want more structure."
    ),
    "orgasm_balance": (
        "Sub orgasms have been rising relative to the keyholder (or vs the standing target). "
        "Ask if this is intentional. Offer to tighten denial, add tasks, or adjust the weighted target."
    ),
    "lockup_trend": (
        "Chastity lockup time or percent locked has been falling vs the prior window or vs the standing target. "
        "Ask if this is intentional. Offer lockup-policy or target adjustments — do not lock/unlock."
    ),
    "inbox": "Triage the inbox items. Suggest what to handle first.",
    "journal_review": "New journal material is available. Summarize tone and flag anything that needs a keyholder response.",
    "goal_progress": "Gift/unlock goals may be ready to grant or stalled. Advise, don't grant.",
    "scene_ideas": "The keyholder wants scene ideas. Point them at scene builder and give one concrete lean/effort suggestion.",
}

EXAMPLE_PROMPTS = [
    {"label": "What can you do here?", "text": "What can you do for me on this page?", "subject_id": "this_page"},
    {"label": "Easier vs harder week", "text": "Give me an easier week and a harder week of tasks and lockup.", "subject_id": "goal_coach"},
    {"label": "Orgasm split", "text": "Is our orgasm split still what I want?", "subject_id": "orgasm_review"},
    {"label": "Unused features", "text": "Which features are we not using? Should I turn any off?", "subject_id": "feature_audit"},
    {"label": "Tonight's tease", "text": "Suggest a tease for tonight. One idea, then ask if I want another direction.", "subject_id": "suggest_tease"},
    {"label": "Service task", "text": "Assign a service task in a lane that matches our limits.", "subject_id": "suggest_service"},
]


def require_domme_assistant(
    user: User,
    membership: Membership,
    dynamic: Dynamic,
    *,
    need_llm: bool = True,
) -> None:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Assistant Domme chat is for the keyholder.",
        )
    if not getattr(user, "ai_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI features are turned off.",
        )
    if need_llm and not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add an API key in Settings before chatting with Assistant Domme.",
        )


def subject_catalog() -> list[dict]:
    return list(SUBJECTS)


def demo_suggestions(dynamic_id: str) -> list[dict]:
    return [
        {
            "type": "create_task",
            "content": "Send a check-in photo tonight before bed.",
            "tags": ["Sensual"],
        },
        {
            "type": "open_path",
            "path": f"/dynamic/{dynamic_id}/chastity",
            "label": "Open chastity",
        },
        {
            "type": "open_path",
            "path": f"/dynamic/{dynamic_id}/tasks",
            "label": "Open tasks",
        },
    ]


def _entity_key(related_entity_id: str | None) -> str:
    return (related_entity_id or "").strip()


def get_or_create_thread(
    db: Session,
    *,
    dynamic_id: str,
    membership_id: str,
    subject_id: str,
    related_entity_id: str | None = None,
) -> AssistantThread:
    if subject_id not in SUBJECT_BY_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown assistant subject")
    entity = _entity_key(related_entity_id)
    thread = (
        db.query(AssistantThread)
        .filter(
            AssistantThread.dynamic_id == dynamic_id,
            AssistantThread.membership_id == membership_id,
            AssistantThread.subject_id == subject_id,
            AssistantThread.related_entity_id == entity,
        )
        .first()
    )
    if thread:
        return thread
    thread = AssistantThread(
        dynamic_id=dynamic_id,
        membership_id=membership_id,
        subject_id=subject_id,
        related_entity_id=entity,
    )
    db.add(thread)
    db.flush()
    return thread


def thread_messages(db: Session, thread_id: str) -> list[AssistantMessage]:
    return (
        db.query(AssistantMessage)
        .filter(
            AssistantMessage.thread_id == thread_id,
            AssistantMessage.cleared_at.is_(None),
        )
        .order_by(AssistantMessage.created_at)
        .all()
    )


ASSISTANT_TRASH_DAYS = 7


def _assistant_thread_ids(db: Session, dynamic_id: str, membership_id: str) -> list[str]:
    return [
        tid
        for (tid,) in db.query(AssistantThread.id)
        .filter(
            AssistantThread.dynamic_id == dynamic_id,
            AssistantThread.membership_id == membership_id,
        )
        .all()
    ]


def purge_assistant_trash(db: Session, dynamic_id: str, membership_id: str) -> int:
    cutoff = datetime.utcnow() - timedelta(days=ASSISTANT_TRASH_DAYS)
    ids = _assistant_thread_ids(db, dynamic_id, membership_id)
    if not ids:
        return 0
    return (
        db.query(AssistantMessage)
        .filter(
            AssistantMessage.thread_id.in_(ids),
            AssistantMessage.cleared_at.isnot(None),
            AssistantMessage.cleared_at < cutoff,
        )
        .delete(synchronize_session=False)
    )


def assistant_trash_count(db: Session, dynamic_id: str, membership_id: str) -> int:
    purge_assistant_trash(db, dynamic_id, membership_id)
    ids = _assistant_thread_ids(db, dynamic_id, membership_id)
    if not ids:
        return 0
    return (
        db.query(AssistantMessage)
        .filter(
            AssistantMessage.thread_id.in_(ids),
            AssistantMessage.cleared_at.isnot(None),
        )
        .count()
    )


def clear_assistant_messages(db: Session, dynamic_id: str, membership_id: str) -> int:
    purge_assistant_trash(db, dynamic_id, membership_id)
    ids = _assistant_thread_ids(db, dynamic_id, membership_id)
    if not ids:
        return 0
    q = db.query(AssistantMessage).filter(
        AssistantMessage.thread_id.in_(ids),
        AssistantMessage.cleared_at.is_(None),
    )
    n = q.count()
    if n:
        q.update({AssistantMessage.cleared_at: datetime.utcnow()}, synchronize_session=False)
    return n


def recover_assistant_messages(db: Session, dynamic_id: str, membership_id: str) -> int:
    purge_assistant_trash(db, dynamic_id, membership_id)
    ids = _assistant_thread_ids(db, dynamic_id, membership_id)
    if not ids:
        return 0
    q = db.query(AssistantMessage).filter(
        AssistantMessage.thread_id.in_(ids),
        AssistantMessage.cleared_at.isnot(None),
    )
    n = q.count()
    if n:
        q.update({AssistantMessage.cleared_at: None}, synchronize_session=False)
    return n


def change_log_rows(db: Session, dynamic_id: str, *, limit: int = 30) -> list[dict]:
    rows = (
        db.query(AssistantChangeLog)
        .filter(AssistantChangeLog.dynamic_id == dynamic_id)
        .order_by(AssistantChangeLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "subject_id": row.subject_id,
            "action": row.action,
            "summary": row.summary,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _append_change_log(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    action: str,
    summary: str,
    suggestion: dict,
    subject_id: str = "",
) -> None:
    db.add(
        AssistantChangeLog(
            dynamic_id=dynamic.id,
            membership_id=membership.id,
            subject_id=(subject_id or "")[:64],
            action=action[:64],
            summary=summary[:400],
            payload_json=json.dumps(suggestion)[:8000],
        )
    )


def parse_suggestions(raw: str) -> tuple[str, list[dict]]:
    text = (raw or "").strip()
    blob = None
    match = SUGGESTIONS_RE.search(text)
    if match:
        blob = match.group(1)
        visible = (text[: match.start()] + text[match.end() :]).strip()
    else:
        match = SUGGESTIONS_BARE_RE.search(text)
        if match:
            blob = match.group(1)
            visible = text[: match.start()].strip()
        else:
            visible = text
    suggestions: list[dict] = []
    if blob:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                cleaned = _clean_suggestion(item)
                if cleaned:
                    suggestions.append(cleaned)
    return visible or text, suggestions


def _clean_suggestion(item: dict | object) -> dict | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("type") or "").strip()
    if kind not in SUGGESTION_TYPES:
        return None
    cleaned: dict = {"type": kind}
    if kind in {"create_task", "assign_punishment_task"}:
        content = str(item.get("content") or "").strip()
        if not content:
            return None
        cleaned["content"] = content[:4000]
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        cleaned["tags"] = [str(t).strip() for t in tags if str(t).strip()][:8]
        if kind == "assign_punishment_task":
            if not any(t.lower() == "punishment" for t in cleaned["tags"]):
                cleaned["tags"] = ["Punishment"] + cleaned["tags"]
            rid = str(item.get("report_id") or "").strip()
            if rid:
                cleaned["report_id"] = rid[:36]
            cleaned["mark_covered"] = bool(item.get("mark_covered", True))
    elif kind == "adjust_target":
        tid = str(item.get("target_id") or "").strip()
        if not tid:
            return None
        cleaned["target_id"] = tid
        if item.get("weight") is not None:
            try:
                cleaned["weight"] = max(1, min(5, int(item.get("weight"))))
            except (TypeError, ValueError):
                pass
        if item.get("target") is not None:
            try:
                cleaned["target"] = float(item.get("target"))
            except (TypeError, ValueError):
                pass
        if item.get("direction") in {"at_least", "at_most", "hold"}:
            cleaned["direction"] = item.get("direction")
    elif kind == "create_standing_target":
        metric = str(item.get("metric") or "").strip()
        if metric not in METRICS:
            return None
        meta = METRICS[metric]
        cleaned["metric"] = metric
        cleaned["title"] = str(item.get("title") or meta["title"])[:80]
        try:
            cleaned["target"] = float(item.get("target") if item.get("target") is not None else meta["default_target"])
        except (TypeError, ValueError):
            cleaned["target"] = float(meta["default_target"])
        try:
            cleaned["weight"] = max(1, min(5, int(item.get("weight") or 3)))
        except (TypeError, ValueError):
            cleaned["weight"] = 3
        try:
            cleaned["window_days"] = max(3, min(90, int(item.get("window_days") or meta["default_window_days"])))
        except (TypeError, ValueError):
            cleaned["window_days"] = int(meta["default_window_days"])
        cleaned["direction"] = (
            item.get("direction") if item.get("direction") in {"at_least", "at_most", "hold"} else meta["default_direction"]
        )
    elif kind == "adjust_gift_goal":
        gid = str(item.get("goal_id") or "").strip()
        if not gid:
            return None
        cleaned["goal_id"] = gid
        if item.get("title"):
            cleaned["title"] = str(item.get("title"))[:80]
        if item.get("requirement_type"):
            rtype = str(item.get("requirement_type"))[:64]
            if rtype in REQUIREMENT_TYPES:
                cleaned["requirement_type"] = rtype
        if item.get("add") is not None:
            try:
                cleaned["add"] = float(item.get("add"))
            except (TypeError, ValueError):
                pass
    elif kind == "toggle_feature":
        fid = str(item.get("feature_id") or "").strip()
        if fid not in OPTIONAL_FEATURES:
            return None
        cleaned["feature_id"] = fid
        cleaned["enabled"] = bool(item.get("enabled"))
    elif kind == "open_path":
        path = str(item.get("path") or "").strip()
        if not path.startswith("/"):
            return None
        cleaned["path"] = path[:300]
        cleaned["label"] = str(item.get("label") or "Open")[:80]
    elif kind == "open_scene":
        cleaned["label"] = str(item.get("label") or "Open scene builder")[:80]
    if item.get("label") and kind not in {"open_path", "open_scene"}:
        cleaned["label"] = str(item.get("label"))[:80]
    return cleaned


def _history_lines(messages: list[AssistantMessage]) -> str:
    lines = []
    for msg in messages[-16:]:
        speaker = "Keyholder" if msg.role == "user" else "Assistant"
        lines.append(f"{speaker}: {msg.content}")
    return "\n".join(lines)


def _confession_block(db: Session, dynamic_id: str, report_id: str) -> str:
    if not report_id:
        return ""
    report = db.get(PunishmentReport, report_id)
    if report is None or report.dynamic_id != dynamic_id:
        return ""
    return (
        f"Pending confession id={report.id} status={report.status} "
        f"at {report.created_at}:\n{(report.action_text or '').strip()[:2000]}"
    )


def _change_log_block(db: Session, dynamic_id: str) -> str:
    rows = change_log_rows(db, dynamic_id, limit=20)
    if not rows:
        return ""
    lines = ["Recent changes applied from Assistant chat:"]
    for row in rows:
        when = row["created_at"].isoformat() if row.get("created_at") else ""
        lines.append(f"  - {when} {row.get('action')}: {row.get('summary')}")
    return "\n".join(lines)


def reply_to_assistant(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
    thread: AssistantThread,
    message: str,
    route: str = "",
    feature_id: str = "",
) -> tuple[AssistantMessage, AssistantMessage]:
    user_msg = AssistantMessage(
        thread_id=thread.id,
        role="user",
        content=message.strip(),
    )
    db.add(user_msg)
    db.flush()

    parts = [p for p in (route or "").strip().strip("/").split("/") if p]
    if parts[:1] == ["dynamic"]:
        parts = parts[2:]
    route_key = route_key_from_parts(parts) or (parts[0] if parts else "")

    extra: list[str] = []
    preamble = SUBJECT_PREAMBLES.get(thread.subject_id, "")
    if preamble:
        extra.append(preamble)
    if thread.subject_id == "confession":
        extra.append(_confession_block(db, dynamic.id, thread.related_entity_id))
    if thread.subject_id == "what_can_you_do":
        extra.append("Example prompts: " + "; ".join(p["text"] for p in EXAMPLE_PROMPTS))

    prior_assistant = (
        db.query(AssistantMessage)
        .filter(
            AssistantMessage.thread_id == thread.id,
            AssistantMessage.role == "assistant",
            AssistantMessage.cleared_at.is_(None),
        )
        .count()
    )
    context = build_assistant_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        route_key=route_key,
        first_turn=prior_assistant == 0,
        include_tracking=bool(user.assistant_include_tracking),
        subject_id=thread.subject_id,
    )
    history = _history_lines(thread_messages(db, thread.id))
    extra_block = "\n\n".join(line for line in extra if line)
    prompt = f"""Subject: {SUBJECT_BY_ID.get(thread.subject_id, {}).get('title', thread.subject_id)}

{extra_block}

Conversation so far:
{history}

Reply to the keyholder. If this is the first message and they only opened the subject, greet briefly and give a concrete read of the situation."""

    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        system_instruction=CHAT_SYSTEM,
        dynamic=dynamic,
        tool_id="assistant",
        db=db,
    )
    visible, suggestions = parse_suggestions(raw)
    assistant_msg = AssistantMessage(
        thread_id=thread.id,
        role="assistant",
        content=visible or raw.strip(),
        suggestions_json=json.dumps(suggestions),
    )
    db.add(assistant_msg)
    thread.updated_at = datetime.utcnow()
    thread.unread = False
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    return user_msg, assistant_msg


def _sub_membership(db: Session, dynamic_id: str) -> Membership | None:
    return (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.submissive)
        .first()
    )


def _assistant_task_list(db: Session, dynamic: Dynamic, membership: Membership) -> TaskList:
    task_list = (
        db.query(TaskList)
        .filter(TaskList.dynamic_id == dynamic.id, TaskList.title == "Assistant tasks")
        .first()
    )
    if task_list is None:
        task_list = TaskList(
            dynamic_id=dynamic.id,
            title="Assistant tasks",
            created_by_membership_id=membership.id,
        )
        db.add(task_list)
        db.flush()
    return task_list


def _create_task_row(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    content: str,
    tags: list,
) -> Task:
    task_list = _assistant_task_list(db, dynamic, membership)
    sub = _sub_membership(db, dynamic.id)
    position = db.query(Task).filter(Task.task_list_id == task_list.id).count()
    task = Task(
        task_list_id=task_list.id,
        position=position,
        content=content,
        visibility=TaskVisibility.visible,
        tags=tags_to_string([str(t) for t in tags]),
        approval_status=TaskApprovalStatus.approved,
        source=TaskSource.assistant,
        created_by_membership_id=membership.id,
        assigned_to_membership_id=sub.id if sub else None,
        recurrence=TaskRecurrence.none,
    )
    db.add(task)
    return task


def apply_suggestion(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    suggestion: dict,
    subject_id: str = "",
    grant: str | None = None,
) -> dict:
    cleaned = _clean_suggestion(suggestion) if suggestion.get("type") else None
    if cleaned is None and suggestion.get("type") in {"open_path", "open_scene", "create_task"}:
        cleaned = _clean_suggestion(suggestion)
    if cleaned is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown suggestion type")
    kind = cleaned["type"]

    auth = authorize_suggestion(dynamic, kind, grant)
    if auth.get("denied"):
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Assistant is not allowed to {auth.get('capability')}.",
        )
    if auth.get("needs_permission"):
        db.commit()
        return {
            "ok": False,
            "needs_permission": True,
            "capability": auth.get("capability"),
            "label": auth.get("label") or auth.get("capability"),
            "suggestion": cleaned,
        }

    if kind == "create_task":
        _create_task_row(
            db,
            dynamic=dynamic,
            membership=membership,
            content=cleaned["content"],
            tags=cleaned.get("tags") or [],
        )
        summary = f"assigned task (assistant): {task_snippet(cleaned['content'])}"
        post_system_event(db, dynamic.id, membership, summary)
        _append_change_log(
            db,
            dynamic=dynamic,
            membership=membership,
            action=kind,
            summary=summary,
            suggestion=cleaned,
            subject_id=subject_id,
        )
        db.commit()
        return {"ok": True, "applied": kind}

    if kind == "assign_punishment_task":
        _create_task_row(
            db,
            dynamic=dynamic,
            membership=membership,
            content=cleaned["content"],
            tags=cleaned.get("tags") or ["Punishment"],
        )
        summary = f"assigned punishment task (assistant): {task_snippet(cleaned['content'])}"
        post_system_event(db, dynamic.id, membership, summary)
        report_id = cleaned.get("report_id") or ""
        if report_id and cleaned.get("mark_covered"):
            report = db.get(PunishmentReport, report_id)
            if report is not None and report.dynamic_id == dynamic.id:
                mark_covered(db, membership=membership, report=report)
                summary = f"{summary}; marked confession covered"
        _append_change_log(
            db,
            dynamic=dynamic,
            membership=membership,
            action=kind,
            summary=summary,
            suggestion=cleaned,
            subject_id=subject_id,
        )
        db.commit()
        return {"ok": True, "applied": kind}

    if kind == "adjust_target":
        target_id = cleaned["target_id"]
        data = parse_standing_targets(getattr(dynamic, "standing_targets", None))
        found = next((row for row in data["targets"] if row["id"] == target_id), None)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing target not found")
        if cleaned.get("weight") is not None:
            found["weight"] = cleaned["weight"]
        if cleaned.get("target") is not None:
            found["target"] = cleaned["target"]
        if cleaned.get("direction"):
            found["direction"] = cleaned["direction"]
        dynamic.standing_targets = serialize_standing_targets(data)
        summary = f"adjusted standing target {found.get('title') or target_id}"
        post_system_event(db, dynamic.id, membership, summary)
        _append_change_log(
            db,
            dynamic=dynamic,
            membership=membership,
            action=kind,
            summary=summary,
            suggestion=cleaned,
            subject_id=subject_id,
        )
        db.commit()
        return {"ok": True, "applied": kind}

    if kind == "create_standing_target":
        data = parse_standing_targets(getattr(dynamic, "standing_targets", None))
        row = {
            "id": str(uuid.uuid4()),
            "metric": cleaned["metric"],
            "title": cleaned.get("title") or METRICS[cleaned["metric"]]["title"],
            "weight": cleaned.get("weight") or 3,
            "target": cleaned.get("target"),
            "window_days": cleaned.get("window_days"),
            "direction": cleaned.get("direction"),
        }
        data["targets"].append(row)
        dynamic.standing_targets = serialize_standing_targets(data)
        summary = f"added standing target {row['title']}"
        post_system_event(db, dynamic.id, membership, summary)
        _append_change_log(
            db,
            dynamic=dynamic,
            membership=membership,
            action=kind,
            summary=summary,
            suggestion=cleaned,
            subject_id=subject_id,
        )
        db.commit()
        return {"ok": True, "applied": kind, "target_id": row["id"]}

    if kind == "adjust_gift_goal":
        data = parse_goals(getattr(dynamic, "chastity_goals", None))
        found = next((g for g in data.get("goals") or [] if g.get("id") == cleaned["goal_id"]), None)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gift goal not found")
        if cleaned.get("title"):
            found["title"] = cleaned["title"]
        if cleaned.get("requirement_type") and cleaned.get("add") is not None:
            reqs = found.get("requirements") or []
            matched = False
            for req in reqs:
                if req.get("type") == cleaned["requirement_type"]:
                    req["value"] = float(req.get("value") or 0) + float(cleaned["add"])
                    matched = True
                    break
            if not matched:
                reqs.append({"type": cleaned["requirement_type"], "value": float(cleaned["add"])})
            found["requirements"] = reqs
        dynamic.chastity_goals = serialize_goals(data)
        summary = f"adjusted gift goal {found.get('title') or cleaned['goal_id']}"
        post_system_event(db, dynamic.id, membership, summary)
        _append_change_log(
            db,
            dynamic=dynamic,
            membership=membership,
            action=kind,
            summary=summary,
            suggestion=cleaned,
            subject_id=subject_id,
        )
        db.commit()
        return {"ok": True, "applied": kind}

    if kind == "toggle_feature":
        summary = apply_setting(
            db,
            dynamic,
            setting_key=f"features.{cleaned['feature_id']}",
            value=bool(cleaned.get("enabled")),
        )
        post_system_event(db, dynamic.id, membership, summary)
        _append_change_log(
            db,
            dynamic=dynamic,
            membership=membership,
            action=kind,
            summary=summary,
            suggestion=cleaned,
            subject_id=subject_id,
        )
        db.commit()
        return {"ok": True, "applied": kind}

    if kind in {"open_path", "open_scene"}:
        return {"ok": True, "applied": kind, "navigate": True}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown suggestion type")
