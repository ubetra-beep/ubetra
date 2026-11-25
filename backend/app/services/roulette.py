"""Orgasm Roulette: a 90-day marble bag.

A completed task tagged project opens a marble pull.
Logged orgasms, ruins, and denials move the marbles.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import Membership, OrgEventType, OrgTrackingEntry, PartnerRole, RouletteCampaign
from ..services.tags import tags_to_list
from ..services.tracking_events import has_cheated_tag, has_full_orgasm_tag, has_ruined_orgasm_tag

log = logging.getLogger(__name__)

MARBLE_NAMES = {"R": "Ruin", "D": "Denial", "O": "Orgasm"}
RULE_KEYS = ("high_ruin", "gambler", "desperation", "hot_hand", "mercy", "veto", "task_gate")
_RNG = random.SystemRandom()


def _rules(state: dict) -> dict:
    raw = state.get("rules") if isinstance(state.get("rules"), dict) else {}
    return {key: bool(raw.get(key)) for key in RULE_KEYS}


def fresh_state(now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    stamp = now.isoformat(timespec="seconds")
    return {
        "bag": {"R": 4, "D": 2, "O": 1},
        "reserve": {"R": 8, "D": 4, "O": 2},
        "caps": {"R": 12, "D": 6, "O": 3},
        "removed": {"R": 0, "D": 0, "O": 0},
        "orgasm_drawn_since_refresh": 0,
        "soft_applied": [],
        "session": None,
        "pending": [],
        "history": [],
        "applied_entry_ids": [],
        "campaign_started_at": stamp,
        "logged_from": stamp,
        "rules": {key: False for key in RULE_KEYS},
        "grant_rules": [
            {"id": "domme-orgasm", "kind": "domme_orgasm", "tag": "", "every": 1, "effect": "pull", "progress": 0},
            {"id": "tag-project", "kind": "task_tag", "tag": "project", "every": 1, "effect": "pull", "progress": 0},
        ],
        "sessions_since_orgasm": 0,
        "first_draw_denials": 0,
        "block_sessions": 0,
        "mercy_armed": False,
    }


def _parse(value: str | None) -> datetime:
    raw = (value or "").replace("Z", "")
    if not raw:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.utcnow()


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _take(pool: dict, key: str, count: int) -> int:
    got = min(count, int(pool.get(key) or 0))
    pool[key] = int(pool.get(key) or 0) - got
    return got


def _note(state: dict, marble: str, source: str, notes: list[str], at: datetime) -> None:
    state.setdefault("history", []).append(
        {
            "at": _stamp(at),
            "marble": marble,
            "name": MARBLE_NAMES.get(marble, marble),
            "source": source,
            "notes": notes,
        }
    )
    state["history"] = state["history"][-80:]


def apply_outcome(state: dict, marble: str, *, force_continue: bool = False) -> tuple[bool, list[str]]:
    """Move one marble of this color and apply its feedback. Returns (session_ended, notes)."""
    bag = state["bag"]
    reserve = state["reserve"]
    if int(bag.get(marble) or 0) <= 0:
        return False, [f"The bag has no {MARBLE_NAMES.get(marble, marble).lower()} marble."]
    bag[marble] = int(bag[marble]) - 1
    ended = False
    if marble == "O":
        state.setdefault("removed", {"R": 0, "D": 0, "O": 0})
        state["removed"]["O"] = int(state["removed"].get("O") or 0) + 1
        notes = ["The orgasm marble left the bag."]
    else:
        reserve[marble] = int(reserve.get(marble) or 0) + 1
        notes = [f"The {MARBLE_NAMES.get(marble, marble).lower()} marble moved from the bag to the reserve."]
    if marble == "R":
        moved = _take(reserve, "D", 1)
        if moved:
            bag["D"] = int(bag.get("D") or 0) + moved
            notes.append("One denial marble came in from reserve.")
        else:
            notes.append("Denial reserve is empty, so nothing replaced it.")
    elif marble == "D":
        if int(reserve.get("O") or 0) > 0:
            orgasm = _take(reserve, "O", 1)
            bag["O"] = int(bag.get("O") or 0) + orgasm
            if _rules(state).get("high_ruin"):
                ruin = _take(reserve, "R", 1)
                bag["R"] = int(bag.get("R") or 0) + ruin
                notes.append(
                    f"Denial ended the session. High-ruin mode added {orgasm} orgasm and {ruin} ruin from reserve."
                )
            else:
                denial = _take(reserve, "D", 1)
                bag["D"] = int(bag.get("D") or 0) + denial
                notes.append(
                    f"Denial ended the session. Added {orgasm} orgasm and {denial} denial from reserve."
                )
        else:
            ruin = _take(reserve, "R", 2)
            bag["R"] = int(bag.get("R") or 0) + ruin
            notes.append(
                f"Denial ended the session. Orgasm reserve is empty, so {ruin} ruin marble"
                f"{'' if ruin == 1 else 's'} came in from reserve."
            )
        ended = not force_continue
    elif marble == "O":
        state["orgasm_drawn_since_refresh"] = int(state.get("orgasm_drawn_since_refresh") or 0) + 1
        ruin_count = 4 if _rules(state).get("hot_hand") and int(state.get("block_sessions") or 0) == 0 else 2
        ruin = _take(reserve, "R", ruin_count)
        denial = _take(reserve, "D", 1)
        bag["R"] = int(bag.get("R") or 0) + ruin
        bag["D"] = int(bag.get("D") or 0) + denial
        if ruin_count == 4:
            notes.append(f"Hot hand. The first orgasm of this block added {ruin} ruin and {denial} denial from reserve.")
        else:
            notes.append(f"Added {ruin} ruin and {denial} denial from reserve.")
    return ended, notes


def _add_refill(state: dict, marble: str) -> list[str]:
    """Add the marbles an outcome puts back, without removing a pulled marble."""
    bag = state["bag"]
    reserve = state["reserve"]
    if marble == "R":
        moved = _take(reserve, "D", 1)
        bag["D"] = int(bag.get("D") or 0) + moved
        if moved:
            return ["One denial marble came in from reserve."]
        return ["Denial reserve is empty, so no denial marble was added."]
    ruin = _take(reserve, "R", 2)
    denial = _take(reserve, "D", 1)
    bag["R"] = int(bag.get("R") or 0) + ruin
    bag["D"] = int(bag.get("D") or 0) + denial
    return [f"Added {ruin} ruin and {denial} denial from reserve."]


def _remove_orgasm_marbles(state: dict, count: int) -> list[str]:
    bag = state["bag"]
    reserve = state["reserve"]
    have = int(bag.get("O") or 0)
    taken = min(count, have)
    bag["O"] = have - taken
    reserve["O"] = int(reserve.get("O") or 0) + taken
    notes = [f"Moved {taken} orgasm marble{'' if taken == 1 else 's'} from the bag to the reserve."]
    short = count - taken
    if short:
        notes.append(f"{short} orgasm marble{'' if short == 1 else 's'} could not be moved because the bag was short.")
    return notes


def apply_grant(state: dict, marble: str, at: datetime) -> list[str]:
    label = "orgasm" if marble == "O" else "ruin"
    notes = [f"Granted {label}. No marble was pulled."] + _add_refill(state, marble)
    _note(state, marble, "grant", notes, at)
    return notes


def apply_stolen(state: dict, marble: str, at: datetime) -> list[str]:
    extra = 3 if marble == "O" else 2
    label = "orgasm" if marble == "O" else "ruin"
    notes = [f"Stolen {label} after a denial."] + _add_refill(state, marble) + _remove_orgasm_marbles(state, extra)
    _note(state, marble, "stolen", notes, at)
    return notes


def apply_infraction(state: dict, at: datetime, *, source: str = "infraction") -> list[str]:
    bag = state["bag"]
    reserve = state["reserve"]
    cleared = int(bag.get("O") or 0)
    if cleared:
        bag["O"] = 0
        reserve["O"] = int(reserve.get("O") or 0) + cleared
    got = _take(reserve, "D", 2)
    created = 0
    if got < 2:
        created = 2 - got
        state["caps"]["D"] = int(state["caps"].get("D") or 0) + 2
    bag["D"] = int(bag.get("D") or 0) + got + created
    notes = [
        f"Cheating penalty: {cleared} orgasm marble{'' if cleared == 1 else 's'} moved from the bag to the reserve.",
    ]
    if created:
        notes.append(f"Denial reserve was short, so the denial cap grew by 2 and {got + created} denial marbles entered the bag.")
    else:
        notes.append("Two denial marbles moved from reserve into the bag.")
    _note(state, "D", source, notes, at)
    return notes


def _soft_refresh(state: dict, mark: int, at: datetime) -> None:
    applied = set(state.get("soft_applied") or [])
    if mark in applied:
        return
    notes = [f"Day {mark} refresh."]
    held = int(state.get("removed", {}).get("O") or 0)
    if held > 0:
        state["removed"]["O"] = held - 1
        state["reserve"]["O"] = int(state["reserve"].get("O") or 0) + 1
        state["orgasm_drawn_since_refresh"] = 0
        state["block_sessions"] = 0
        notes.append("One drawn orgasm marble returned to the reserve.")
    elif int(state.get("orgasm_drawn_since_refresh") or 0) > 0:
        state["orgasm_drawn_since_refresh"] = 0
        notes.append("A drawn orgasm marble is already in the reserve.")
    else:
        notes.append("No orgasm marble had been drawn, so the reserve stayed as it was.")
    state["block_sessions"] = 0
    state["soft_applied"] = sorted(applied | {mark})
    _note(state, "", "refresh", notes, at)


def _hard_reset(state: dict, at: datetime) -> None:
    history = list(state.get("history") or [])
    fresh = fresh_state(at)
    fresh["history"] = history
    state.clear()
    state.update(fresh)
    _note(
        state,
        "",
        "reset",
        ["Day 90. The bag is back to 4 ruin, 2 denial, and 1 orgasm. The reserve is 8 ruin, 4 denial, and 2 orgasm."],
        at,
    )


def _on_day(start: datetime, day_number: int) -> datetime:
    target = start.date() + timedelta(days=day_number - 1)
    return datetime(target.year, target.month, target.day)


def advance(state: dict, now: datetime, logs: list[dict] | None = None) -> None:
    """Apply 30/60 refreshes, 90-day resets, and any logged pulls in time order."""
    logs = logs or []
    for _ in range(12):
        start = _parse(state.get("campaign_started_at"))
        reset_at = _on_day(start, 90)
        window_end = now if now < reset_at else reset_at
        events: list[tuple[datetime, int, str, object]] = []
        for mark in (30, 60):
            when = _on_day(start, mark)
            if when <= window_end and mark not in set(state.get("soft_applied") or []):
                events.append((when, 0, "soft", mark))
        logged_from = _parse(state.get("logged_from") or state.get("campaign_started_at"))
        applied = set(state.get("applied_entry_ids") or [])
        for item in logs:
            at = item["at"]
            if item["id"] in applied:
                continue
            if at < logged_from or at < start or at >= reset_at or at > now:
                continue
            events.append((at, 1, "log", item))
        events.sort(key=lambda row: (row[0], row[1]))
        for when, _, kind, payload in events:
            if kind == "soft":
                _soft_refresh(state, int(payload), when)
            else:
                _apply_logged(state, payload)
        if now >= reset_at:
            _hard_reset(state, reset_at)
            continue
        break


def _apply_logged(state: dict, item: dict) -> None:
    state.setdefault("applied_entry_ids", []).append(item["id"])
    marble = item.get("marble")
    at = item["at"]
    if marble == "grant-O":
        apply_grant(state, "O", at)
        return
    if marble == "grant-R":
        apply_grant(state, "R", at)
        return
    if marble == "stolen-O":
        apply_stolen(state, "O", at)
        return
    if marble == "stolen-R":
        apply_stolen(state, "R", at)
        return
    if marble == "cheat":
        apply_infraction(state, at, source="log")
        return
    if marble not in ("R", "D", "O"):
        return
    if int(state["bag"].get(marble) or 0) <= 0:
        _note(
            state,
            marble,
            "log",
            [f"A {MARBLE_NAMES[marble].lower()} was logged, but that marble was not in the bag."],
            at,
        )
        return
    ended, notes = apply_outcome(state, marble)
    state["session"] = {
        "open": False,
        "ended": True,
        "bonus": False,
        "penalty_left": 0,
        "penalty": False,
        "reason": "Orgasm log",
        "draws": [{"marble": marble, "notes": notes, "at": _stamp(at)}],
    }
    _note(state, marble, "log", notes + (["Session ended."] if ended else []), at)


def pick_marble(state: dict, rng: random.Random | None = None) -> str:
    rng = rng or _RNG
    bag = state["bag"]
    total = sum(int(bag.get(key) or 0) for key in ("R", "D", "O"))
    if total <= 0:
        raise ValueError("The bag is empty")
    roll = rng.randrange(total)
    for key in ("R", "D", "O"):
        roll -= int(bag.get(key) or 0)
        if roll < 0:
            return key
    return "R"


def _session(state: dict) -> dict:
    session = state.get("session") or {}
    return session if isinstance(session, dict) else {}


def _bag_total(state: dict) -> int:
    return sum(int(state["bag"].get(key) or 0) for key in ("R", "D", "O"))


def _finish_session(state: dict) -> None:
    session = _session(state)
    if session.get("scored"):
        return
    session["scored"] = True
    draws = list(session.get("draws") or [])
    kept = [draw for draw in draws if not draw.get("vetoed")]
    if any(draw.get("marble") == "O" for draw in kept):
        state["sessions_since_orgasm"] = 0
    else:
        state["sessions_since_orgasm"] = int(state.get("sessions_since_orgasm") or 0) + 1
    if len(draws) == 1 and draws[0].get("marble") == "D":
        state["first_draw_denials"] = int(state.get("first_draw_denials") or 0) + 1
    else:
        state["first_draw_denials"] = 0
    if _rules(state).get("mercy") and int(state.get("first_draw_denials") or 0) >= 5:
        state["mercy_armed"] = True
    state["block_sessions"] = int(state.get("block_sessions") or 0) + 1


def can_draw(state: dict) -> bool:
    if _bag_total(state) <= 0:
        return False
    session = _session(state)
    if session.get("mercy_pair"):
        return False
    if session.get("open") and int(session.get("penalty_left") or 0) > 0:
        return True
    if session.get("open") and not session.get("ended"):
        return bool(session.get("bonus"))
    if session.get("open"):
        return False
    return bool(state.get("pending"))


def draw_marble(state: dict, now: datetime, rng: random.Random | None = None) -> dict:
    if not can_draw(state):
        raise ValueError("No pull is open. Complete a task tagged project.")
    session = _session(state)
    penalty = bool(session.get("open") and int(session.get("penalty_left") or 0) > 0)
    continuing = bool(session.get("open") and not session.get("ended"))
    if not session.get("open") or session.get("ended"):
        pending = list(state.get("pending") or [])
        if not pending:
            raise ValueError("No pull is open. Complete a task tagged project.")
        reason = (pending.pop(0) or {}).get("reason") or "Project task"
        state["pending"] = pending
        session = {
            "open": True,
            "ended": False,
            "bonus": False,
            "penalty_left": 0,
            "penalty": False,
            "reason": reason,
            "draws": [],
        }
        state["session"] = session
        if (
            _rules(state).get("mercy")
            and state.get("mercy_armed")
            and not penalty
            and _bag_total(state) >= 2
        ):
            state["mercy_armed"] = False
            first = pick_marble(state, rng)
            state["bag"][first] = int(state["bag"].get(first) or 0) - 1
            second = pick_marble(state, rng)
            state["bag"][first] = int(state["bag"].get(first) or 0) + 1
            session["mercy_pair"] = [first, second]
            session["was_mercy"] = True
            session["bonus"] = False
            notes = [
                f"Mercy draw. {MARBLE_NAMES[first]} and {MARBLE_NAMES[second]} are up. The keyholder chooses."
            ]
            _note(state, "", "mercy", notes, now)
            return {"marble": "", "name": "Mercy", "notes": notes, "ended": False}
    if continuing and session.get("gambler_open"):
        session["doubled"] = True
        session["gambler_open"] = False
    marble = pick_marble(state, rng)
    ended, notes = apply_outcome(state, marble, force_continue=penalty)
    session.setdefault("draws", []).append({"marble": marble, "notes": notes, "at": _stamp(now)})
    if penalty:
        session["penalty_left"] = max(0, int(session.get("penalty_left") or 0) - 1)
        if session["penalty_left"] <= 0:
            ended = True
        else:
            ended = False
            session["bonus"] = True
    else:
        session["bonus"] = marble in ("R", "O") and not ended
    if _rules(state).get("gambler") and marble == "R" and not penalty and not session.get("doubled"):
        session["gambler_open"] = True
    if ended:
        session["open"] = False
        session["ended"] = True
        session["bonus"] = False
        session["gambler_open"] = False
        notes = notes + ["Session ended."]
        _finish_session(state)
    elif session.get("bonus"):
        notes = notes + ["Swipe again for a bonus pull, or slide to end the session."]
    _note(state, marble, "penalty" if penalty else "swipe", notes, now)
    return {"marble": marble, "name": MARBLE_NAMES[marble], "notes": notes, "ended": ended}


def end_session(state: dict, now: datetime) -> None:
    session = _session(state)
    if not session.get("open") or session.get("ended"):
        raise ValueError("No session is open")
    if int(session.get("penalty_left") or 0) > 0:
        raise ValueError("Finish the three penalty pulls first")
    if not session.get("draws"):
        raise ValueError("Pull a marble before ending the session")
    session["open"] = False
    session["ended"] = True
    session["bonus"] = False
    session["gambler_open"] = False
    _finish_session(state)
    _note(state, "", "end", ["Session ended."], now)


def start_penalty(state: dict, now: datetime) -> None:
    state["session"] = {
        "open": True,
        "ended": False,
        "bonus": True,
        "penalty_left": 3,
        "penalty": True,
        "reason": "Penalty session",
        "draws": [],
    }
    _note(
        state,
        "",
        "penalty",
        ["Penalty session. Pull three times. Carry out each ruin or denial before the next pull."],
        now,
    )


def queue_pull(state: dict, reason: str, now: datetime) -> None:
    pending = list(state.get("pending") or [])
    pending.append({"id": _stamp(now) + reason, "reason": reason, "at": _stamp(now)})
    state["pending"] = pending[-12:]


def probabilities(bag: dict) -> dict:
    total = sum(int(bag.get(key) or 0) for key in ("R", "D", "O")) or 1
    return {key: round(int(bag.get(key) or 0) / total * 100, 1) for key in ("R", "D", "O")}


def _campaign_dates(state: dict) -> dict:
    start = _parse(state.get("campaign_started_at"))
    return {
        "started_on": start.date().isoformat(),
        "soft_on": _on_day(start, 30).date().isoformat(),
        "second_soft_on": _on_day(start, 60).date().isoformat(),
        "reset_on": _on_day(start, 90).date().isoformat(),
    }


def campaign_day(state: dict, now: datetime) -> int:
    start = _parse(state.get("campaign_started_at"))
    return max(1, (now.date() - start.date()).days + 1)


def _loads(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    base = fresh_state()
    if not isinstance(data, dict) or "bag" not in data:
        return base
    base.update(data)
    for key in ("bag", "reserve", "caps", "removed"):
        merged = fresh_state()[key]
        merged.update(base.get(key) or {})
        base[key] = {name: int(merged.get(name) or 0) for name in ("R", "D", "O")}
    return base


def _dump(state: dict) -> str:
    return json.dumps(state)


def _row(db: Session, dynamic_id: str, *, create: bool) -> RouletteCampaign | None:
    row = db.query(RouletteCampaign).filter(RouletteCampaign.dynamic_id == dynamic_id).one_or_none()
    if row is None and create:
        row = RouletteCampaign(dynamic_id=dynamic_id, enabled=False, mode="virtual", state_json="{}")
        db.add(row)
        db.flush()
    return row


def _logged_events(db: Session, dynamic_id: str, state: dict) -> list[dict]:
    start = _parse(state.get("logged_from") or state.get("campaign_started_at"))
    subs = [
        row.id
        for row in db.query(Membership.id)
        .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.submissive)
        .all()
    ]
    if not subs:
        return []
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id.in_(subs),
            OrgTrackingEntry.occurred_at >= start,
        )
        .order_by(OrgTrackingEntry.occurred_at.asc())
        .all()
    )
    events = []
    for entry in entries:
        marble = _classify(entry)
        if not marble:
            continue
        events.append({"id": entry.id, "at": entry.occurred_at, "marble": marble})
    return events


def _decision_kind(blobs: list[str]) -> str | None:
    tags = {" ".join(str(raw).lower().replace("-", " ").replace("_", " ").split()) for raw in blobs if str(raw).strip()}

    def has(*names: str) -> bool:
        return any(name in tags or any(tag.startswith(name + " ") for tag in tags) for name in names)

    if has("stolen orgasm", "orgasm stolen"):
        return "stolen-O"
    if has("stolen ruin", "ruin stolen"):
        return "stolen-R"
    if has("granted orgasm"):
        return "grant-O"
    if has("granted ruin"):
        return "grant-R"
    return None


def _classify(entry: OrgTrackingEntry) -> str | None:
    blobs: list[str] = []
    blobs.extend(tags_to_list(entry.tags))
    for orgasm in entry.orgasms or []:
        blobs.extend(tags_to_list(orgasm.tags))
    kind = entry.event_type.value if isinstance(entry.event_type, OrgEventType) else str(entry.event_type)
    lowered = " ".join(blobs).lower()
    decision = _decision_kind(blobs)
    if decision:
        return decision
    if has_cheated_tag(blobs):
        return "cheat"
    if "denied" in lowered or "denial" in lowered:
        if not has_full_orgasm_tag(blobs) and not has_ruined_orgasm_tag(blobs):
            return "D"
    if kind in (OrgEventType.no_orgasm.value, "no_orgasm", "scene"):
        return None
    if has_full_orgasm_tag(blobs):
        return "O"
    if has_ruined_orgasm_tag(blobs):
        return "R"
    if kind in (OrgEventType.orgasm.value, OrgEventType.both.value, "orgasm", "both"):
        return "O"
    return None


def _prepare(db: Session, row: RouletteCampaign, now: datetime) -> dict:
    state = _loads(row.state_json)
    if row.enabled:
        if not state.get("log_tie_from"):
            # Keep the bag that was already played. New logs move marbles from here on.
            state["log_tie_from"] = _stamp(now)
            state["logged_from"] = state["log_tie_from"]
        logs = _logged_events(db, row.dynamic_id, state)
        advance(state, now, logs)
        row.state_json = _dump(state)
        row.updated_at = now
    return state


def public_state(db: Session, dynamic_id: str, *, you_are_dominant: bool, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None:
        state = fresh_state(now)
        enabled = False
        mode = "virtual"
    else:
        state = _prepare(db, row, now)
        enabled = bool(row.enabled)
        mode = row.mode if row.mode in ("virtual", "logged") else "virtual"
        db.commit()
    return _public(state, enabled=enabled, mode=mode, you_are_dominant=you_are_dominant, now=now, db=db, dynamic_id=dynamic_id)


def _log_pull_tally(db: Session, dynamic_id: str, start: datetime) -> dict:
    """Count ruin, denial, and orgasm logs for the sub since the game started."""
    tally = {"R": 0, "D": 0, "O": 0, "total": 0}
    subs = [
        row.id
        for row in db.query(Membership.id)
        .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.submissive)
        .all()
    ]
    if not subs:
        return tally
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.for_membership_id.in_(subs),
            OrgTrackingEntry.occurred_at >= start,
        )
        .all()
    )
    alias = {"grant-O": "O", "stolen-O": "O", "grant-R": "R", "stolen-R": "R"}
    for entry in entries:
        marble = alias.get(_classify(entry) or "", "")
        if marble not in ("R", "D", "O"):
            continue
        tally[marble] += 1
        tally["total"] += 1
    return tally


def _public(
    state: dict,
    *,
    enabled: bool,
    mode: str,
    you_are_dominant: bool,
    now: datetime,
    db: Session | None = None,
    dynamic_id: str = "",
) -> dict:
    bag = state["bag"]
    day = campaign_day(state, now)
    if day < 30:
        next_soft = 30
    elif day < 60:
        next_soft = 60
    else:
        next_soft = None
    session = _session(state)
    pending = list(state.get("pending") or [])
    probs = probabilities(bag)
    marbles = []
    for key in ("R", "D", "O"):
        marbles.extend([key] * int(bag.get(key) or 0))
    return {
        "enabled": enabled,
        "mode": mode,
        "you_are_dominant": you_are_dominant,
        "campaign_day": day,
        "started_on": _parse(state.get("campaign_started_at")).date().isoformat(),
        "dates": _campaign_dates(state),
        "start_request": state.get("start_request") or None,
        "bag_request": state.get("bag_request") or None,
        "next_soft_day": next_soft,
        "days_until_soft": None if next_soft is None else max(0, next_soft - day),
        "days_until_reset": max(0, 90 - day),
        "bag": bag,
        "reserve": state["reserve"],
        "caps": state["caps"],
        "probabilities": probs,
        "bag_total": sum(int(bag.get(key) or 0) for key in ("R", "D", "O")),
        "removed": state.get("removed") or {"R": 0, "D": 0, "O": 0},
        "chart": _marble_chart(state, probs),
        "grant_rules": _grant_rules(state),
        "marbles": marbles,
        "pending_count": len(pending),
        "pending_reason": (pending[0].get("reason") if pending else "") or "",
        "can_draw": bool(enabled and can_draw(state)),
        "can_end": bool(
            enabled
            and session.get("open")
            and not session.get("ended")
            and session.get("draws")
            and int(session.get("penalty_left") or 0) == 0
        ),
        "rules": _rules(state),
        "sessions_since_orgasm": int(state.get("sessions_since_orgasm") or 0),
        "first_draw_denials": int(state.get("first_draw_denials") or 0),
        "mercy_armed": bool(state.get("mercy_armed")),
        "desperation_request": bool(state.get("desperation_request")),
        "can_desperation": bool(
            enabled
            and _rules(state).get("desperation")
            and sum(int(bag.get(key) or 0) for key in ("R", "D", "O")) >= 12
            and int(state.get("sessions_since_orgasm") or 0) >= 15
            and not (session.get("open") and not session.get("ended"))
        ),
        "can_veto": bool(
            enabled
            and _rules(state).get("veto")
            and session.get("open")
            and not session.get("ended")
            and (session.get("draws") or [])
            and (session.get("draws") or [])[-1].get("marble") == "O"
            and not (session.get("draws") or [])[-1].get("vetoed")
        ),
        "can_gate": bool(
            enabled
            and _rules(state).get("task_gate")
            and session.get("open")
            and not session.get("ended")
            and (session.get("draws") or [])
            and (session.get("draws") or [])[-1].get("marble") == "O"
            and not (session.get("draws") or [])[-1].get("vetoed")
        ),
        "session": {
            "open": bool(session.get("open")),
            "ended": bool(session.get("ended")),
            "bonus": bool(session.get("bonus")),
            "penalty_left": int(session.get("penalty_left") or 0),
            "penalty": bool(session.get("penalty")),
            "gambler_open": bool(session.get("gambler_open")),
            "mercy_pair": list(session.get("mercy_pair") or []),
            "reason": session.get("reason") or "",
            "draws": session.get("draws") or [],
        },
        "history": list(reversed(state.get("history") or []))[:12],
        "pull_tally": _log_pull_tally(db, dynamic_id, _parse(state.get("campaign_started_at")))
        if db is not None and dynamic_id
        else {"R": 0, "D": 0, "O": 0, "total": 0},
    }


def _parse_start(value: str | None, now: datetime) -> datetime | None:
    raw = (value or "").strip()[:10]
    if not raw:
        return None
    try:
        day = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Start date must be YYYY-MM-DD") from exc
    if day.date() > now.date():
        raise ValueError("Start date cannot be in the future")
    return day


def _shift_start(state: dict, start: datetime, mode: str) -> bool:
    """Rebuild the bag when the start date moves, then let logs since that day replay."""
    del mode
    new = start.date().isoformat()
    old = (state.get("campaign_started_at") or "")[:10]
    if old == new:
        return False
    history = list(state.get("history") or [])
    fresh = fresh_state(start)
    fresh["history"] = history
    state.clear()
    state.update(fresh)
    _note(
        state,
        "",
        "refresh",
        [f"Start date set to {new}. The bag starts at 4 ruin, 2 denial, and 1 orgasm, then orgasm logs since that day are applied."],
        start,
    )
    return True


def update_settings(
    db: Session,
    dynamic_id: str,
    *,
    enabled: bool,
    mode: str,
    you_are_dominant: bool,
    started_on: str = "",
) -> dict:
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=True)
    assert row is not None
    if not you_are_dominant:
        # The sub runs the bag. Start date and mode stay put.
        started_on = ""
        mode = row.mode or "virtual"
    mode = mode if mode in ("virtual", "logged") else "virtual"
    raw = (row.state_json or "").strip()
    has_campaign = "campaign_started_at" in raw
    start = _parse_start(started_on, now)
    if has_campaign:
        state = _loads(raw)
    else:
        state = fresh_state(start or now)
    shifted = False
    if has_campaign and start is not None:
        shifted = _shift_start(state, start, mode)
    elif not has_campaign and start is not None:
        state = fresh_state(start)
    request = state.get("start_request") or {}
    if start is not None and request.get("started_on") == start.date().isoformat():
        state.pop("start_request", None)
    if enabled and mode == "logged" and row.mode != "logged" and start is None and has_campaign:
        state["logged_from"] = _stamp(now)
    row.enabled = bool(enabled)
    row.mode = mode
    row.state_json = _dump(state)
    row.updated_at = now
    if row.enabled:
        logs = _logged_events(db, dynamic_id, state) if mode == "logged" or shifted else []
        advance(state, now, logs)
        row.state_json = _dump(state)
    db.commit()
    return _public(state, enabled=bool(enabled), mode=mode, you_are_dominant=you_are_dominant, now=now, db=db, dynamic_id=dynamic_id)


def _mutate(db: Session, dynamic_id: str, you_are_dominant: bool, action) -> dict:
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        raise ValueError("Orgasm Roulette is off")
    state = _prepare(db, row, now)
    action(state, now)
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=True, mode=row.mode, you_are_dominant=you_are_dominant, now=now, db=db, dynamic_id=dynamic_id)


def perform_draw(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    def action(state, now):
        if not can_draw(state):
            raise ValueError("No pull is open. Complete a task tagged project.")
        draw_marble(state, now)

    return _mutate(db, dynamic_id, you_are_dominant, action)


def perform_end(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    return _mutate(db, dynamic_id, you_are_dominant, end_session)


def set_rules(db: Session, dynamic_id: str, *, rules: dict, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("Only the keyholder can change the rules")
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=True)
    assert row is not None
    raw = (row.state_json or "").strip()
    state = _loads(raw) if "campaign_started_at" in raw else fresh_state(now)
    current = _rules(state)
    for key in RULE_KEYS:
        if key in (rules or {}):
            current[key] = bool(rules[key])
    state["rules"] = current
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=bool(row.enabled), mode=row.mode or "virtual", you_are_dominant=True, now=now, db=db, dynamic_id=dynamic_id)


def perform_desperation(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    def action(state, now):
        if not _rules(state).get("desperation"):
            raise ValueError("The desperation gambit is off")
        if _bag_total(state) < 12 or int(state.get("sessions_since_orgasm") or 0) < 15:
            raise ValueError("The bag needs 12 marbles and 15 sessions without an orgasm")
        if not you_are_dominant:
            state["desperation_request"] = True
            _note(state, "", "mercy", ["The sub asked for the desperation gambit."], now)
            return
        taken = min(3, int(state["bag"].get("D") or 0))
        state["bag"]["D"] = int(state["bag"].get("D") or 0) - taken
        state.setdefault("removed", {"R": 0, "D": 0, "O": 0})
        state["removed"]["D"] = int(state["removed"].get("D") or 0) + taken
        state.pop("desperation_request", None)
        _note(
            state,
            "D",
            "home",
            [f"Desperation gambit. Two ruined orgasms are owed. {taken} denial marble{'' if taken == 1 else 's'} left the bag for good."],
            now,
        )

    return _mutate(db, dynamic_id, you_are_dominant, action)


def choose_mercy(db: Session, dynamic_id: str, *, marble: str, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("The keyholder chooses the mercy marble")
    picked = marble if marble in ("R", "D", "O") else ""

    def action(state, now):
        session = _session(state)
        pair = list(session.get("mercy_pair") or [])
        if picked not in pair:
            raise ValueError("Choose one of the two mercy marbles")
        session["mercy_pair"] = []
        ended, notes = apply_outcome(state, picked)
        session.setdefault("draws", []).append({"marble": picked, "notes": notes, "at": _stamp(now)})
        session["bonus"] = picked in ("R", "O") and not ended
        if ended:
            session["open"] = False
            session["ended"] = True
            session["bonus"] = False
            notes = notes + ["Session ended."]
            _finish_session(state)
        _note(state, picked, "mercy", notes, now)

    return _mutate(db, dynamic_id, you_are_dominant, action)


def veto_orgasm(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("Only the keyholder can veto an orgasm")

    def action(state, now):
        if not _rules(state).get("veto"):
            raise ValueError("Orgasm veto is off")
        session = _session(state)
        draws = list(session.get("draws") or [])
        if not draws or draws[-1].get("marble") != "O" or draws[-1].get("vetoed"):
            raise ValueError("There is no orgasm to veto")
        draws[-1]["vetoed"] = True
        session["draws"] = draws
        removed = state.setdefault("removed", {"R": 0, "D": 0, "O": 0})
        if int(removed.get("O") or 0) > 0:
            removed["O"] = int(removed["O"]) - 1
        state["bag"]["O"] = int(state["bag"].get("O") or 0) + 1
        if int(state.get("orgasm_drawn_since_refresh") or 0) > 0:
            state["orgasm_drawn_since_refresh"] = int(state["orgasm_drawn_since_refresh"]) - 1
        session["bonus"] = False
        _note(state, "O", "home", ["Orgasm vetoed. The orgasm marble went back into the bag."], now)

    return _mutate(db, dynamic_id, you_are_dominant, action)


def gate_orgasm(db: Session, dynamic_id: str, *, challenge: str, passed: bool, downgrade: str, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("Only the keyholder can gate an orgasm")

    def action(state, now):
        if not _rules(state).get("task_gate"):
            raise ValueError("Task-gated orgasms are off")
        session = _session(state)
        draws = list(session.get("draws") or [])
        if not draws or draws[-1].get("marble") != "O" or draws[-1].get("vetoed"):
            raise ValueError("There is no orgasm to gate")
        label = (challenge or "challenge").strip()[:80] or "challenge"
        if passed:
            _note(state, "O", "home", [f"Challenge passed: {label}. The orgasm stands."], now)
            return
        kind = "denial" if downgrade == "denial" else "ruin"
        draws[-1]["vetoed"] = True
        session["draws"] = draws
        notes = [f"Challenge failed: {label}. The orgasm is downgraded to a {kind}."]
        if kind == "denial":
            got = _take(state["reserve"], "D", 2)
            created = 0
            if got < 2:
                created = 2 - got
                state["caps"]["D"] = int(state["caps"].get("D") or 0) + 2
            state["bag"]["D"] = int(state["bag"].get("D") or 0) + got + created
            notes.append(f"{got + created} denial marbles entered the bag.")
            session["open"] = False
            session["ended"] = True
            session["bonus"] = False
            _finish_session(state)
        _note(state, "D" if kind == "denial" else "R", "home", notes, now)

    return _mutate(db, dynamic_id, you_are_dominant, action)


def _clamp_count(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(24, number))


def _counts(raw: dict | None) -> dict:
    return {key: _clamp_count((raw or {}).get(key)) for key in ("R", "D", "O")}


def _pool_supply(state: dict) -> dict:
    removed = state.get("removed") or {}
    return {
        key: int(state["bag"].get(key) or 0)
        + int(state["reserve"].get(key) or 0)
        + int(removed.get(key) or 0)
        for key in ("R", "D", "O")
    }


def _link_pools(state: dict, bag: dict, reserve: dict, focus: str) -> None:
    """Bag and reserve are the same marbles. Moving one side changes the other."""
    supply = _pool_supply(state)
    removed = state.get("removed") or {}
    for key in ("R", "D", "O"):
        room = max(0, supply[key] - int(removed.get(key) or 0))
        if focus == "reserve":
            hold = min(room, _clamp_count((reserve or {}).get(key)))
            state["reserve"][key] = hold
            state["bag"][key] = room - hold
        else:
            hold = min(room, _clamp_count((bag or {}).get(key)))
            state["bag"][key] = hold
            state["reserve"][key] = room - hold


def _apply_manual_bag(state: dict, bag: dict, reserve: dict, now: datetime, focus: str = "bag") -> None:
    """Hand-set counts. Bag and reserve edits move marbles; a reserve edit can also add some."""
    if focus == "reserve-set":
        state.setdefault("caps", {"R": 12, "D": 6, "O": 3})
        removed = state.get("removed") or {}
        for key in ("R", "D", "O"):
            state["bag"][key] = int(state["bag"].get(key) or 0)
            state["reserve"][key] = _clamp_count((reserve or {}).get(key))
            held = state["bag"][key] + state["reserve"][key] + int(removed.get(key) or 0)
            if held > int(state["caps"].get(key) or 0):
                state["caps"][key] = held
        note = "Reserve counts updated."
    else:
        _link_pools(state, bag, reserve, focus)
        note = "Bag and reserve updated. They share the same marbles."
    state["logged_from"] = _stamp(now + timedelta(seconds=1))
    state["log_tie_from"] = state.get("log_tie_from") or state["logged_from"]
    state.pop("bag_request", None)
    _note(state, "", "home", [note], now)


def set_bag(
    db: Session,
    dynamic_id: str,
    *,
    bag: dict,
    reserve: dict,
    you_are_dominant: bool,
    focus: str = "bag",
) -> dict:
    """Either partner sets the bag. The sub's numbers apply immediately."""
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None:
        raise ValueError("Orgasm Roulette is off")
    state = _loads(row.state_json)
    chosen = "reserve-set" if focus == "reserve-set" else "reserve" if focus == "reserve" else "bag"
    _apply_manual_bag(state, bag, reserve, now, chosen)
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=bool(row.enabled), mode=row.mode, you_are_dominant=you_are_dominant, now=now, db=db, dynamic_id=dynamic_id)


