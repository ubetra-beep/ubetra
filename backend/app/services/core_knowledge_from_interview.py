from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, User
from .context import CORE_KNOWLEDGE_FIELDS, get_or_create_core_knowledge
from .llm import generate_text, is_llm_configured

FIELD_ORDER = list(CORE_KNOWLEDGE_FIELDS.keys())

FIELD_ALIASES = {
    "relationship_context": ["RELATIONSHIP_CONTEXT", "RELATIONSHIP"],
    "distance": ["DISTANCE", "DISTANCE_LOGISTICS"],
    "space": ["SPACE", "PLAY_SPACE"],
    "budget": ["BUDGET", "BUDGET_RESOURCES"],
    "about_you": ["ABOUT_YOU", "ABOUT"],
    "desires": ["DESIRES", "DESIRES_FANTASIES", "FANTASIES"],
}


def _parse_fielded_response(raw: str) -> dict[str, str]:
    lines = raw.splitlines()
    current_key: str | None = None
    buckets: dict[str, list[str]] = {key: [] for key in FIELD_ORDER}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        matched = False
        for key, aliases in FIELD_ALIASES.items():
            for alias in aliases:
                prefix = f"{alias}:"
                if stripped.upper().startswith(prefix):
                    current_key = key
                    buckets[key].append(stripped.split(":", 1)[1].strip())
                    matched = True
                    break
            if matched:
                break
        if not matched and current_key:
            buckets[current_key].append(stripped)

    return {key: " ".join(parts).strip() for key, parts in buckets.items() if parts}


def _core_knowledge_mostly_empty(record) -> bool:
    filled = sum(1 for key in FIELD_ORDER if (getattr(record, key, None) or "").strip())
    return filled <= 1


def populate_core_knowledge_from_interview(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
    overwrite: bool = False,
) -> tuple[object, bool]:
    """Returns (CoreKnowledge record, used_llm)."""
    if not membership.interview_completed or not (membership.interview_summary or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your dynamic interview first.",
        )

    record = get_or_create_core_knowledge(db, membership)
    summary = (membership.interview_summary or "").strip()
    parsed: dict[str, str] = {}

    if is_llm_configured(user, dynamic):
        field_help = "\n".join(f"{key.upper()}: <text>" for key in FIELD_ORDER)
        prompt = f"""Extract structured core knowledge from this partner's dynamic interview summary.

Interview summary:
{summary}

Output exactly these labeled sections (use the label followed by a colon). Leave a section empty if the interview did not cover it:
{field_help}

Keep each section concise (1-4 sentences). Do not invent facts not implied by the summary."""

        raw = generate_text(
            user=user,
            user_prompt=prompt,
            dynamic_context=f"Dynamic: {dynamic.name}",
            dynamic=dynamic,
            tool_id="core_knowledge",
            db=db,
        )
        parsed = _parse_fielded_response(raw or "")

    if not any(parsed.values()):
        parsed = {
            "relationship_context": summary[:600],
            "about_you": summary,
            "desires": summary,
        }

    for key in FIELD_ORDER:
        value = (parsed.get(key) or "").strip()
        if not value:
            continue
        existing = (getattr(record, key, None) or "").strip()
        if overwrite or not existing:
            setattr(record, key, value)

    record.submitted = False
    db.flush()
    return record, bool(is_llm_configured(user, dynamic))


def maybe_auto_fill_core_knowledge_from_interview(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
) -> None:
    if not membership.interview_completed:
        return
    record = get_or_create_core_knowledge(db, membership)
    if not _core_knowledge_mostly_empty(record):
        return
    try:
        populate_core_knowledge_from_interview(
            db,
            user=user,
            dynamic=dynamic,
            membership=membership,
            overwrite=False,
        )
    except HTTPException:
        pass
