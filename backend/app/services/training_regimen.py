from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole, Task, TaskApprovalStatus, TaskList, User
from ..schemas import (
    RegimenListOut,
    RegimenMessageOut,
    RegimenSuggestedTag,
    RegimenTagNote,
    RegimenTaskIdea,
    TrainingRegimenOut,
)
from .context import build_dynamic_context
from .llm import generate_text, is_llm_configured
from .playtime import _extract_json
from .tags import tags_to_list, tags_to_string

DEFAULT_TASK_TAGS = "Domestic,Health / Hygiene,Sensual,Sexual"
MAX_MESSAGES = 24


def current_task_tags(dynamic: Dynamic) -> list[str]:
    raw = getattr(dynamic, "task_tag_presets", None) or DEFAULT_TASK_TAGS
    tags = tags_to_list(raw)
    return tags or tags_to_list(DEFAULT_TASK_TAGS)


def load_state(dynamic: Dynamic) -> dict[str, Any]:
    raw = getattr(dynamic, "training_regimen_state", None) or ""
    if not raw.strip():
        return empty_state(dynamic)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return empty_state(dynamic)
    if not isinstance(data, dict):
        return empty_state(dynamic)
    data.setdefault("phase", "")
    data.setdefault("messages", [])
    data.setdefault("tag_notes", [])
    data.setdefault("suggested_tags", [])
    data.setdefault("focus_tags", [])
    data.setdefault("lists", [])
    if data.get("phase") == "tags_review":
        data["phase"] = "pick_focus"
    data["tags"] = current_task_tags(dynamic)
    return data


def empty_state(dynamic: Dynamic) -> dict[str, Any]:
    return {
        "phase": "",
        "messages": [],
        "tags": current_task_tags(dynamic),
        "tag_notes": [],
        "suggested_tags": [],
        "focus_tags": [],
        "lists": [],
    }


def save_state(dynamic: Dynamic, state: dict[str, Any]) -> None:
    payload = {
        "phase": state.get("phase") or "",
        "messages": (state.get("messages") or [])[-MAX_MESSAGES:],
        "tag_notes": state.get("tag_notes") or [],
        "suggested_tags": state.get("suggested_tags") or [],
        "focus_tags": state.get("focus_tags") or [],
        "lists": state.get("lists") or [],
    }
    dynamic.training_regimen_state = json.dumps(payload, ensure_ascii=False)


def state_out(
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
    state: dict[str, Any] | None = None,
) -> TrainingRegimenOut:
    data = state if state is not None else load_state(dynamic)
    tags = current_task_tags(dynamic)
    return TrainingRegimenOut(
        phase=data.get("phase") or "",
        tags=tags,
        tag_notes=[RegimenTagNote(**_tag_note(row)) for row in data.get("tag_notes") or []],
        suggested_tags=[
            RegimenSuggestedTag(**_suggested(row))
            for row in data.get("suggested_tags") or []
            if isinstance(row, dict)
            and _canon(str(row.get("tag") or ""))
            and _canon(str(row.get("tag") or ""), tags) not in tags
        ],
        focus_tags=data.get("focus_tags") or [],
        lists=[_list_out(row) for row in data.get("lists") or []],
        messages=[
            RegimenMessageOut(
                role=str(m.get("role") or "assistant"),
                content=str(m.get("content") or ""),
                kind=str(m.get("kind") or "text"),
            )
            for m in data.get("messages") or []
            if isinstance(m, dict) and str(m.get("content") or "").strip()
        ],
        llm_configured=is_llm_configured(user, dynamic),
        interview_completed=bool(membership.interview_completed),
    )


def _tag_note(row: Any) -> dict[str, str]:
    if not isinstance(row, dict):
        return {"tag": "", "note": ""}
    return {"tag": str(row.get("tag") or "").strip(), "note": str(row.get("note") or "").strip()}


def _suggested(row: Any) -> dict[str, str]:
    if not isinstance(row, dict):
        return {"tag": "", "why": ""}
    return {"tag": str(row.get("tag") or "").strip(), "why": str(row.get("why") or "").strip()}