def approve_bag(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("Only the keyholder can approve a bag change")
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        raise ValueError("Orgasm Roulette is off")
    state = _loads(row.state_json)
    request = state.get("bag_request") or {}
    if not request.get("bag"):
        raise ValueError("No bag change is waiting")
    _apply_manual_bag(state, request.get("bag") or {}, request.get("reserve") or {}, now)
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=True, mode=row.mode, you_are_dominant=True, now=now, db=db, dynamic_id=dynamic_id)


def deny_bag(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("Only the keyholder can decline a bag change")
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        raise ValueError("Orgasm Roulette is off")
    state = _loads(row.state_json)
    if not state.get("bag_request"):
        raise ValueError("No bag change is waiting")
    state.pop("bag_request", None)
    _note(state, "", "home", ["Bag change was declined."], now)
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=True, mode=row.mode, you_are_dominant=True, now=now, db=db, dynamic_id=dynamic_id)


def log_decision(
    db: Session,
    dynamic_id: str,
    *,
    kind: str,
    stolen: bool,
    actor_membership_id: str,
    you_are_dominant: bool,
) -> dict:
    """Log a granted or stolen orgasm/ruin and add marbles without pulling one."""
    if not you_are_dominant:
        raise ValueError("Only the keyholder can log a grant or a stolen orgasm")
    marble = "O" if kind == "orgasm" else "R" if kind == "ruin" else ""
    if not marble:
        raise ValueError("Choose orgasm or ruin")
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        raise ValueError("Orgasm Roulette is off")
    sub = (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.submissive)
        .order_by(Membership.id.asc())
        .first()
    )
    if sub is None:
        raise ValueError("Add a sub before logging this")
    from ..models import OrgTrackingOrgasm
    from ..services.tags import tags_to_string

    label = "Stolen" if stolen else "Granted"
    word = "Orgasm" if marble == "O" else "Ruin"
    tag = f"{label} {word}"
    entry = OrgTrackingEntry(
        dynamic_id=dynamic_id,
        logged_by_membership_id=actor_membership_id,
        for_membership_id=sub.id,
        event_type=OrgEventType.orgasm,
        notes=f"{label} {word.lower()}. Logged for the marble bag.",
        tags=tags_to_string([tag]),
        occurred_at=now,
    )
    entry.orgasms.append(OrgTrackingOrgasm(tags=tags_to_string([tag]), position=0))
    db.add(entry)
    db.flush()
    state = _loads(row.state_json)
    code = ("stolen" if stolen else "grant") + "-" + marble
    _apply_logged(state, {"id": entry.id, "at": now, "marble": code})
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=True, mode=row.mode, you_are_dominant=True, now=now, db=db, dynamic_id=dynamic_id)


