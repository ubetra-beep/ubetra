from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..models import FeelingCheckIn, FeelingCheckInSelection, FeelingEmotion, Membership

WHEEL_PATH = Path(__file__).resolve().parents[2] / "data" / "feelings_wheel.json"
DESCRIPTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "feelings_descriptions.json"

_VALID_CONTEXTS = {"ad_hoc", "before_play", "after_play", "end_of_day"}


def load_wheel_json() -> dict:
    return json.loads(WHEEL_PATH.read_text(encoding="utf-8"))


def load_descriptions() -> dict[str, str]:
    if not DESCRIPTIONS_PATH.exists():
        return {}
    try:
        raw = json.loads(DESCRIPTIONS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in (raw or {}).items() if v}


def seed_feeling_emotions(db: Session) -> int:
    """Upsert the full wheel taxonomy into feeling_emotions. Returns row count."""
    data = load_wheel_json()
    descriptions = load_descriptions()
    count = 0
    core_order = 0
    for core in data.get("cores") or []:
        core_id = str(core["id"])
        existing = db.get(FeelingEmotion, core_id)
        if existing is None:
            existing = FeelingEmotion(id=core_id)
            db.add(existing)
        existing.label = str(core.get("label") or core_id)
        existing.level = 1
        existing.parent_id = None
        existing.color = str(core.get("color") or "")
        existing.description = descriptions.get(core_id) or str(core.get("description") or "")
        existing.sort_order = core_order
        count += 1
        core_order += 1
        mid_order = 0
        for mid in core.get("mids") or []:
            mid_id = str(mid["id"])
            mrow = db.get(FeelingEmotion, mid_id)
            if mrow is None:
                mrow = FeelingEmotion(id=mid_id)
                db.add(mrow)
            mrow.label = str(mid.get("label") or mid_id)
            mrow.level = 2
            mrow.parent_id = core_id
            mrow.color = existing.color
            mrow.description = descriptions.get(mid_id) or str(mid.get("description") or "")
            mrow.sort_order = mid_order
            count += 1
            mid_order += 1
            outer_order = 0
            for outer in mid.get("outers") or []:
                oid = str(outer["id"])
                orow = db.get(FeelingEmotion, oid)
                if orow is None:
                    orow = FeelingEmotion(id=oid)
                    db.add(orow)
                orow.label = str(outer.get("label") or oid)
                orow.level = 3
                orow.parent_id = mid_id
                orow.color = existing.color
                orow.description = descriptions.get(oid) or str(outer.get("description") or "")
                orow.sort_order = outer_order
                count += 1
                outer_order += 1
    db.flush()
    return count


def wheel_tree_from_db(db: Session) -> dict:
    """Build nested cores/mids/outers from feeling_emotions (same shape as JSON)."""
    if db.query(FeelingEmotion).count() == 0:
        seed_feeling_emotions(db)
        db.commit()
    # Keep descriptions fresh when descriptions file updates
    if any(not (e.description or "").strip() for e in db.query(FeelingEmotion).limit(5)):
        seed_feeling_emotions(db)
        db.commit()
    cores = (
        db.query(FeelingEmotion)
        .filter(FeelingEmotion.level == 1)
        .order_by(FeelingEmotion.sort_order)
        .all()
    )
    mids = (
        db.query(FeelingEmotion)
        .filter(FeelingEmotion.level == 2)
        .order_by(FeelingEmotion.sort_order)
        .all()
    )
    outers = (
        db.query(FeelingEmotion)
        .filter(FeelingEmotion.level == 3)
        .order_by(FeelingEmotion.sort_order)
        .all()
    )
    mids_by_parent: dict[str, list] = {}
    for m in mids:
        mids_by_parent.setdefault(m.parent_id or "", []).append(m)
    outers_by_parent: dict[str, list] = {}
    for o in outers:
        outers_by_parent.setdefault(o.parent_id or "", []).append(o)

    kind_map = {
        str(core.get("id")): str(core.get("kind") or "feeling")
        for core in (load_wheel_json().get("cores") or [])
        if core.get("id")
    }

    tree = []
    for c in cores:
        mid_list = []
        for m in mids_by_parent.get(c.id, []):
            mid_list.append(
                {
                    "id": m.id,
                    "label": m.label,
                    "description": m.description or "",
                    "outers": [
                        {
                            "id": o.id,
                            "label": o.label,
                            "description": o.description or "",
                        }
                        for o in outers_by_parent.get(m.id, [])
                    ],
                }
            )
        tree.append(
            {
                "id": c.id,
                "label": c.label,
                "color": c.color,
                "kind": kind_map.get(c.id) or "feeling",
                "description": c.description or "",
                "mids": mid_list,
            }
        )
    return {"cores": tree}