def _idea_title(title: str, content: str) -> str:
    t = " ".join((title or "").split()).strip()
    if t:
        return t[:80]
    first = " ".join((content or "").strip().split())
    if not first:
        return "Task"
    for sep in (". ", "! ", "? "):
        if sep in first:
            first = first.split(sep, 1)[0]
            break
    first = first.rstrip(".:;").strip()
    return (first or "Task")[:80]


def _list_out(row: Any) -> RegimenListOut:
    if not isinstance(row, dict):
        row = {}
    tasks = []
    for item in row.get("tasks") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        tasks.append(
            RegimenTaskIdea(
                id=str(item.get("id") or uuid.uuid4()),
                title=_idea_title(str(item.get("title") or ""), content),
                content=content,
                selected=bool(item.get("selected")),
                due_tod=_due_tod(item.get("due_tod")),
            )
        )
    recurrence = str(row.get("recurrence") or "daily").strip().lower()
    if recurrence not in ("daily", "weekly"):
        recurrence = "daily"
    tag = str(row.get("tag") or "").strip()
    return RegimenListOut(
        id=str(row.get("id") or uuid.uuid4()),
        title=_group_title(recurrence, tag),
        recurrence=recurrence,
        tag=tag,
        tasks=tasks,
        assigned=bool(row.get("assigned")),
    )


def _canon(name: str, known: list[str] | None = None) -> str:
    key = " ".join((name or "").strip().lower().split())
    if not key:
        return ""
    for tag in known or []:
        if tag.lower() == key:
            return tag
    return key


def _append(state: dict[str, Any], role: str, content: str, kind: str = "text") -> None:
    text = (content or "").strip()
    if not text:
        return
    state.setdefault("messages", []).append({"role": role, "content": text, "kind": kind})


def _history_block(state: dict[str, Any]) -> str:
    lines = []
    for msg in (state.get("messages") or [])[-12:]:
        if not isinstance(msg, dict):
            continue
        role = "Domme" if msg.get("role") == "user" else "Assistant"
        content = str(msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(no prior messages)"


def _group_title(recurrence: str, tag: str) -> str:
    rec_label = "Weekly" if recurrence == "weekly" else "Daily"
    label = " ".join((tag or "").split()).strip()
    if label:
        return f"{rec_label} · {label}"
    return rec_label


def _due_tod(raw: Any) -> str:
    text = str(raw or "").strip().lower().replace(".", "")
    if not text:
        return ""
    match = re.match(r"^(\d{1,2}):(\d{2})(?:\s*(am|pm))?$", text)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _open_tasks_block(db: Session, dynamic_id: str) -> str:
    rows = (
        db.query(Task, TaskList)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(TaskList.dynamic_id == dynamic_id)
        .all()
    )
    items: list[str] = []
    for task, task_list in rows:
        if task.approval_status == TaskApprovalStatus.rejected:
            continue
        rec = task.recurrence.value if hasattr(task.recurrence, "value") else (task.recurrence or "none")
        tags = tags_to_list(task.tags or "")
        tag_bit = f" [{', '.join(tags)}]" if tags else ""
        status = "done" if task.completed_at else ("paused" if task.paused else "open")
        items.append(
            f"- ({rec}, {status}) {task.content.strip()}{tag_bit} — list “{task_list.title}”"
        )
        if len(items) >= 60:
            break
    if not items:
        return "No existing tasks yet."
    return "Existing assigned tasks in this dynamic (do not suggest duplicates):\n" + "\n".join(items)


def _draft_ideas_block(state: dict[str, Any]) -> str:
    lines: list[str] = []
    for lst in state.get("lists") or []:
        if not isinstance(lst, dict):
            continue
        rec = lst.get("recurrence") or "daily"
        for task in lst.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            title = str(task.get("title") or "").strip()
            content = str(task.get("content") or "").strip()
            if not title and not content:
                continue
            lines.append(f"- ({rec}) {title}: {content}"[:280])
            if len(lines) >= 40:
                break
        if len(lines) >= 40:
            break
    if not lines:
        return ""
    return "Already suggested in this session (do not repeat these titles or instructions):\n" + "\n".join(lines)


def _require_dom_ready(membership: Membership, user: User, dynamic: Dynamic) -> None:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant partner can build a training regimen",
        )
    if not getattr(user, "ai_enabled", True):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AI features are turned off")
    if not membership.interview_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your dynamic interview first so the regimen matches this couple.",
        )
    if not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add your API key in Settings before using the training assistant.",
        )