def request_start(db: Session, dynamic_id: str, *, started_on: str, you_are_dominant: bool) -> dict:
    if you_are_dominant:
        raise ValueError("Set the start date directly. A request is for the sub.")
    now = datetime.utcnow()
    start = _parse_start(started_on, now)
    if start is None:
        raise ValueError("Pick a start date")
    row = _row(db, dynamic_id, create=True)
    assert row is not None
    raw = (row.state_json or "").strip()
    state = _loads(raw) if "campaign_started_at" in raw else fresh_state(now)
    state["start_request"] = {"started_on": start.date().isoformat(), "at": _stamp(now)}
    row.state_json = _dump(state)
    row.updated_at = now
    if row.enabled:
        logs = _logged_events(db, dynamic_id, state) if row.mode == "logged" else []
        advance(state, now, logs)
        row.state_json = _dump(state)
    db.commit()
    return _public(state, enabled=bool(row.enabled), mode=row.mode or "virtual", you_are_dominant=False, now=now, db=db, dynamic_id=dynamic_id)


def dismiss_start_request(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    if not you_are_dominant:
        raise ValueError("Only the keyholder can answer a start-date request")
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None:
        raise ValueError("Orgasm Roulette has not been started")
    state = _loads(row.state_json)
    state.pop("start_request", None)
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=bool(row.enabled), mode=row.mode or "virtual", you_are_dominant=True, now=now, db=db, dynamic_id=dynamic_id)