def load_wheel(db: Session | None = None) -> dict:
    if db is not None:
        return wheel_tree_from_db(db)
    return load_wheel_json()


def _path_labels(db: Session, emotion_id: str) -> list[str]:
    labels: list[str] = []
    current = db.get(FeelingEmotion, emotion_id)
    chain: list[FeelingEmotion] = []
    while current is not None:
        chain.append(current)
        current = db.get(FeelingEmotion, current.parent_id) if current.parent_id else None
    for node in reversed(chain):
        labels.append(node.label)
    return labels


def normalize_emotion_ids(
    db: Session, emotion_ids: list[str], *, allow_empty: bool = False
) -> list[FeelingEmotion]:
    if db.query(FeelingEmotion).count() == 0:
        seed_feeling_emotions(db)
    out: list[FeelingEmotion] = []
    seen: set[str] = set()
    for raw in emotion_ids or []:
        eid = str(raw or "").strip()
        if not eid or eid in seen:
            continue
        row = db.get(FeelingEmotion, eid)
        if row is None:
            continue
        seen.add(eid)
        out.append(row)
        if len(out) >= 24:
            break
    if not out and not allow_empty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one feeling on the wheel",
        )
    return out


def checkin_out(row: FeelingCheckIn, memberships: dict[str, Membership], db: Session | None = None) -> dict:
    for_m = memberships.get(row.for_membership_id)
    by_m = memberships.get(row.logged_by_membership_id)
    selections: list[dict] = []
    if row.selections:
        for sel in row.selections:
            emo = sel.emotion
            if emo is None and db is not None:
                emo = db.get(FeelingEmotion, sel.emotion_id)
            if emo is None:
                selections.append({"id": sel.emotion_id, "label": sel.emotion_id, "level": 0})
                continue
            path = _path_labels(db, emo.id) if db is not None else [emo.label]
            selections.append(
                {
                    "id": emo.id,
                    "label": emo.label,
                    "level": emo.level,
                    "path": " › ".join(path),
                    "parent_id": emo.parent_id,
                }
            )
    else:
        try:
            selections = json.loads(row.selections_json or "[]")
        except json.JSONDecodeError:
            selections = []
    return {
        "id": row.id,
        "for_membership_id": row.for_membership_id,
        "for_display_name": for_m.display_name if for_m else "Partner",
        "logged_by_membership_id": row.logged_by_membership_id,
        "logged_by_display_name": by_m.display_name if by_m else "Partner",
        "context": row.context,
        "selections": selections if isinstance(selections, list) else [],
        "horny_level": getattr(row, "horny_level", None),
        "org_entry_id": row.org_entry_id,
        "chastity_lockup_id": row.chastity_lockup_id,
        "spin_session_id": row.spin_session_id,
        "occurred_at": row.occurred_at,
        "created_at": row.created_at,
    }


