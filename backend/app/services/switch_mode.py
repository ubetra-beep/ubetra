"""Temporary switch overlay. Membership.role never changes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, OrgEventType, OrgTrackingEntry, PartnerRole, SwitchSession
from .tags import tags_to_list, tags_to_string

OPEN_STATUSES = ("drafting", "pending_approval", "active")
OFFER_KINDS = ("timed", "session", "until_goal")
GOAL_KINDS = ("until_goal", "goal_gift")
SCENE_KINDS = ("scene_gift",)
GOAL_METRICS = {
    "denials": "Denied or no-orgasm logs",
    "scenes": "Scene logs",
    "spanking": "Spanking logs",
}
LOG_KINDS = ("denial", "scene", "spanking")


def _partners(db: Session, dynamic_id: str) -> tuple[Membership | None, Membership | None]:
    rows = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    dom = next((m for m in rows if m.role == PartnerRole.dominant), None)
    sub = next((m for m in rows if m.role == PartnerRole.submissive), None)
    return dom, sub


def _open(db: Session, dynamic_id: str) -> SwitchSession | None:
    return (
        db.query(SwitchSession)
        .filter(
            SwitchSession.dynamic_id == dynamic_id,
            SwitchSession.status.in_(OPEN_STATUSES),
        )
        .order_by(SwitchSession.created_at.desc())
        .first()
    )


def _load_json(raw: str | None) -> dict:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_goal(raw) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Describe the goal")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Give the goal a title")
    metric = str(raw.get("metric") or "").strip()
    if metric not in GOAL_METRICS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick denials, scenes, or spanking")
    try:
        target = int(raw.get("target") or 0)
    except (TypeError, ValueError):
        target = 0
    if target < 1 or target > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target must be from 1 to 100")
    detail = str(raw.get("detail") or "").strip()[:500]
    return {"title": title[:80], "detail": detail, "metric": metric, "target": target}


def _clean_scene(raw) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Describe the scene")
    title = str(raw.get("title") or "").strip()
    body = str(raw.get("body") or "").strip()
    if not title or not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A scene needs a title and a body")
    summary = str(raw.get("summary") or "").strip()[:500]
    return {"title": title[:120], "summary": summary, "body": body[:8000]}


def _require_pair(db: Session, dynamic_id: str) -> tuple[Membership, Membership]:
    dom, sub = _partners(db, dynamic_id)
    if dom is None or sub is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A switch needs one keyholder and one sub",
        )
    return dom, sub


def _complete(session: SwitchSession, now: datetime) -> None:
    session.status = "completed"
    session.ended_at = now


def _count_progress(db: Session, session: SwitchSession) -> int:
    if session.status != "active" or session.end_rule != "goal" or not session.started_at:
        return 0
    goal = _load_json(session.draft_goal_json)
    metric = goal.get("metric")
    if metric not in GOAL_METRICS:
        return 0
    rows = (
        db.query(OrgTrackingEntry)
        .filter(
            OrgTrackingEntry.dynamic_id == session.dynamic_id,
            OrgTrackingEntry.for_membership_id == session.subject_membership_id,
            OrgTrackingEntry.occurred_at >= session.started_at,
        )
        .all()
    )
    count = 0
    for entry in rows:
        tags = set(tags_to_list(entry.tags))
        if "switch" not in tags:
            continue
        if metric == "denials" and (entry.event_type == OrgEventType.no_orgasm or "denied" in tags):
            count += 1
        elif metric == "scenes" and "scene" in tags:
            count += 1
        elif metric == "spanking" and "spanking" in tags:
            count += 1
    return count


def _finish_if_met(db: Session, session: SwitchSession, now: datetime) -> None:
    if session.status != "active" or session.end_rule != "goal":
        return
    goal = _load_json(session.draft_goal_json)
    try:
        target = int(goal.get("target") or 0)
    except (TypeError, ValueError):
        target = 0
    if target and _count_progress(db, session) >= target:
        _complete(session, now)


def _expire_clocks(db: Session, dynamic_id: str, now: datetime) -> None:
    rows = (
        db.query(SwitchSession)
        .filter(
            SwitchSession.dynamic_id == dynamic_id,
            SwitchSession.status == "active",
            SwitchSession.end_rule == "clock",
            SwitchSession.ends_at.isnot(None),
            SwitchSession.ends_at <= now,
        )
        .all()
    )
    for session in rows:
        _complete(session, now)


def sync_earned_gifts(db: Session, dynamic: Dynamic) -> None:
    """A ready switch_gift opens a draft. It does not start the switch."""
    from .chastity_goals import build_goals_progress, parse_goals

    stored = parse_goals(getattr(dynamic, "chastity_goals", None))
    style_by_id = {g["id"]: g.get("switch_style") or "goal" for g in stored.get("goals") or []}
    reset_by_id = {g["id"]: g.get("reset_at") for g in stored.get("goals") or []}
    progress = build_goals_progress(db, dynamic)
    open_row = _open(db, dynamic.id)
    dom, sub = _partners(db, dynamic.id)
    if dom is None or sub is None:
        return
    for row in progress.get("goals") or []:
        if row.get("kind") != "switch_gift" or not row.get("ready") or not row.get("active"):
            continue
        gid = str(row.get("id") or "")
        if not gid:
            continue
        prior = (
            db.query(SwitchSession)
            .filter(SwitchSession.dynamic_id == dynamic.id, SwitchSession.source_goal_id == gid)
            .order_by(SwitchSession.created_at.desc())
            .first()
        )
        if prior and prior.status in OPEN_STATUSES:
            continue
        reset_raw = reset_by_id.get(gid)
        reset_at = None
        if reset_raw:
            try:
                reset_at = datetime.fromisoformat(str(reset_raw).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                reset_at = None
        if prior and prior.status == "completed":
            if reset_at is None or (prior.created_at and prior.created_at >= reset_at):
                continue
        if open_row is not None:
            continue
        drafter_id = row.get("for_membership_id") or sub.id
        style = style_by_id.get(gid) or "goal"
        kind = "scene_gift" if style == "scene" else "goal_gift"
        session = SwitchSession(
            dynamic_id=dynamic.id,
            kind=kind,
            status="drafting",
            offered_by_membership_id=dom.id,
            drafter_membership_id=drafter_id,
            subject_membership_id=dom.id,
            end_rule="one_scene" if kind == "scene_gift" else "goal",
            source_goal_id=gid,
            created_at=datetime.utcnow(),
        )
        db.add(session)
        db.flush()
        open_row = session


def prepare(db: Session, dynamic: Dynamic) -> SwitchSession | None:
    now = datetime.utcnow()
    _expire_clocks(db, dynamic.id, now)
    sync_earned_gifts(db, dynamic)
    current = _open(db, dynamic.id)
    if current is not None:
        _finish_if_met(db, current, now)
        if current.status not in OPEN_STATUSES:
            current = _open(db, dynamic.id)
    return current


def _headline(session: SwitchSession, progress: int) -> str:
    if session.status == "drafting":
        if session.kind == "scene_gift":
            return "Scene switch is open. Direct one scene, then the keyholder approves it."
        return "Switch is open. Draft one goal for the keyholder. It starts after she approves it."
    if session.status == "pending_approval":
        return "Switch draft is waiting for the keyholder."
    if session.status == "active":
        if session.end_rule == "clock" and session.ends_at:
            return f"Switch is on until {session.ends_at.strftime('%b %d, %H:%M')} UTC."
        if session.end_rule == "one_scene":
            return "Switch is on for this play session. Logging the scene ends it."
        goal = _load_json(session.draft_goal_json)
        target = goal.get("target") or 0
        title = goal.get("title") or "Goal"
        return f"Switch is on until “{title}” is met ({progress} / {target})."
    return "Switch"


def to_public(db: Session, session: SwitchSession | None, viewer: Membership) -> dict:
    is_dom = viewer.role == PartnerRole.dominant
    if session is None or session.status not in OPEN_STATUSES:
        return {
            "switch": None,
            "you_are_keyholder": is_dom,
            "can_offer": is_dom,
            "can_draft_goal": False,
            "can_draft_scene": False,
            "can_approve": False,
            "can_log": False,
            "headline": "",
            "progress": 0,
            "metrics": [{"id": k, "title": v} for k, v in GOAL_METRICS.items()],
        }
    progress = _count_progress(db, session)
    goal = _load_json(session.draft_goal_json)
    scene = _load_json(session.draft_scene_json)
    drafting = session.status == "drafting" and viewer.id == session.drafter_membership_id
    return {
        "switch": {
            "id": session.id,
            "kind": session.kind,
            "status": session.status,
            "end_rule": session.end_rule,
            "ends_at": session.ends_at.isoformat() + "Z" if session.ends_at else None,
            "source_goal_id": session.source_goal_id or "",
            "note": session.note or "",
            "goal": goal or None,
            "scene": scene or None,
            "started_at": session.started_at.isoformat() + "Z" if session.started_at else None,
        },
        "you_are_keyholder": is_dom,
        "can_offer": False,
        "can_draft_goal": drafting and session.kind in GOAL_KINDS,
        "can_draft_scene": drafting and session.kind in SCENE_KINDS,
        "can_approve": is_dom and session.status == "pending_approval",
        "can_log": session.status == "active" and session.end_rule in {"goal", "one_scene"},
        "can_end": is_dom and session.status == "active",
        "headline": _headline(session, progress),
        "progress": progress,
        "metrics": [{"id": k, "title": v} for k, v in GOAL_METRICS.items()],
    }


def offer_switch(
    db: Session,
    dynamic: Dynamic,
    actor: Membership,
    *,
    kind: str,
    hours: int | None = None,
) -> SwitchSession:
    if actor.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can offer a switch")
    prepare(db, dynamic)
    if _open(db, dynamic.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A switch is already open")
    if kind not in OFFER_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown switch kind")
    dom, sub = _require_pair(db, dynamic.id)
    now = datetime.utcnow()
    session = SwitchSession(
        dynamic_id=dynamic.id,
        kind=kind,
        offered_by_membership_id=dom.id,
        drafter_membership_id=sub.id,
        subject_membership_id=dom.id,
        created_at=now,
    )
    if kind == "timed":
        try:
            span = int(hours or 0)
        except (TypeError, ValueError):
            span = 0
        if span < 1 or span > 24 * 30:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick a length from 1 to 720 hours")
        session.status = "active"
        session.end_rule = "clock"
        session.ends_at = now + timedelta(hours=span)
        session.started_at = now
        session.approved_at = now
    elif kind == "session":
        session.status = "active"
        session.end_rule = "one_scene"
        session.started_at = now
        session.approved_at = now
    else:
        session.status = "drafting"
        session.end_rule = "goal"
    db.add(session)
    db.flush()
    return session


def submit_draft(db: Session, dynamic: Dynamic, actor: Membership, *, goal=None, scene=None) -> SwitchSession:
    prepare(db, dynamic)
    session = _open(db, dynamic.id)
    if session is None or session.status != "drafting":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No switch is waiting for a draft")
    if actor.id != session.drafter_membership_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the sub can draft this switch")
    if session.kind in GOAL_KINDS:
        session.draft_goal_json = json.dumps(_clean_goal(goal))
    elif session.kind in SCENE_KINDS:
        session.draft_scene_json = json.dumps(_clean_scene(scene))
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This switch does not take a draft")
    session.status = "pending_approval"
    session.note = ""
    db.flush()
    return session


def approve_switch(db: Session, dynamic: Dynamic, actor: Membership) -> SwitchSession:
    if actor.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can approve a switch")
    prepare(db, dynamic)
    session = _open(db, dynamic.id)
    if session is None or session.status != "pending_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing is waiting for approval")
    if session.kind in GOAL_KINDS and not _load_json(session.draft_goal_json):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The goal draft is empty")
    if session.kind in SCENE_KINDS and not _load_json(session.draft_scene_json):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The scene draft is empty")
    now = datetime.utcnow()
    session.status = "active"
    session.approved_at = now
    session.started_at = now
    session.note = ""
    db.flush()
    return session


def send_back(db: Session, dynamic: Dynamic, actor: Membership, *, note: str = "") -> SwitchSession:
    if actor.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can send a draft back")
    prepare(db, dynamic)
    session = _open(db, dynamic.id)
    if session is None or session.status != "pending_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing is waiting for approval")
    session.status = "drafting"
    session.note = (note or "").strip()[:500]
    db.flush()
    return session


def decline_switch(db: Session, dynamic: Dynamic, actor: Membership, *, note: str = "") -> SwitchSession:
    if actor.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can decline a switch")
    prepare(db, dynamic)
    session = _open(db, dynamic.id)
    if session is None or session.status not in {"drafting", "pending_approval"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This switch can no longer be declined")
    session.status = "declined"
    session.ended_at = datetime.utcnow()
    session.note = (note or "").strip()[:500]
    db.flush()
    return session


def end_switch(db: Session, dynamic: Dynamic, actor: Membership) -> SwitchSession:
    if actor.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can end a switch")
    prepare(db, dynamic)
    session = _open(db, dynamic.id)
    if session is None or session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No switch is active")
    _complete(session, datetime.utcnow())
    db.flush()
    return session


def log_experience(db: Session, dynamic: Dynamic, actor: Membership, *, kind: str) -> SwitchSession:
    prepare(db, dynamic)
    session = _open(db, dynamic.id)
    if session is None or session.status != "active" or session.end_rule not in {"goal", "one_scene"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to log for this switch")
    if actor.id not in {session.drafter_membership_id, session.offered_by_membership_id}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot log this switch")
    if kind not in LOG_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Log a denial, a scene, or a spanking")
    if session.end_rule == "goal":
        metric = _load_json(session.draft_goal_json).get("metric")
        expected = {"denials": "denial", "scenes": "scene", "spanking": "spanking"}.get(metric)
        if kind != expected:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That log does not count toward this goal")
    if session.end_rule == "one_scene" and kind == "denial":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Log the scene to finish this switch")
    now = datetime.utcnow()
    if kind == "denial":
        event_type = OrgEventType.no_orgasm
        tags = ["denied", "switch"]
        label = "denial"
    elif kind == "spanking":
        event_type = OrgEventType.sex
        tags = ["spanking", "switch"]
        label = "spanking"
    else:
        event_type = OrgEventType.sex
        tags = ["scene", "switch"]
        label = "scene"
    db.add(
        OrgTrackingEntry(
            dynamic_id=dynamic.id,
            logged_by_membership_id=actor.id,
            for_membership_id=session.subject_membership_id,
            event_type=event_type,
            notes=f"Switch · {label}",
            tags=tags_to_string(tags),
            occurred_at=now,
            created_at=now,
        )
    )
    db.flush()
    if session.end_rule == "one_scene":
        _complete(session, now)
    else:
        _finish_if_met(db, session, now)
    db.flush()
    return session