def perform_infraction(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        raise ValueError("Orgasm Roulette is off")
    state = _prepare(db, row, now)
    apply_infraction(state, now)
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=True, mode=row.mode, you_are_dominant=you_are_dominant, now=now, db=db, dynamic_id=dynamic_id)


def perform_penalty(db: Session, dynamic_id: str, *, you_are_dominant: bool) -> dict:
    return _mutate(db, dynamic_id, you_are_dominant, start_penalty)


def _is_sensual(tags: str) -> bool:
    parts = [part.strip().lower() for part in (tags or "").replace(";", ",").split(",")]
    return any(part == "sensual" or part.startswith("sensual ") for part in parts if part)


def _queue_pull(db: Session, dynamic_id: str, reason: str, count: int = 1) -> None:
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        return
    state = _loads(row.state_json)
    now = datetime.utcnow()
    for _ in range(max(0, count)):
        queue_pull(state, reason, now)
    row.state_json = _dump(state)
    row.updated_at = now


def _grant_rules(state: dict) -> list[dict]:
    if "grant_rules" not in state:
        raw = fresh_state().get("grant_rules") or []
    else:
        raw = state.get("grant_rules")
    if not isinstance(raw, list):
        raw = []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") if item.get("kind") in ("domme_orgasm", "task_tag") else ""
        if not kind:
            continue
        effect = item.get("effect") if item.get("effect") in ("pull", "add_orgasm") else "pull"
        try:
            every = int(item.get("every") or 1)
        except (TypeError, ValueError):
            every = 1
        try:
            progress = int(item.get("progress") or 0)
        except (TypeError, ValueError):
            progress = 0
        cleaned.append(
            {
                "id": str(item.get("id") or "")[:40] or secrets_id(),
                "kind": kind,
                "tag": str(item.get("tag") or "").strip().lower()[:40],
                "every": max(1, min(50, every)),
                "effect": effect,
                "progress": max(0, progress),
            }
        )
    return cleaned