def _context(db: Session, dynamic: Dynamic, membership: Membership, user: User) -> str:
    return build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=bool(user.assistant_include_tracking),
    )


def _llm_json(
    *,
    user: User,
    dynamic: Dynamic,
    db: Session,
    ctx: str,
    prompt: str,
) -> dict:
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=ctx,
        dynamic=dynamic,
        tool_id="tasks",
        db=db,
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an unexpected response. Try again.",
        )
    return data


def start_session(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
    force: bool = False,
) -> dict[str, Any]:
    _require_dom_ready(membership, user, dynamic)
    state = load_state(dynamic)
    if state.get("phase") and not force:
        return state

    tags = current_task_tags(dynamic)
    state = empty_state(dynamic)
    state["phase"] = "pick_focus"
    state["focus_tags"] = list(tags)
    _append(
        state,
        "assistant",
        "Pick the types you want help with, then generate. "
        "Check the ideas you like, expand any to edit the wording, and assign when you're ready.",
        "pick_focus",
    )
    save_state(dynamic, state)
    return state


def suggest_tags(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
) -> dict[str, Any]:
    _require_dom_ready(membership, user, dynamic)
    state = load_state(dynamic)
    if not state.get("phase"):
        state = start_session(db, dynamic=dynamic, membership=membership, user=user)
    tags = current_task_tags(dynamic)
    ctx = _context(db, dynamic, membership, user)
    prompt = f"""Suggest extra task-category tags for this couple's training regimen.

They already have: {", ".join(tags) or "(none)"}

Return 0–4 short new tags (1–3 words) that are not already in that list and that fit their negotiated dynamic.
Empty array is fine if nothing extra is needed.

Return ONLY valid JSON:
{{
  "suggested_tags": [
    {{"tag": "Protocol", "why": "one short sentence"}}
  ]
}}
"""
    data = _llm_json(user=user, dynamic=dynamic, db=db, ctx=ctx, prompt=prompt)
    suggested = []
    seen = set(tags)
    for row in data.get("suggested_tags") or []:
        if not isinstance(row, dict):
            continue
        tag = _canon(str(row.get("tag") or ""))
        if not tag or tag in seen:
            continue
        seen.add(tag)
        suggested.append({"tag": tag, "why": str(row.get("why") or "").strip()})
        if len(suggested) >= 4:
            break
    state["suggested_tags"] = suggested
    save_state(dynamic, state)
    return state


def add_tag(dynamic: Dynamic, tag_name: str) -> dict[str, Any]:
    tag = _canon(tag_name)
    if not tag:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a tag name")
    tags = current_task_tags(dynamic)
    if tag not in tags:
        tags.append(tag)
        dynamic.task_tag_presets = tags_to_string(tags)
    state = load_state(dynamic)
    state["tags"] = tags
    notes = state.get("tag_notes") or []
    if not any(_canon(n.get("tag") if isinstance(n, dict) else "") == tag for n in notes):
        notes.append({"tag": tag, "note": f"New category for {tag} tasks."})
        state["tag_notes"] = notes
    state["suggested_tags"] = [
        row
        for row in (state.get("suggested_tags") or [])
        if isinstance(row, dict) and _canon(str(row.get("tag") or "")) != tag
    ]
    save_state(dynamic, state)
    return state


