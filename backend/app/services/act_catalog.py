from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole, User
from .context import build_dynamic_context
from .llm import generate_text, is_llm_configured

_CATEGORY_BLOCK_RE = re.compile(
    r"^CATEGORY:\s*(.+?)\s*\nDESCRIPTION:\s*(.+?)\s*\nEXAMPLES:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def parse_act_catalog(raw: str | None) -> list[dict[str, str | list[str]]]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str | list[str]]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        examples = item.get("example_acts") or item.get("examples") or []
        if not isinstance(examples, list):
            examples = []
        out.append(
            {
                "id": str(item.get("id") or title.lower().replace(" ", "_")[:40]),
                "title": title,
                "description": str(item.get("description") or "").strip(),
                "example_acts": [str(x).strip() for x in examples if str(x).strip()][:5],
            }
        )
    return out


def serialize_act_catalog(categories: list[dict]) -> str:
    return json.dumps(categories, ensure_ascii=False)


def _both_interviews_complete(db: Session, dynamic_id: str) -> bool:
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    if len(memberships) < 2:
        return False
    return all(m.interview_completed and m.interview_summary.strip() for m in memberships)


def generate_act_catalog(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
) -> list[dict[str, str | list[str]]]:
    if not is_llm_configured(user, dynamic):
        raise ValueError("Configure an AI API key before generating act types.")

    context = build_dynamic_context(db, dynamic)
    prompt = """Based on BOTH partners' dynamic interviews in the context below, define 4–6 act-of-submission categories tailored to this couple.

Each category should reflect what the dominant and submissive said they are willing to do — especially practical service, rituals, and intimate submission they described or implied.

Include domestic-service style options where interviews support them (e.g. meal prep, tidying, laundry, errands, morning/evening routines) but only if they fit this dynamic.

Return ONLY valid JSON — an array of objects:
[
  {
    "id": "snake_case_id",
    "title": "Short category name",
    "description": "One sentence on what fits this couple",
    "example_acts": ["example 1", "example 2", "example 3"]
  }
]

No markdown fences, no commentary outside the JSON array."""

    raw = generate_text(user=user, user_prompt=prompt, dynamic_context=context, dynamic=dynamic, tool_id="acts", db=db)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("AI returned invalid act categories. Try again.") from exc
    categories = parse_act_catalog(json.dumps(data))
    if len(categories) < 2:
        raise ValueError("AI returned too few act categories. Try again.")
    dynamic.act_categories = serialize_act_catalog(categories)
    db.commit()
    return categories


def maybe_generate_act_catalog(db: Session, *, user: User, dynamic: Dynamic) -> None:
    if dynamic.act_categories and parse_act_catalog(dynamic.act_categories):
        return
    if not _both_interviews_complete(db, dynamic.id):
        return
    if not is_llm_configured(user, dynamic):
        return
    try:
        generate_act_catalog(db, user=user, dynamic=dynamic)
    except Exception:
        return


def find_act_category(dynamic: Dynamic, act_type_id: str) -> dict | None:
    for cat in parse_act_catalog(dynamic.act_categories):
        if cat["id"] == act_type_id:
            return cat
    return None