def secrets_id() -> str:
    return "g" + random.SystemRandom().randbelow(10**8).__str__().zfill(8)


def _marble_chart(state: dict, probs: dict) -> list[dict]:
    bag = state.get("bag") or {}
    reserve = state.get("reserve") or {}
    removed = state.get("removed") or {}
    pulled = {key: 0 for key in ("R", "D", "O")}
    for row in state.get("history") or []:
        key = row.get("marble")
        if key in pulled and row.get("source") in ("swipe", "log", "penalty"):
            pulled[key] += 1
    pull_total = sum(pulled.values())
    chart = []
    for key in ("R", "D", "O"):
        total = int(bag.get(key) or 0) + int(reserve.get(key) or 0)
        chart.append(
            {
                "key": key,
                "name": MARBLE_NAMES[key],
                "total": total,
                "bag": int(bag.get(key) or 0),
                "reserve": int(reserve.get(key) or 0),
                "removed": int(removed.get(key) or 0),
                "pulled": pulled[key],
                "pulled_pct": round(pulled[key] / pull_total * 100, 1) if pull_total else 0,
                "next_pct": probs.get(key) or 0,
            }
        )
    return chart


def _tag_parts(tags: str) -> set[str]:
    return {part.strip().lower() for part in (tags or "").replace(";", ",").split(",") if part.strip()}