def advance_to_focus(dynamic: Dynamic) -> dict[str, Any]:
    state = load_state(dynamic)
    if not state.get("phase"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start the assistant first")
    tags = current_task_tags(dynamic)
    names = ", ".join(tags) if tags else "your tags"
    state["phase"] = "pick_focus"
    state["tags"] = tags
    _append(
        state,
        "assistant",
        f"Which of these do you want help generating — daily and weekly lists? "
        f"You can pick one type or several: {names}.",
        "pick_focus",
    )
    save_state(dynamic, state)
    return state


def _normalize_lists(raw_lists: Any, known_tags: list[str]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(raw_lists, list):
        return []
    for row in raw_lists:
        if not isinstance(row, dict):
            continue
        rec = str(row.get("recurrence") or "daily").strip().lower()
        if rec not in ("daily", "weekly"):
            rec = "daily"
        tag = _canon(str(row.get("tag") or ""), known_tags)
        key = (rec, tag)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "id": str(uuid.uuid4()),
                "title": _group_title(rec, tag),
                "recurrence": rec,
                "tag": tag,
                "tasks": [],
                "assigned": False,
            }
            buckets[key] = bucket
        seen = {
            (str(t.get("title") or "").strip().lower(), str(t.get("content") or "").strip().lower()[:80])
            for t in bucket["tasks"]
        }
        for item in row.get("tasks") or []:
            if isinstance(item, str):
                content = item.strip()
                task_title = ""
            elif isinstance(item, dict):
                content = str(item.get("content") or "").strip()
                task_title = str(item.get("title") or "").strip()
            else:
                continue
            if not content:
                continue
            task_title = _idea_title(task_title, content)
            sig = (task_title.lower(), content.lower()[:80])
            if sig in seen:
                continue
            seen.add(sig)
            bucket["tasks"].append({
                "id": str(uuid.uuid4()),
                "title": task_title,
                "content": content,
                "selected": False,
                "due_tod": _due_tod(item.get("due_tod") if isinstance(item, dict) else ""),
            })
            if len(bucket["tasks"]) >= 12:
                break
        if len(buckets) >= 10:
            break
    return [b for b in buckets.values() if b["tasks"]]


def _merge_list_buckets(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for lst in [*existing, *incoming]:
        if not isinstance(lst, dict):
            continue
        rec = str(lst.get("recurrence") or "daily")
        if rec not in ("daily", "weekly"):
            rec = "daily"
        tag = str(lst.get("tag") or "")
        key = (rec, tag)
        if key not in buckets:
            row = dict(lst)
            row["recurrence"] = rec
            row["tag"] = tag
            row["title"] = _group_title(rec, tag)
            row["tasks"] = list(lst.get("tasks") or [])
            row["id"] = str(lst.get("id") or uuid.uuid4())
            buckets[key] = row
            order.append(key)
            continue
        dest = buckets[key]
        seen = {
            (str(t.get("title") or "").strip().lower(), str(t.get("content") or "").strip().lower()[:80])
            for t in dest["tasks"]
            if isinstance(t, dict)
        }
        for task in lst.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            sig = (
                str(task.get("title") or "").strip().lower(),
                str(task.get("content") or "").strip().lower()[:80],
            )
            if sig in seen:
                continue
            seen.add(sig)
            dest["tasks"].append(task)
            if len(dest["tasks"]) >= 16:
                break
    return [buckets[k] for k in order]


def generate_lists(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
    focus_tags: list[str],
    note: str = "",
    more: bool = False,
) -> dict[str, Any]:
    _require_dom_ready(membership, user, dynamic)
    state = load_state(dynamic)
    tags = current_task_tags(dynamic)
    chosen = []
    seen = set()
    for name in focus_tags or state.get("focus_tags") or tags:
        tag = _canon(name, tags)
        if tag and tag not in seen:
            chosen.append(tag)
            seen.add(tag)
    if not chosen:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick at least one tag")

    ctx = _context(db, dynamic, membership, user)
    existing = _open_tasks_block(db, dynamic.id)
    drafts = _draft_ideas_block(state)
    note_block = f"Keyholder direction: {note.strip()}\n" if note.strip() else ""
    history = _history_block(state)
    extra = (
        "Return ADDITIONAL new ideas only — do not repeat anything already listed. "
        "About 2–4 more daily and 2–4 more weekly tasks across the chosen tags."
        if more
        else "Keep the whole regimen feasible: about 2–5 daily tasks total across the chosen tags, plus 2–6 weekly tasks total."
    )
    prompt = f"""Build a training regimen: lists of assignable daily and weekly tasks for the submissive.

Ignore the usual 250-word limit. Return JSON only.

All available tags: {", ".join(tags)}
Generate tasks only for these tags: {", ".join(chosen)}
{note_block}{existing}
{drafts}

Conversation so far:
{history}

Rules:
- Concrete, doable tasks the sub can complete without the keyholder present unless the dynamic clearly wants that.
- Stay inside negotiated limits from the context. No illegal, public-exposure, or third-party tasks unless context strongly supports them.
- {extra}
- Each task has one category tag from the chosen list and is either daily or weekly.
- Do not duplicate existing assigned tasks or ideas already suggested in this session.
- List titles MUST be exactly "Daily · <tag>" or "Weekly · <tag>". Never name a list after one of its tasks.
- For Health / Hygiene (and similar tags), include physical workout / exercise ideas (walks, strength, stretches, cardio) as well as hygiene and self-care. Mix both unless the keyholder asked for only one.
- Give each task a due_tod as 24-hour HH:MM for a reasonable time of day (morning chores in the morning, workouts morning or evening, weekly deep-cleans on a typical evening).

Return ONLY valid JSON:
{{
  "message": "A short (2–5 sentence) note introducing the ideas.",
  "lists": [
    {{
      "title": "Daily · domestic",
      "recurrence": "daily",
      "tag": "domestic",
      "tasks": [{{"title": "Short 3–8 word title", "content": "Specific instructions the sub can complete.", "due_tod": "08:00"}}]
    }}
  ]
}}
Group by recurrence + tag. Use only daily or weekly. Every task needs a short title, a content string, and due_tod.
"""
    data = _llm_json(user=user, dynamic=dynamic, db=db, ctx=ctx, prompt=prompt)
    incoming = _normalize_lists(data.get("lists"), tags)
    if more:
        before = sum(
            len(lst.get("tasks") or [])
            for lst in (state.get("lists") or [])
            if isinstance(lst, dict)
        )
        lists = _merge_list_buckets(state.get("lists") or [], incoming)
        after = sum(len(lst.get("tasks") or []) for lst in lists)
        if after <= before:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No new ideas this round. Try a different direction note, or generate again.",
            )
    else:
        lists = incoming
    if not lists:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant did not return any tasks. Try again or pick different tags.",
        )
    message = str(data.get("message") or "").strip() or (
        "More ideas added. Check the ones you agree with, expand any to edit, then assign."
        if more
        else "Here are recommended task ideas. Check the ones you agree with, expand any to edit, then assign."
    )
    if note.strip():
        _append(state, "user", note.strip())
    elif more:
        _append(state, "user", "Generate more task ideas.")
    state["phase"] = "lists"
    state["focus_tags"] = chosen
    state["lists"] = lists
    _append(state, "assistant", message, "lists")
    save_state(dynamic, state)
    return state


