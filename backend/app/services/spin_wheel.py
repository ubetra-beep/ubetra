from __future__ import annotations

import json
import math
import re
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole, User
from .llm import generate_text
from .menu_summaries import _days_since_full_o

SPIN_PRESETS = [
    {
        "id": "wait_days",
        "title": "Days to wait longer",
        "description": (
            "Dice value = extra days before release/orgasm. "
            "Tell him the number. On fail: lock back up and serve the wait — do not re-spin."
        ),
        "value_label": "Days",
        "uses_dice": True,
        "share_with_sub": True,
        "fail_behavior": "lock_up",
        "once_only": False,
    },
    {
        "id": "wait_weeks",
        "title": "Weeks to wait longer",
        "description": (
            "Dice value = extra weeks before release/orgasm. "
            "Tell him the number. On fail: lock back up and serve the wait — do not re-spin."
        ),
        "value_label": "Weeks",
        "uses_dice": True,
        "share_with_sub": True,
        "fail_behavior": "lock_up",
        "once_only": False,
    },
    {
        "id": "ruins_secret",
        "title": "Ruins before earned",
        "description": (
            "Dice value = ruins required (secret). Tell him only that more ruins are required. "
            "Do one ruin at a time (in front of you or self-ruin), then ask if he can handle another. "
            "If not: lock up and finish the remaining ruins later. When the secret count is met, "
            "ask full orgasm now or later — after a full orgasm, run post-orgasm tasks and "
            "longer/shorter next-wait."
        ),
        "value_label": "Ruins (secret)",
        "uses_dice": True,
        "share_with_sub": False,
        "fail_behavior": "ruins_session",
        "once_only": False,
    },
    {
        "id": "edges_shared",
        "title": "Edges before orgasm",
        "description": (
            "Dice value = edges (shared so he can beg you to stop). "
            "If he ruins early or can't finish: no orgasm — lock up and try the edges again "
            "later, or re-spin for a different outcome."
        ),
        "value_label": "Edges (shared)",
        "uses_dice": True,
        "share_with_sub": True,
        "fail_behavior": "retry_or_respin",
        "once_only": False,
    },
    {
        "id": "dom_orgasms_locked",
        "title": "Orgasms for keyholder while locked",
        "description": (
            "Dice value = orgasms he provides to the keyholder while he stays locked. "
            "If interrupted: lock him back up and finish the remaining count later."
        ),
        "value_label": "Orgasms for keyholder",
        "uses_dice": True,
        "share_with_sub": True,
        "fail_behavior": "continue_later",
        "once_only": False,
    },
    {
        "id": "full_orgasm",
        "title": "Full Orgasm!",
        "description": (
            "He earns a full orgasm now. Then pick post-orgasm tasks, and optionally spin "
            "the next wait period (longer or shorter than this wait)."
        ),
        "value_label": "",
        "uses_dice": False,
        "share_with_sub": True,
        "fail_behavior": "none",
        "once_only": False,
    },
    {
        "id": "multiplier",
        "title": "Multiplier (+20%)",
        "description": (
            "Can land once per game. Adds 20% to the current dice value (rounded up), "
            "then the wheel must be spun again without this option."
        ),
        "value_label": "",
        "uses_dice": False,
        "share_with_sub": True,
        "fail_behavior": "none",
        "once_only": True,
    },
]

POST_ORGASM_PRESETS = [
    {
        "id": "massage",
        "title": "Massage",
        "description": (
            "Give the keyholder a focused massage — shoulders, back, feet, or wherever she directs. "
            "Stay attentive; ask what feels good and keep going until she says stop."
        ),
        "kind": "service",
    },
    {
        "id": "facesitting",
        "title": "Facesitting",
        "description": (
            "Serve with oral / facesitting aftercare play. Stay still and useful under her; "
            "follow her pace and don’t rush your own recovery."
        ),
        "kind": "service",
    },
    {
        "id": "domestic",
        "title": "Domestic tasks",
        "description": (
            "Chores, tidy-up, or household service — dishes, laundry, tidy the play space, "
            "fetch water or snacks. Do it promptly and carefully."
        ),
        "kind": "service",
    },
    {
        "id": "cuddle",
        "title": "Cuddle / aftercare",
        "description": (
            "Quiet closeness: blankets, water, check-in, soft touch. Be present and calm; "
            "let her set how much talk vs silence."
        ),
        "kind": "service",
    },
    {
        "id": "foot_service",
        "title": "Foot service",
        "description": (
            "Foot rub, worship, or polish as negotiated. Keep your focus on her comfort and "
            "follow any rules she sets for kissing, pressure, or duration."
        ),
        "kind": "service",
    },
]