def create_checkin(
    db: Session,
    *,
    dynamic_id: str,
    actor: Membership,
    for_membership_id: str,
    context: str,
    emotion_ids: list[str] | None = None,
    selections: list | None = None,
    horny_level: int | None = None,
    org_entry_id: str | None = None,
    chastity_lockup_id: str | None = None,
    spin_session_id: str | None = None,
    occurred_at: datetime | None = None,
) -> FeelingCheckIn:
    ctx = (context or "ad_hoc").strip()
    if ctx not in _VALID_CONTEXTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid context")

    level: int | None = None
    if horny_level is not None:
        try:
            level = int(horny_level)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid horny level"
            ) from exc
        if level < 0 or level > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Horny level must be between 0 and 10",
            )

    ids = list(emotion_ids or [])
    # Back-compat: accept old {core,mid,outer} payloads
    if not ids and selections:
        for item in selections:
            if not isinstance(item, dict):
                continue
            if item.get("id"):
                ids.append(str(item["id"]))
            elif item.get("outer"):
                ids.append(str(item["outer"]))
            elif item.get("mid"):
                ids.append(str(item["mid"]))
            elif item.get("core"):
                ids.append(str(item["core"]))

    emotions = normalize_emotion_ids(db, ids, allow_empty=level is not None)
    if not emotions and level is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one feeling or set a horny level",
        )
    legacy = [
        {
            "id": e.id,
            "label": e.label,
            "level": e.level,
            "path": " › ".join(_path_labels(db, e.id)),
            "core": e.id if e.level == 1 else None,
            "mid": e.id if e.level == 2 else None,
            "outer": e.id if e.level == 3 else None,
        }
        for e in emotions
    ]
    row = FeelingCheckIn(
        dynamic_id=dynamic_id,
        for_membership_id=for_membership_id,
        logged_by_membership_id=actor.id,
        context=ctx,
        selections_json=json.dumps(legacy, ensure_ascii=False),
        horny_level=level,
        org_entry_id=org_entry_id or None,
        chastity_lockup_id=chastity_lockup_id or None,
        spin_session_id=spin_session_id or None,
        occurred_at=occurred_at or datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    for emo in emotions:
        db.add(FeelingCheckInSelection(checkin_id=row.id, emotion_id=emo.id))
    db.flush()
    return row


def recent_checkins(
    db: Session,
    dynamic_id: str,
    *,
    limit: int = 30,
    since_hours: int | None = None,
) -> list[FeelingCheckIn]:
    q = (
        db.query(FeelingCheckIn)
        .options(joinedload(FeelingCheckIn.selections).joinedload(FeelingCheckInSelection.emotion))
        .filter(FeelingCheckIn.dynamic_id == dynamic_id)
    )
    if since_hours is not None:
        since = datetime.utcnow() - timedelta(hours=max(1, since_hours))
        q = q.filter(FeelingCheckIn.occurred_at >= since)
    return q.order_by(FeelingCheckIn.occurred_at.desc()).limit(limit).all()


def has_checkin_today(db: Session, dynamic_id: str, membership_id: str) -> bool:
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(FeelingCheckIn)
        .filter(
            FeelingCheckIn.dynamic_id == dynamic_id,
            FeelingCheckIn.for_membership_id == membership_id,
            FeelingCheckIn.occurred_at >= start,
        )
        .first()
        is not None
    )


def has_recent_context_checkin(
    db: Session,
    dynamic_id: str,
    membership_id: str,
    context: str,
    *,
    within_hours: int = 6,
) -> bool:
    since = datetime.utcnow() - timedelta(hours=max(1, within_hours))
    return (
        db.query(FeelingCheckIn)
        .filter(
            FeelingCheckIn.dynamic_id == dynamic_id,
            FeelingCheckIn.for_membership_id == membership_id,
            FeelingCheckIn.context == context,
            FeelingCheckIn.occurred_at >= since,
        )
        .first()
        is not None
    )