def _rule_matches_tags(rule: dict, tags: set[str]) -> bool:
    if rule.get("kind") != "task_tag":
        return False
    want = (rule.get("tag") or "").strip().lower()
    if not want:
        return True
    aliases = {want}
    if want in {"project", "projects"}:
        aliases.update({"project", "projects"})
    return any(tag in aliases or tag.startswith(want + " ") for tag in tags)


def _apply_grant_effect(state: dict, rule: dict, now: datetime) -> None:
    if rule.get("effect") == "add_orgasm":
        moved = _take(state.setdefault("reserve", {"R": 0, "D": 0, "O": 0}), "O", 1)
        if moved:
            state.setdefault("bag", {"R": 0, "D": 0, "O": 0})
            state["bag"]["O"] = int(state["bag"].get("O") or 0) + moved
            notes = ["An orgasm marble moved from the reserve into the bag."]
        else:
            notes = ["The orgasm reserve is empty, so no marble was added."]
        _note(state, "O", "home", notes, now)
        return
    if rule.get("kind") == "domme_orgasm":
        reason = "Orgasm for the keyholder"
    else:
        tag = rule.get("tag") or "task"
        reason = f"Task tagged {tag}"
    queue_pull(state, reason, now)


def _advance_grant_rules(state: dict, rules: list[dict], now: datetime) -> None:
    stored = _grant_rules(state)
    by_id = {rule["id"]: rule for rule in stored}
    for incoming in rules:
        rule = by_id.get(incoming.get("id"))
        if rule is None:
            continue
        rule["progress"] = int(rule.get("progress") or 0) + 1
        every = max(1, int(rule.get("every") or 1))
        if rule["progress"] >= every:
            rule["progress"] = 0
            _apply_grant_effect(state, rule, now)
    state["grant_rules"] = stored


