from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Membership, PartnerRole, SpinGameSession
from .chat_events import post_system_event
from .push import notify_playtime_push_async


def _loads(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def get_active_session(db: Session, dynamic_id: str) -> SpinGameSession | None:
    return (
        db.query(SpinGameSession)
        .filter(
            SpinGameSession.dynamic_id == dynamic_id,
            SpinGameSession.status.in_(["active", "awaiting_post_spin", "paused"]),
        )
        .order_by(SpinGameSession.updated_at.desc())
        .first()
    )


def ensure_session(
    db: Session,
    *,
    dynamic_id: str,
    membership: Membership,
) -> SpinGameSession:
    session = get_active_session(db, dynamic_id)
    if session is not None:
        return session
    session = SpinGameSession(
        dynamic_id=dynamic_id,
        created_by_membership_id=membership.id,
        status="active",
        secret_json="{}",
        public_json="{}",
    )
    db.add(session)
    db.flush()
    return session


def session_view(session: SpinGameSession, membership: Membership) -> dict:
    public = _loads(session.public_json)
    secret = _loads(session.secret_json)
    is_dom = membership.role == PartnerRole.dominant
    is_sub = membership.role == PartnerRole.submissive
    out = {
        "id": session.id,
        "status": session.status,
        "started_at": session.started_at.isoformat() + "Z" if session.started_at else None,
        "updated_at": session.updated_at.isoformat() + "Z" if session.updated_at else None,
        "public": public,
        "secret": secret if is_dom else None,
        "your_role": membership.role.value,
        "can_spin_post_orgasm": False,
    }
    post = public.get("post_orgasm") or {}
    if session.status == "awaiting_post_spin" and post.get("use_wheel"):
        spinner = post.get("spinner") or "dom"
        results = post.get("results") or []
        needed = int(post.get("task_count") or 1)
        if len(results) < needed:
            # Keyholder can always spin; sub when chosen or either.
            if is_dom:
                out["can_spin_post_orgasm"] = True
            elif spinner in {"either", "sub"} and is_sub:
                out["can_spin_post_orgasm"] = True
    return out


def update_secret(session: SpinGameSession, patch: dict) -> None:
    data = _loads(session.secret_json)
    data.update(patch)
    session.secret_json = _dumps(data)
    session.updated_at = datetime.utcnow()


def update_public(session: SpinGameSession, patch: dict) -> None:
    data = _loads(session.public_json)
    data.update(patch)
    session.public_json = _dumps(data)
    session.updated_at = datetime.utcnow()


def configure_post_orgasm(
    session: SpinGameSession,
    *,
    task_pool: list[dict],
    task_count: int,
    use_wheel: bool,
    spinner: str,
    manual_picks: list[dict] | None = None,
) -> dict:
    if not task_pool:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one task")
    count = max(1, min(int(task_count), len(task_pool)))
    if spinner not in {"dom", "sub", "either"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid spinner")

    # Pool stays secret (keyholder-only). Public only exposes shared spin meta + results.
    secret = _loads(session.secret_json)
    secret["post_orgasm_pool"] = task_pool
    session.secret_json = _dumps(secret)

    public_post: dict = {
        "phase": "post_orgasm",
        "task_count": count,
        "use_wheel": bool(use_wheel),
        "spinner": spinner if use_wheel else "dom",
        "results": [],
    }
    if not use_wheel:
        picks = manual_picks or []
        if len(picks) != count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pick exactly {count} task(s)",
            )
        public_post["results"] = picks
        session.status = "active"
    else:
        session.status = "awaiting_post_spin"

    public = _loads(session.public_json)
    public["post_orgasm"] = public_post
    session.public_json = _dumps(public)
    session.updated_at = datetime.utcnow()
    return {**public_post, "task_pool": task_pool}


def spin_post_orgasm(
    db: Session,
    session: SpinGameSession,
    membership: Membership,
) -> dict:
    public = _loads(session.public_json)
    secret = _loads(session.secret_json)
    post = public.get("post_orgasm") or {}
    if session.status != "awaiting_post_spin" or not post.get("use_wheel"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No post-orgasm wheel waiting")

    spinner = post.get("spinner") or "dom"
    is_dom = membership.role == PartnerRole.dominant
    is_sub = membership.role == PartnerRole.submissive
    # Keyholder may always spin; sub only when spinner is sub or either.
    if is_dom:
        pass
    elif spinner in {"either", "sub"} and is_sub:
        pass
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not allowed to spin this wheel")

    pool = list(secret.get("post_orgasm_pool") or [])
    results = list(post.get("results") or [])
    needed = int(post.get("task_count") or 1)
    if len(results) >= needed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="All post-orgasm tasks already spun")
    if not pool:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Post-orgasm task pool missing")

    remaining = [t for t in pool if t.get("id") not in {r.get("id") for r in results}]
    if not remaining:
        remaining = pool
    pick = random.choice(remaining)
    results.append({"id": pick.get("id"), "title": pick.get("title"), "description": pick.get("description", "")})
    post["results"] = results
    public["post_orgasm"] = post
    session.public_json = _dumps(public)
    session.updated_at = datetime.utcnow()

    if len(results) >= needed:
        session.status = "active"
        titles = ", ".join(r["title"] for r in results)
        post_system_event(
            db,
            session.dynamic_id,
            membership,
            f"Playtime post-orgasm task(s): {titles}",
            from_label="Game",
        )
        notify_playtime_push_async(
            dynamic_id=session.dynamic_id,
            sender_membership_id=membership.id,
            title="Post-orgasm task",
            body=titles,
            url=f"/#/dynamic/{session.dynamic_id}/assistant/games/spin?post=1",
        )

    return {"picked": pick, "results": results, "complete": len(results) >= needed}


def end_session(session: SpinGameSession) -> None:
    """Mark the spin game completed so a fresh one can start."""
    session.status = "completed"
    session.updated_at = datetime.utcnow()


def announce_shared_outcome(
    db: Session,
    *,
    dynamic_id: str,
    membership: Membership,
    text: str,
    push_url: str | None = None,
    from_label: str = "Game",
) -> None:
    """Visible chat + push for non-hidden playtime outcomes (shown as Game)."""
    # Keep action markers in chat body; strip them from push preview.
    push_body = re.sub(r"\[\[ubetra:[^\]]+\]\]", "", text).strip()
    push_body = re.sub(r"\[\[from:[^\]]+\]\]", "", push_body).strip()
    post_system_event(db, dynamic_id, membership, text, from_label=from_label)
    notify_playtime_push_async(
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        title=from_label or "Playtime",
        body=push_body or text,
        url=push_url,
    )


def fulfill_spin_outcome(
    db: Session,
    *,
    dynamic_id: str,
    membership: Membership,
    kind: str,
    count: int,
    unit: str = "days",
) -> dict:
    """Write orgasm/chastity tracking from a fulfilled spin outcome + Game chat notify."""
    from ..models import Membership as MembershipModel
    from ..models import OrgEventType, OrgTrackingEntry, OrgTrackingOrgasm, PartnerRole
    from .chastity import active_lockup
    from .tags import tags_to_string

    amount = max(1, min(int(count or 1), 40))
    memberships = (
        db.query(MembershipModel).filter(MembershipModel.dynamic_id == dynamic_id).all()
    )
    dominant = next((m for m in memberships if m.role == PartnerRole.dominant), None)
    submissive = next((m for m in memberships if m.role == PartnerRole.submissive), None)

    if kind == "dom_orgasms":
        if dominant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No keyholder in this dynamic")
        entry = OrgTrackingEntry(
            dynamic_id=dynamic_id,
            logged_by_membership_id=membership.id,
            for_membership_id=dominant.id,
            event_type=OrgEventType.orgasm,
            notes="Playtime spin: orgasms for keyholder while locked",
            tags=tags_to_string(["Playtime", "Partner"]),
            occurred_at=datetime.utcnow(),
        )
        for idx in range(amount):
            entry.orgasms.append(
                OrgTrackingOrgasm(
                    tags=tags_to_string(["Partner", "Playtime"]),
                    position=idx,
                )
            )
        db.add(entry)
        text = f"logged {amount} orgasm(s) for {dominant.display_name} (spin fulfilled)"
        announce_shared_outcome(db, dynamic_id=dynamic_id, membership=membership, text=text)
        return {"ok": True, "kind": kind, "count": amount, "for_display_name": dominant.display_name}

    if kind == "wait_lockup":
        days = amount * 7 if unit == "weeks" else amount
        days = max(1, min(days, 365))
        if submissive is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No submissive in this dynamic")
        lockup = active_lockup(db, dynamic_id, submissive.id)
        if lockup is None:
            text = (
                f"spin added {days} day(s) wait for {submissive.display_name} — "
                "no active lockup to extend (enable/start chastity to track it)"
            )
            announce_shared_outcome(db, dynamic_id=dynamic_id, membership=membership, text=text)
            return {"ok": True, "kind": kind, "days": days, "extended": False}

        base = lockup.planned_end_at or datetime.utcnow()
        if base < datetime.utcnow():
            base = datetime.utcnow()
        lockup.planned_end_at = base + timedelta(days=days)
        note = f"Playtime spin +{days}d"
        existing = (lockup.device_notes or "").strip()
        lockup.device_notes = f"{existing}; {note}".strip("; ") if existing else note
        end_label = lockup.planned_end_at.strftime("%Y-%m-%d %H:%M")
        text = f"added {days} day(s) to {submissive.display_name}'s lockup (planned end {end_label})"
        announce_shared_outcome(db, dynamic_id=dynamic_id, membership=membership, text=text)
        return {
            "ok": True,
            "kind": kind,
            "days": days,
            "extended": True,
            "planned_end_at": lockup.planned_end_at.isoformat() + "Z",
            "for_display_name": submissive.display_name,
        }

    if kind == "sub_full_orgasm":
        if submissive is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No submissive in this dynamic")
        entry = OrgTrackingEntry(
            dynamic_id=dynamic_id,
            logged_by_membership_id=membership.id,
            for_membership_id=submissive.id,
            event_type=OrgEventType.orgasm,
            notes="Playtime spin: full orgasm granted",
            tags=tags_to_string(["Full Orgasm", "Playtime"]),
            occurred_at=datetime.utcnow(),
        )
        entry.orgasms.append(
            OrgTrackingOrgasm(
                tags=tags_to_string(["Full Orgasm", "Playtime"]),
                position=0,
            )
        )
        db.add(entry)
        text = f"logged a full orgasm for {submissive.display_name} (granted after spin)"
        announce_shared_outcome(db, dynamic_id=dynamic_id, membership=membership, text=text)
        return {"ok": True, "kind": kind, "for_display_name": submissive.display_name}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown fulfill kind")