POST_ORGASM_ADDONS = [
    {
        "id": "addon_torture",
        "title": "Post-orgasm torture",
        "description": (
            "Extra stimulation after he’s already come — light teasing, overstim, or edging "
            "torture within negotiated limits. Pair with a service or run as its own beat."
        ),
        "kind": "addon",
    },
    {
        "id": "addon_piv_riding",
        "title": "PIV riding",
        "description": (
            "She rides him (PIV) as part of or after his orgasm service window. "
            "He stays useful for her pleasure; condom/protection rules as negotiated."
        ),
        "kind": "addon",
    },
    {
        "id": "addon_butt_plug",
        "title": "Butt plug while performing services",
        "description": (
            "Insert a butt plug (sized as negotiated) before or during the assigned service(s). "
            "He keeps it in while he serves unless she says otherwise."
        ),
        "kind": "addon",
    },
]


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


def partner_names(memberships: list[Membership]) -> tuple[str, str]:
    dominant = next((m for m in memberships if m.role == PartnerRole.dominant), None)
    submissive = next((m for m in memberships if m.role == PartnerRole.submissive), None)
    dom_name = (dominant.display_name if dominant else "the keyholder").strip() or "the keyholder"
    sub_name = (submissive.display_name if submissive else "the submissive").strip() or "the submissive"
    return dom_name, sub_name


def submissive_membership(memberships: list[Membership]) -> Membership | None:
    return next((m for m in memberships if m.role == PartnerRole.submissive), None)


def days_since_last_orgasm(db: Session, dynamic_id: str, memberships: list[Membership]) -> int | None:
    sub = submissive_membership(memberships)
    if sub is None:
        return None
    return _days_since_full_o(db, dynamic_id, sub)


def build_spin_presets(*, dominant_name: str) -> list[dict]:
    items = []
    for preset in SPIN_PRESETS:
        item = dict(preset)
        if item["id"] == "dom_orgasms_locked":
            item["title"] = f"Additional orgasms for {dominant_name} while locked"
            item["description"] = (
                f"Dice value = orgasms he provides to {dominant_name} while locked. "
                "On fail: re-spin for a new assignment."
            )
            item["value_label"] = f"Orgasms for {dominant_name}"
        item["source"] = "preset"
        items.append(item)
    return items


def generate_spin_extra_ideas(
    *,
    user: User,
    dynamic_context: str,
    dynamic: Dynamic | None,
    faces: int,
    dominant_name: str,
    submissive_name: str,
) -> list[dict]:
    prompt = f"""The keyholder is configuring a "Spin the Wheel" denial/release game.
Context: {submissive_name} has almost earned release or a full orgasm.
Dice faces available: {faces}. After options are chosen, a dice roll supplies the numeral
value assigned to whichever wheel item lands (except Full Orgasm! and Multiplier).

Propose 2–3 EXTRA wheel outcomes (not duplicates of: wait days, wait weeks, secret ruins,
shared edges, orgasms for {dominant_name} while locked, Full Orgasm!, Multiplier +20%).

Return ONLY valid JSON:
{{
  "ideas": [
    {{
      "id": "custom_snake_short_id",
      "title": "Short title",
      "description": "What the dice number means, and fail behavior.",
      "value_label": "Unit name for the dice value",
      "uses_dice": true,
      "share_with_sub": true,
      "fail_behavior": "respin"
    }}
  ]
}}

fail_behavior must be one of: respin, lock_up, respin_or_retry_edges, none
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=dynamic_context,
        dynamic=dynamic,
    )
    data = _extract_json(raw)
    ideas = data.get("ideas") if isinstance(data, dict) else data
    if not isinstance(ideas, list):
        return []

    extras: list[dict] = []
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        raw_id = re.sub(r"[^a-z0-9_]+", "_", str(item.get("id") or title).lower()).strip("_")
        fail = str(item.get("fail_behavior") or "respin").strip()
        if fail not in {"respin", "lock_up", "respin_or_retry_edges", "none"}:
            fail = "respin"
        extras.append(
            {
                "id": f"llm_{raw_id[:40]}",
                "title": title[:80],
                "description": str(item.get("description") or "").strip()[:320],
                "value_label": str(item.get("value_label") or "Count").strip()[:60],
                "uses_dice": bool(item.get("uses_dice", True)),
                "share_with_sub": bool(item.get("share_with_sub", True)),
                "fail_behavior": fail,
                "once_only": False,
                "source": "llm",
            }
        )
        if len(extras) >= 3:
            break
    return extras


def generate_post_orgasm_tasks(
    *,
    user: User,
    dynamic_context: str,
    dynamic: Dynamic | None,
    dominant_name: str,
    submissive_name: str,
) -> list[dict]:
    prompt = f"""{submissive_name} just earned a Full Orgasm in a keyholder game.