def note_goal_orgasm(db: Session, dynamic_id: str, count: int) -> None:
    """Goal gifts no longer open a pull on their own. Grant rules do that."""
    del db, dynamic_id, count


def note_tracking_entry(db: Session, dynamic_id: str, target: Membership, entry: OrgTrackingEntry) -> None:
    """Sub logs move the bag. Orgasms for the keyholder count toward a pull rule."""
    from ..services.tracking_events import counts_as_full_orgasm, entry_orgasm_tag_lists, is_orgasm_event

    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        return
    state = _loads(row.state_json)
    now = entry.occurred_at or datetime.utcnow()
    changed = False
    if target.role == PartnerRole.dominant and is_orgasm_event(entry.event_type):
        full_count = sum(1 for tags in entry_orgasm_tag_lists(entry) if counts_as_full_orgasm(tags))
        rules = [rule for rule in _grant_rules(state) if rule.get("kind") == "domme_orgasm"]
        if full_count and rules:
            for _ in range(full_count):
                _advance_grant_rules(state, rules, now)
            changed = True
    else:
        marble = _classify(entry)
        if marble in ("O", "R", "D", "cheat", "grant-O", "grant-R", "stolen-O", "stolen-R"):
            if entry.id not in set(state.get("applied_entry_ids") or []):
                _apply_logged(state, {"id": entry.id, "at": entry.occurred_at, "marble": marble})
                changed = True
    if not changed:
        return
    row.state_json = _dump(state)
    row.updated_at = datetime.utcnow()