def feelings_calendar(
    db: Session,
    dynamic_id: str,
    *,
    year: int,
    month: int,
    you_membership_id: str,
) -> dict:
    """Per-day markers: feelings color + whether a play/lockup event exists."""
    memberships = (
        db.query(Membership).filter(Membership.dynamic_id == dynamic_id).order_by(Membership.created_at).all()
    )
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    days: dict[str, dict[str, dict]] = {}

    def day_bucket(day_key: str, membership_id: str) -> dict:
        day = days.setdefault(day_key, {})
        row = day.setdefault(
            membership_id,
            {"membership_id": membership_id, "feelings_logged": False, "color": None, "has_event": False},
        )
        return row

    checkins = (
        db.query(FeelingCheckIn)
        .options(
            joinedload(FeelingCheckIn.selections).joinedload(FeelingCheckInSelection.emotion)
        )
        .filter(
            FeelingCheckIn.dynamic_id == dynamic_id,
            FeelingCheckIn.occurred_at >= start,
            FeelingCheckIn.occurred_at < end,
        )
        .all()
    )
    for row in checkins:
        day_key = row.occurred_at.date().isoformat()
        bucket = day_bucket(day_key, row.for_membership_id)
        bucket["feelings_logged"] = True
        if not bucket.get("color"):
            color = None
            for sel in row.selections or []:
                emo = sel.emotion or db.get(FeelingEmotion, sel.emotion_id)
                if emo is None:
                    continue
                color = (emo.color or "").strip() or None
                cur = emo
                while cur and not color and cur.parent_id:
                    cur = db.get(FeelingEmotion, cur.parent_id)
                    if cur:
                        color = (cur.color or "").strip() or None
                if color:
                    break
            if color:
                bucket["color"] = color

    from ..models import ChastityLockup, OrgTrackingEntry

    org_rows = (
        db.query(OrgTrackingEntry)
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.occurred_at >= start,
            OrgTrackingEntry.occurred_at < end,
        )
        .all()
    )
    for row in org_rows:
        day_key = row.occurred_at.date().isoformat()
        day_bucket(day_key, row.for_membership_id)["has_event"] = True

    lockups = (
        db.query(ChastityLockup)
        .filter(ChastityLockup.dynamic_id == dynamic_id)
        .all()
    )
    for lock in lockups:
        for stamp in (lock.started_at, lock.ended_at):
            if stamp is None:
                continue
            if stamp < start or stamp >= end:
                continue
            day_key = stamp.date().isoformat()
            day_bucket(day_key, lock.for_membership_id)["has_event"] = True

    out_days = {}
    for day_key, by_member in days.items():
        members = []
        for m in memberships:
            bucket = by_member.get(m.id)
            if not bucket:
                continue
            if not bucket["feelings_logged"] and not bucket["has_event"]:
                continue
            members.append(
                {
                    "membership_id": m.id,
                    "is_you": m.id == you_membership_id,
                    "feelings_logged": bool(bucket["feelings_logged"]),
                    "color": bucket.get("color") or "#7A858C",
                    "has_event": bool(bucket["has_event"]),
                }
            )
        if members:
            # others first (left), you last (right)
            members.sort(key=lambda x: (1 if x["is_you"] else 0, x["membership_id"]))
            out_days[day_key] = {"members": members}

    return {
        "year": year,
        "month": month,
        "you_membership_id": you_membership_id,
        "partners": [
            {"id": m.id, "display_name": m.display_name, "is_you": m.id == you_membership_id}
            for m in memberships
        ],
        "days": out_days,
    }


def feelings_status(db: Session, dynamic_id: str, membership: Membership, dynamic) -> dict:
    mode = getattr(dynamic, "feelings_prompt_mode", None) or "soft"
    require_eod = bool(getattr(dynamic, "feelings_require_end_of_day", True))
    logged_today = has_checkin_today(db, dynamic_id, membership.id)
    return {
        "prompt_mode": mode if mode in {"soft", "hard"} else "soft",
        "require_end_of_day": require_eod,
        "logged_today": logged_today,
        "needs_end_of_day": require_eod and not logged_today,
        "hard_gate_active": mode == "hard",
    }
