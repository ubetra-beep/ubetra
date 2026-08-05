from __future__ import annotations

import json
import re

from fastapi import HTTPException, status

from ..models import Dynamic, User
from .llm import generate_text

EFFORT_LABELS = {
    "low": "Low — under 5 minutes, almost no prep",
    "med": "Medium — about 10–15 minutes",
    "high": "High — 20+ minutes, or meaningful prep / setup",
}

LEAN_LABELS = {
    "sub": "Lean on the submissive's desires more",
    "dom": "Lean on the dominant's / keyholder's desires more",
    "equal": "Balance both partners' desires equally",
}


def _extract_json(raw: str) -> dict | list:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
        if not match:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI returned an unreadable response. Try again.",
            )
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI returned invalid JSON. Try again.",
            ) from exc


def generate_playtime_subjects(
    *,
    user: User,
    dynamic_context: str,
    effort: str,
    lean: str,
    dynamic: Dynamic | None = None,
    exclude_subjects: list[str] | None = None,
    note: str = "",
    db=None,
) -> list[dict[str, str]]:
    effort_label = EFFORT_LABELS.get(effort, EFFORT_LABELS["med"])
    lean_label = LEAN_LABELS.get(lean, LEAN_LABELS["equal"])
    exclude = [s.strip() for s in (exclude_subjects or []) if s and s.strip()]
    exclude_block = ""
    if exclude:
        exclude_block = (
            "Do NOT reuse these subject titles (already rejected or used):\n"
            + "\n".join(f"- {title}" for title in exclude[:12])
            + "\n"
        )
    note_block = f"User direction: {note.strip()}\n" if note.strip() else ""

    prompt = f"""You are helping a dominant/keyholder pick a quick playtime scene subject.

Effort level: {effort_label}
Desire lean: {lean_label}
{exclude_block}{note_block}
Based on the dynamic context, invent exactly THREE distinct scene subjects that fit this effort and lean.
Subjects should be short category-style titles (1–3 words), e.g. "Bondage", "Intimacy", "Toys", "Denial", "Sensory".
Each needs a one-sentence blurb explaining why it fits this couple and effort level.

Return ONLY valid JSON (no markdown):
{{
  "subjects": [
    {{"title": "Bondage", "blurb": "Why it fits in one sentence."}},
    {{"title": "Intimacy", "blurb": "Why it fits in one sentence."}},
    {{"title": "Toys", "blurb": "Why it fits in one sentence."}}
  ]
}}
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=dynamic_context,
        dynamic=dynamic,
        tool_id="playtime",
        db=db,
    )
    data = _extract_json(raw)
    items = data.get("subjects") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI did not return scene subjects. Try again.",
        )

    subjects: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        blurb = str(item.get("blurb") or item.get("description") or "").strip()
        if not title:
            continue
        subjects.append({"title": title[:40], "blurb": blurb[:200]})
        if len(subjects) == 3:
            break

    if len(subjects) < 3:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned fewer than 3 subjects. Try again.",
        )
    return subjects


def generate_playtime_scene(
    *,
    user: User,
    dynamic_context: str,
    effort: str,
    lean: str,
    subject: str,
    dynamic: Dynamic | None = None,
    avoid_summary: str = "",
    note: str = "",
    db=None,
) -> dict[str, str]:
    effort_label = EFFORT_LABELS.get(effort, EFFORT_LABELS["med"])
    lean_label = LEAN_LABELS.get(lean, LEAN_LABELS["equal"])
    avoid_block = ""
    if avoid_summary.strip():
        avoid_block = (
            "The user rejected a previous scene. Do NOT repeat it. Previous scene summary:\n"
            f"{avoid_summary.strip()[:800]}\n"
        )
    note_block = f"User direction for the new scene: {note.strip()}\n" if note.strip() else ""

    prompt = f"""Create ONE concrete playtime scene for this couple.

Subject: {subject.strip()}
Effort level: {effort_label}
Desire lean: {lean_label}
{avoid_block}{note_block}
Constraints:
- Match the effort budget strictly (especially Low = under ~5 minutes).
- Stay inside negotiated interests and boundaries from context.
- Be specific and actionable for a dominant/keyholder to run.
- Do not invent app features, device control, or third parties.

Return ONLY valid JSON (no markdown):
{{
  "title": "Short scene title",
  "summary": "1-2 sentence pitch",
  "body": "Full scene plan: setup, beats, and closing. Use short paragraphs or numbered steps. Aim for 120-220 words."
}}
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=dynamic_context,
        dynamic=dynamic,
        tool_id="playtime",
        db=db,
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI did not return a scene. Try again.",
        )

    title = str(data.get("title") or subject).strip() or subject.strip()
    summary = str(data.get("summary") or "").strip()
    body = str(data.get("body") or data.get("scene") or "").strip()
    if not body:
        # Fallback if model dumped prose
        body = raw.strip()
    return {
        "title": title[:120],
        "summary": summary[:280],
        "body": body[:4000],
        "subject": subject.strip()[:40],
    }