def note_project_task(db: Session, dynamic_id: str, task) -> None:
    row = _row(db, dynamic_id, create=False)
    if row is None or not row.enabled:
        return
    tags = _tag_parts(getattr(task, "tags", "") or "")
    state = _loads(row.state_json)
    matched = [rule for rule in _grant_rules(state) if _rule_matches_tags(rule, tags)]
    if not matched:
        return
    _advance_grant_rules(state, matched, datetime.utcnow())
    row.state_json = _dump(state)
    row.updated_at = datetime.utcnow()


def note_sensual_task(db: Session, dynamic_id: str, task) -> None:
    note_project_task(db, dynamic_id, task)


def set_grant_rules(db: Session, dynamic_id: str, rules: list[dict], *, you_are_dominant: bool) -> dict:
    """Either partner sets what earns a pull or adds an orgasm marble."""
    now = datetime.utcnow()
    row = _row(db, dynamic_id, create=True)
    assert row is not None
    state = _loads(row.state_json) if (row.state_json or "").strip() else fresh_state(now)
    previous = {rule["id"]: int(rule.get("progress") or 0) for rule in _grant_rules(state)}
    cleaned = []
    for item in rules or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") if item.get("kind") in ("domme_orgasm", "task_tag") else ""
        if not kind:
            continue
        effect = item.get("effect") if item.get("effect") in ("pull", "add_orgasm") else "pull"
        try:
            every = int(item.get("every") or 1)
        except (TypeError, ValueError):
            every = 1
        rule_id = str(item.get("id") or "").strip()[:40] or secrets_id()
        cleaned.append(
            {
                "id": rule_id,
                "kind": kind,
                "tag": "" if kind == "domme_orgasm" else str(item.get("tag") or "").strip().lower()[:40],
                "every": max(1, min(50, every)),
                "effect": effect,
                "progress": previous.get(rule_id, 0),
            }
        )
    state["grant_rules"] = cleaned
    row.state_json = _dump(state)
    row.updated_at = now
    db.commit()
    return _public(state, enabled=bool(row.enabled), mode=row.mode or "virtual", you_are_dominant=you_are_dominant, now=now, db=db, dynamic_id=dynamic_id)
