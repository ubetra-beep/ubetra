from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, Task, TaskCompletion, TaskLibraryItem, TaskList, User
from .context import build_dynamic_context
from .llm import generate_text
from .playtime import _extract_json
from .tags import tags_to_list
from .training_regimen import current_task_tags

SCHEDULES = {"am", "noon", "pm", "oneoff"}
HISTORY_DAYS = 120
MAX_KNOWN = 150


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def known_task_texts(db: Session, dynamic_id: str) -> list[str]:
    """Current, past, and library task wording for this dynamic, newest first, deduped."""
    texts: list[str] = []
    rows = (
        db.query(Task.content)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(TaskList.dynamic_id == dynamic_id)
        .order_by(TaskList.created_at.desc())
        .all()
    )
    texts.extend(r[0] for r in rows)
    texts.extend(
        r[0]
        for r in db.query(TaskLibraryItem.content)
        .filter(TaskLibraryItem.dynamic_id == dynamic_id)
        .order_by(TaskLibraryItem.last_used_at.desc())
        .all()
    )
    since = datetime.utcnow() - timedelta(days=HISTORY_DAYS)
    texts.extend(
        r[0]
        for r in db.query(TaskCompletion.content_snippet)
        .filter(TaskCompletion.dynamic_id == dynamic_id, TaskCompletion.completed_at >= since)
        .order_by(TaskCompletion.completed_at.desc())
        .all()
    )
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        clean = " ".join((text or "").split())
        k = _key(clean)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(clean[:200])
        if len(out) >= MAX_KNOWN:
            break
    return out


def suggest_tasks(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
    note: str,
    count: int,
    avoid: list[str],
) -> list[dict[str, str]]:
    tags = current_task_tags(dynamic)
    known = known_task_texts(db, dynamic.id)
    avoid_clean = [" ".join((a or "").split())[:200] for a in avoid if (a or "").strip()]
    blocked = {_key(t) for t in [*known, *avoid_clean]}
    known_block = "\n".join(f"- {t}" for t in known) or "(none yet)"
    avoid_block = "\n".join(f"- {t}" for t in avoid_clean) or "(none)"
    note_block = f"The dominant asked for: {note.strip()}\n\n" if (note or "").strip() else ""
    prompt = f"""{note_block}Suggest {count} new, distinct tasks the dominant can assign to the submissive.

Tasks that already exist or were done before (never repeat or lightly reword these):
{known_block}

Already suggested in this session (do not repeat):
{avoid_block}

Category tags to choose from: {", ".join(tags)}

Return JSON only:
{{"tasks": [{{"content": "one short actionable task, 1-2 sentences", "tag": "one tag from the list", "schedule": "am|noon|pm|oneoff"}}]}}

schedule: am / noon / pm = repeats daily at that time of day; oneoff = do it once."""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=build_dynamic_context(
            db,
            dynamic,
            requesting_membership_id=membership.id,
            include_tracking=bool(user.assistant_include_tracking),
        ),
        dynamic=dynamic,
        tool_id="tasks",
        db=db,
    )
    data = _extract_json(raw)
    items = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an unexpected response. Try again.",
        )
    tag_lookup = {t.lower(): t for t in tags}
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split())[:500]
        k = _key(content)
        if not k or k in blocked:
            continue
        blocked.add(k)
        tag_raw = tags_to_list(str(item.get("tag") or ""))
        tag = (tag_lookup.get(tag_raw[0].lower()) if tag_raw else None) or (tags[0] if tags else "")
        schedule = str(item.get("schedule") or "").strip().lower()
        out.append({
            "content": content,
            "tag": tag,
            "schedule": schedule if schedule in SCHEDULES else "oneoff",
        })
        if len(out) >= count:
            break
    return out