Propose 3–5 post-orgasm service tasks {dominant_name} can assign (massage, facesitting,
domestic chores, aftercare, etc.). Keep them concrete and consensual.

Return ONLY valid JSON:
{{
  "tasks": [
    {{"id": "short_id", "title": "Short title", "description": "One sentence."}}
  ]
}}
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=dynamic_context,
        dynamic=dynamic,
    )
    data = _extract_json(raw)
    tasks = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(tasks, list):
        tasks = []

    out: list[dict] = [dict(item, source="preset") for item in POST_ORGASM_PRESETS]
    out.extend(dict(item, source="addon") for item in POST_ORGASM_ADDONS)
    seen = {t["id"] for t in out}
    for item in tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        raw_id = re.sub(r"[^a-z0-9_]+", "_", str(item.get("id") or title).lower()).strip("_")
        task_id = f"llm_{raw_id[:40]}"
        if task_id in seen:
            continue
        seen.add(task_id)
        out.append(
            {
                "id": task_id,
                "title": title[:80],
                "description": str(item.get("description") or "").strip()[:240],
                "source": "llm",
                "kind": "service",
            }
        )
        if len([t for t in out if t.get("kind") != "addon"]) >= 10:
            break
    return out


def next_wait_day_choices(base_days: int, direction: str) -> list[int]:
    base = max(1, int(base_days))
    if direction == "longer":
        lo = base + 1
        hi = max(lo, int(math.ceil(base * 1.2)))
    elif direction == "shorter":
        lo = max(1, int(math.floor(base * 0.5)))
        hi = max(lo, int(math.floor(base * 0.9)))
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="direction must be longer or shorter")

    if hi == lo:
        return [lo]

    span = hi - lo
    # Up to 8 discrete choices across the range.
    steps = min(8, span + 1)
    if steps == 1:
        return [lo]
    values = []
    for i in range(steps):
        values.append(lo + int(round(i * span / (steps - 1))))
    # unique sorted
    return sorted(set(values))


def apply_multiplier(dice_value: int) -> int:
    return max(1, int(math.ceil(dice_value * 1.2)))


def full_orgasms_since(
    db: Session,
    dynamic_id: str,
    memberships: list[Membership],
    *,
    since: datetime,
) -> list[dict]:
    """Submissive full-orgasm tracking entries after `since` (while a spin game is in play)."""
    from ..models import OrgTrackingEntry
    from .tracking_events import has_full_orgasm_tag, is_orgasm_event, orgasm_count

    sub = submissive_membership(memberships)
    if sub is None:
        return []

    entries = (
        db.query(OrgTrackingEntry)
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id == sub.id,
            OrgTrackingEntry.occurred_at >= since,
        )
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .limit(50)
        .all()
    )
    hits: list[dict] = []
    for entry in entries:
        if not is_orgasm_event(entry.event_type):
            continue
        tags: list[str] = []
        for row in entry.orgasms or []:
            tags.extend([t.strip() for t in (row.tags or "").split(",") if t.strip()])
        lowered = [t.lower() for t in tags]
        ruined_only = bool(lowered) and all("ruin" in t for t in lowered)
        if ruined_only:
            continue
        # Full orgasm tag, or an orgasm event that isn't tagged as ruin-only.
        if tags and not has_full_orgasm_tag(tags) and any("ruin" in t for t in lowered):
            # Mixed tags with ruin but no full → skip
            if not has_full_orgasm_tag(tags):
                continue
        hits.append(
            {
                "id": entry.id,
                "occurred_at": entry.occurred_at.isoformat() + "Z",
                "orgasm_count": orgasm_count(entry),
                "tags": tags,
            }
        )
    return hits
