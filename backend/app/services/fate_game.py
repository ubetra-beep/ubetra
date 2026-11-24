"""Six hidden fates. Each card is an orgasm tag, an edge count, or denial, plus a follow-up task."""

from __future__ import annotations

import json
import random
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, FateGame, User
from .llm import generate_text

ORGASM_TYPES = [
    "Full Orgasm",
    "Ruined Orgasm",
    "Milking",
    "Partial-Milking",
    "Dildo",
    "Handjob",
    "PiV",
    "Finger",
    "Oral",
    "Vibrator",
    "Masturbation",
    "Anal",
    "Prostate",
]
TASK_STYLES = ("domestic", "sexual", "sensual")
KINDS = ("orgasm", "edges", "denial")

_FALLBACKS = [
    {"kind": "orgasm", "orgasm_type": "Ruined Orgasm", "task_style": "domestic", "task": "Straighten the bedroom and bring a glass of water."},
    {"kind": "edges", "edge_count": 10, "task_style": "sensual", "task": "Give a ten-minute massage with no rush toward orgasm."},
    {"kind": "denial", "task_style": "domestic", "task": "Cook a simple meal and serve it."},
    {"kind": "orgasm", "orgasm_type": "Oral", "task_style": "sexual", "task": "Ask permission, then give oral until told to stop."},
    {"kind": "edges", "edge_count": 5, "task_style": "sexual", "task": "Stay close and describe what you want, without touching unless told."},
    {"kind": "denial", "task_style": "sensual", "task": "Kneel, breathe slowly, and hold still for five minutes."},
]


def _extract_json(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _card_from(item: dict) -> dict | None:
    kind = str(item.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    style = str(item.get("task_style") or "").strip().lower()
    if style not in TASK_STYLES:
        style = "domestic"
    task = str(item.get("task") or "").strip()
    if len(task) < 3:
        return None
    card: dict = {"kind": kind, "task_style": style, "task": task[:400]}
    if kind == "orgasm":
        orgasm = str(item.get("orgasm_type") or "").strip()
        if orgasm not in ORGASM_TYPES:
            orgasm = "Ruined Orgasm"
        card["orgasm_type"] = orgasm
    elif kind == "edges":
        try:
            count = int(item.get("edge_count") or 0)
        except (TypeError, ValueError):
            count = 8
        card["edge_count"] = max(1, min(40, count))
    return card


def _fill_cards(parsed) -> list[dict]:
    raw_items = []
    if isinstance(parsed, dict):
        raw_items = parsed.get("fates") or parsed.get("cards") or []
    elif isinstance(parsed, list):
        raw_items = parsed
    cards = []
    for item in raw_items:
        if isinstance(item, dict):
            card = _card_from(item)
            if card:
                cards.append(card)
        if len(cards) == 6:
            break
    index = 0
    while len(cards) < 6:
        cards.append(dict(_FALLBACKS[index % len(_FALLBACKS)]))
        index += 1
    random.shuffle(cards)
    for number, card in enumerate(cards, start=1):
        card["n"] = number
    return cards


def _public_card(card: dict) -> dict:
    kind = card["kind"]
    if kind == "orgasm":
        label = card.get("orgasm_type") or "Orgasm"
        detail = "Orgasm"
    elif kind == "edges":
        label = f"{card.get('edge_count') or 1} edges"
        detail = "Edges"
    else:
        label = "Denial"
        detail = "Denial"
    return {
        "n": card["n"],
        "kind": kind,
        "label": label,
        "detail": detail,
        "task_style": card["task_style"],
        "task": card["task"],
    }


def load_game(db: Session, dynamic_id: str) -> FateGame | None:
    return db.query(FateGame).filter(FateGame.dynamic_id == dynamic_id).one_or_none()


def public_state(game: FateGame | None) -> dict:
    if game is None:
        return {"ready": False, "numbers": [1, 2, 3, 4, 5, 6], "revealed": []}
    cards = json.loads(game.cards_json or "[]")
    opened = set(json.loads(game.revealed_json or "[]"))
    revealed = [_public_card(card) for card in cards if card.get("n") in opened]
    revealed.sort(key=lambda row: row["n"])
    return {"ready": True, "numbers": [1, 2, 3, 4, 5, 6], "revealed": revealed}


def deal_fates(db: Session, *, user: User, dynamic: Dynamic) -> dict:
    prompt = f"""Create exactly 6 different fates for the submissive in a consensual adult game.

Each fate is one kind:
- orgasm: set orgasm_type to exactly one of: {", ".join(ORGASM_TYPES)}
- edges: set edge_count to an integer from 3 to 20
- denial: no orgasm

Use a mix. Do not make all six the same kind.

Every fate also has a task performed AFTER the fate.
task_style must be domestic, sexual, or sensual.
task is one concrete sentence.

Return ONLY JSON:
{{
  "fates": [
    {{"kind": "orgasm", "orgasm_type": "Ruined Orgasm", "task_style": "domestic", "task": "Make the bed."}},
    {{"kind": "edges", "edge_count": 8, "task_style": "sensual", "task": "Give a slow massage."}},
    {{"kind": "denial", "task_style": "sexual", "task": "Describe what you want, then stop."}}
  ]
}}
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context="Consensual adult couple. Game cards only. Do not use real names.",
        dynamic=dynamic,
        tool_id="spin_wheel",
        db=db,
    )
    cards = _fill_cards(_extract_json(raw))
    game = load_game(db, dynamic.id)
    if game is None:
        game = FateGame(dynamic_id=dynamic.id)
        db.add(game)
    game.cards_json = json.dumps(cards)
    game.revealed_json = "[]"
    db.commit()
    return public_state(game)


def reveal_fate(db: Session, *, dynamic_id: str, number: int) -> dict:
    if number < 1 or number > 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick a number from 1 to 6.")
    game = load_game(db, dynamic_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal the fates first.")
    opened = json.loads(game.revealed_json or "[]")
    if number not in opened:
        opened.append(number)
        game.revealed_json = json.dumps(opened)
        db.commit()
    state = public_state(game)
    card = next((row for row in state["revealed"] if row["n"] == number), None)
    state["opened"] = card
    return state