def reply(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
    message: str,
) -> dict[str, Any]:
    _require_dom_ready(membership, user, dynamic)
    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type a message first")
    state = load_state(dynamic)
    if not state.get("phase"):
        state = start_session(db, dynamic=dynamic, membership=membership, user=user)
    _append(state, "user", text)
    tags = current_task_tags(dynamic)
    ctx = _context(db, dynamic, membership, user)
    existing = _open_tasks_block(db, dynamic.id)
    drafts = _draft_ideas_block(state)
    phase = state.get("phase") or "pick_focus"
    lists_json = json.dumps(state.get("lists") or [], ensure_ascii=False)[:4000]
    prompt = f"""You are continuing a training-regimen conversation with the dominant.

Ignore the usual 250-word limit. Return JSON only.

Current phase: {phase}
All tags: {", ".join(tags)}
Focus tags already chosen: {", ".join(state.get("focus_tags") or []) or "(none yet)"}
Suggested extra tags still pending: {json.dumps(state.get("suggested_tags") or [], ensure_ascii=False)}
Current draft lists JSON: {lists_json or "[]"}
{existing}
{drafts}

Conversation:
{_history_block(state)}

The keyholder just said:
{text}

Respond in character. Also return structured updates:
- If they want new tags, put them in add_tags (short names) and/or suggested_tags.
- If they name which existing tags to generate for, put them in focus_tags.
- If phase is lists, or they asked to change / regenerate the regimen, return a full updated lists array (same shape as before). Otherwise omit lists or use [].
- Keep tasks feasible (roughly 2–5 daily total, 2–6 weekly total).
- Do not duplicate existing assigned tasks or ideas already in this session.
- List titles MUST be exactly "Daily · <tag>" or "Weekly · <tag>". Never name a list after one of its tasks.
- For Health / Hygiene (and similar tags), include physical workout / exercise ideas as well as hygiene.
- Each task needs due_tod as 24-hour HH:MM.

Return ONLY valid JSON:
{{
  "message": "Conversational reply for the keyholder.",
  "add_tags": ["optional new tag"],
  "suggested_tags": [{{"tag": "name", "why": "why"}}],
  "focus_tags": ["tag"],
  "lists": []
}}
"""
    data = _llm_json(user=user, dynamic=dynamic, db=db, ctx=ctx, prompt=prompt)
    reply_text = str(data.get("message") or "").strip() or "Got it."

    added = []
    for name in data.get("add_tags") or []:
        tag = _canon(str(name))
        if tag and tag not in tags:
            added.append(tag)
            tags.append(tag)
    if added:
        dynamic.task_tag_presets = tags_to_string(tags)
        notes = state.get("tag_notes") or []
        have = {_canon(n.get("tag") if isinstance(n, dict) else "") for n in notes}
        for tag in added:
            if tag not in have:
                notes.append({"tag": tag, "note": f"Added from your note: {tag} tasks."})
        state["tag_notes"] = notes

    suggested = []
    sug_seen = set(tags)
    incoming = data.get("suggested_tags")
    if isinstance(incoming, list) and incoming:
        for row in incoming:
            if not isinstance(row, dict):
                continue
            tag = _canon(str(row.get("tag") or ""))
            if not tag or tag in sug_seen:
                continue
            sug_seen.add(tag)
            suggested.append({"tag": tag, "why": str(row.get("why") or "").strip()})
        if suggested:
            state["suggested_tags"] = suggested

    focus = []
    for name in data.get("focus_tags") or []:
        tag = _canon(str(name), tags)
        if tag and tag in tags and tag not in focus:
            focus.append(tag)
    if focus:
        state["focus_tags"] = focus
        if state.get("phase") in ("tags_review", "pick_focus"):
            state["phase"] = "pick_focus"

    new_lists = _normalize_lists(data.get("lists"), tags)
    kind = "text"
    if new_lists:
        state["lists"] = new_lists
        state["phase"] = "lists"
        kind = "lists"
    elif phase in ("tags_review", "pick_focus"):
        kind = "pick_focus"

    _append(state, "assistant", reply_text, kind)
    state["tags"] = tags
    save_state(dynamic, state)
    return state


def reset_session(dynamic: Dynamic) -> dict[str, Any]:
    state = empty_state(dynamic)
    save_state(dynamic, state)
    return state


def mark_lists_assigned(dynamic: Dynamic, list_ids: list[str]) -> dict[str, Any]:
    state = load_state(dynamic)
    wanted = {str(i) for i in (list_ids or []) if i}
    for row in state.get("lists") or []:
        if isinstance(row, dict) and str(row.get("id") or "") in wanted:
            row["assigned"] = True
    save_state(dynamic, state)
    return state
