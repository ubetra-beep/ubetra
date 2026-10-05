"""Server-side Edge Guard blocklist, lock, and keyholder alerts.

Uninstalling the app or revoking the VPN cannot be prevented. Heartbeats and a
6-hour stale check only detect it. Each off episode and each stale episode
notifies the keyholder once.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import EdgeGuardDomain, EdgeGuardPolicy, Membership, PartnerRole
from ..timeutil import as_naive_utc

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=6)
_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

_stop = threading.Event()
_thread: threading.Thread | None = None


def normalize_domain(raw: str) -> str:
    text = (raw or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0]
    if "@" in text:
        text = text.split("@")[-1]
    if text.startswith("www."):
        text = text[4:]
    if ":" in text:
        text = text.split(":")[0]
    text = text.strip(".")
    if not text or len(text) > 253 or not _HOST_RE.match(text):
        return ""
    return text


def _now() -> datetime:
    return datetime.utcnow()


def _parse_status(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _status_out(raw: str | None) -> dict:
    data = _parse_status(raw)
    return {
        "enabled": bool(data.get("enabled")),
        "running": bool(data.get("running")),
        "vpn_permission": bool(data.get("vpn_permission")),
        "domain_count": int(data.get("domain_count") or 0),
    }


def _is_keyholder(actor: Membership) -> bool:
    return actor.role == PartnerRole.dominant


def _require_keyholder(actor: Membership) -> None:
    if not _is_keyholder(actor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can do that",
        )


def _member(db: Session, dynamic_id: str, membership_id: str) -> Membership | None:
    row = db.get(Membership, membership_id)
    if row is None or row.dynamic_id != dynamic_id:
        return None
    return row


def _resolve_target(db: Session, actor: Membership, membership_id: str | None) -> Membership:
    if membership_id:
        row = _member(db, actor.dynamic_id, membership_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
        if not _is_keyholder(actor) and row.id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only change your own Edge Guard list",
            )
        return row
    if not _is_keyholder(actor):
        return actor
    sub = (
        db.query(Membership)
        .filter(
            Membership.dynamic_id == actor.dynamic_id,
            Membership.role == PartnerRole.submissive,
        )
        .order_by(Membership.created_at.asc())
        .first()
    )
    return sub or actor


def _policy(db: Session, dynamic_id: str, membership_id: str) -> EdgeGuardPolicy | None:
    return (
        db.query(EdgeGuardPolicy)
        .filter(
            EdgeGuardPolicy.dynamic_id == dynamic_id,
            EdgeGuardPolicy.membership_id == membership_id,
        )
        .first()
    )


def _ensure_policy(db: Session, dynamic_id: str, membership_id: str) -> EdgeGuardPolicy:
    row = _policy(db, dynamic_id, membership_id)
    if row is not None:
        return row
    now = _now()
    row = EdgeGuardPolicy(
        dynamic_id=dynamic_id,
        membership_id=membership_id,
        locked=False,
        require_enabled=False,
        last_status="{}",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _domains(db: Session, dynamic_id: str, membership_id: str) -> list[EdgeGuardDomain]:
    return (
        db.query(EdgeGuardDomain)
        .filter(
            EdgeGuardDomain.dynamic_id == dynamic_id,
            EdgeGuardDomain.membership_id == membership_id,
        )
        .order_by(EdgeGuardDomain.domain.asc())
        .all()
    )


def _should_watch(db: Session, policy: EdgeGuardPolicy) -> bool:
    if policy.locked or policy.require_enabled:
        return True
    return (
        db.query(EdgeGuardDomain)
        .filter(
            EdgeGuardDomain.dynamic_id == policy.dynamic_id,
            EdgeGuardDomain.membership_id == policy.membership_id,
        )
        .count()
        > 0
    )


def _keyholder_user_ids(db: Session, dynamic_id: str) -> set[str]:
    return {
        m.user_id
        for m in db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
        if m.role == PartnerRole.dominant
    }


def _notify(
    db: Session,
    *,
    user_ids: set[str],
    title: str,
    body: str,
    url: str,
    tag: str,
    dynamic_id: str,
) -> None:
    if not user_ids:
        return
    from .push import _notify_users_payload

    _notify_users_payload(
        db,
        user_ids=user_ids,
        title=title[:80],
        body=(body or "")[:180],
        url=url,
        tag=tag[:32],
        dynamic_id=dynamic_id,
        kind="edge_guard",
    )


def _settings_url(dynamic_id: str) -> str:
    return f"/#/settings?focus=edge-guard&dynamic={dynamic_id}"


def _member_name(db: Session, membership_id: str) -> str:
    row = db.get(Membership, membership_id)
    name = (getattr(row, "display_name", None) or "").strip() if row else ""
    return name or "Your sub"


def _domain_out(row: EdgeGuardDomain) -> dict:
    return {
        "id": row.id,
        "domain": row.domain,
        "added_by": row.added_by or "",
        "created_at": row.created_at,
        "removal_requested_at": row.removal_requested_at,
    }


def _member_out(db: Session, membership: Membership) -> dict:
    policy = _policy(db, membership.dynamic_id, membership.id)
    return {
        "membership_id": membership.id,
        "display_name": membership.display_name or "",
        "role": membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        "locked": bool(policy.locked) if policy else False,
        "require_enabled": bool(policy.require_enabled) if policy else False,
        "last_heartbeat": policy.last_heartbeat if policy else None,
        "last_status": _status_out(policy.last_status) if policy else _status_out("{}"),
        "domains": [_domain_out(row) for row in _domains(db, membership.dynamic_id, membership.id)],
    }


def snapshot(db: Session, actor: Membership) -> dict:
    members = (
        db.query(Membership)
        .filter(Membership.dynamic_id == actor.dynamic_id)
        .order_by(Membership.created_at.asc())
        .all()
    )
    you = _member_out(db, actor)
    visible = members if _is_keyholder(actor) else [actor]
    return {
        "you_are_keyholder": _is_keyholder(actor),
        "you": you,
        "members": [_member_out(db, m) for m in visible],
    }


def _get_domain(db: Session, actor: Membership, domain_id: str) -> EdgeGuardDomain:
    row = db.get(EdgeGuardDomain, domain_id)
    if row is None or row.dynamic_id != actor.dynamic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return row


def add_domains(
    db: Session,
    actor: Membership,
    domains: list[str],
    membership_id: str | None = None,
) -> dict:
    target = _resolve_target(db, actor, membership_id)
    added: list[str] = []
    existing = {row.domain for row in _domains(db, target.dynamic_id, target.id)}
    for raw in domains:
        domain = normalize_domain(raw)
        if not domain or domain in existing:
            continue
        db.add(
            EdgeGuardDomain(
                dynamic_id=target.dynamic_id,
                membership_id=target.id,
                domain=domain,
                added_by=actor.id,
                created_at=_now(),
            )
        )
        existing.add(domain)
        added.append(domain)
    if added:
        policy = _ensure_policy(db, target.dynamic_id, target.id)
        policy.updated_at = _now()
        if _is_keyholder(actor) and target.id != actor.id:
            _notify(
                db,
                user_ids={target.user_id},
                title="Edge Guard updated",
                body="Sites were added to your blocklist",
                url=_settings_url(actor.dynamic_id),
                tag=f"eg-add-{target.id[:8]}",
                dynamic_id=actor.dynamic_id,
            )
    db.commit()
    out = snapshot(db, actor)
    out["added"] = added
    return out


def remove_domain(db: Session, actor: Membership, domain_id: str) -> dict:
    row = _get_domain(db, actor, domain_id)
    if not _is_keyholder(actor):
        if row.membership_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the keyholder can remove sites",
            )
        policy = _policy(db, row.dynamic_id, row.membership_id)
        if policy is not None and policy.locked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Edge Guard is locked. Request removal instead.",
            )
    owner_id = row.membership_id
    domain = row.domain
    db.delete(row)
    policy = _policy(db, actor.dynamic_id, owner_id)
    if policy is not None:
        policy.updated_at = _now()
    if _is_keyholder(actor) and owner_id != actor.id:
        owner = db.get(Membership, owner_id)
        if owner is not None:
            _notify(
                db,
                user_ids={owner.user_id},
                title="Edge Guard updated",
                body=f"{domain} was removed from your blocklist",
                url=_settings_url(actor.dynamic_id),
                tag=f"eg-rmv-{domain_id[:8]}",
                dynamic_id=actor.dynamic_id,
            )
    db.commit()
    return snapshot(db, actor)


def request_removal(db: Session, actor: Membership, domain_id: str) -> dict:
    if _is_keyholder(actor):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Remove the site directly",
        )
    row = _get_domain(db, actor, domain_id)
    if row.membership_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only request removal from your own list",
        )
    policy = _policy(db, row.dynamic_id, row.membership_id)
    if policy is None or not policy.locked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can remove this site yourself",
        )
    if row.removal_requested_at is None:
        row.removal_requested_at = _now()
        name = _member_name(db, actor.id)
        _notify(
            db,
            user_ids=_keyholder_user_ids(db, actor.dynamic_id),
            title="Edge Guard removal requested",
            body=f"{name} asked to unblock {row.domain}",
            url=_settings_url(actor.dynamic_id),
            tag=f"eg-rm-{row.id[:8]}",
            dynamic_id=actor.dynamic_id,
        )
        db.commit()
    return snapshot(db, actor)


def decide_removal(db: Session, actor: Membership, domain_id: str, decision: str) -> dict:
    _require_keyholder(actor)
    row = _get_domain(db, actor, domain_id)
    owner = db.get(Membership, row.membership_id)
    domain = row.domain
    choice = (decision or "").strip().lower()
    if choice == "approve":
        db.delete(row)
        title = "Edge Guard site removed"
        body = f"{domain} was removed from your blocklist"
    elif choice == "deny":
        row.removal_requested_at = None
        title = "Edge Guard removal denied"
        body = f"{domain} stays blocked"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Decision must be approve or deny")
    if owner is not None:
        _notify(
            db,
            user_ids={owner.user_id},
            title=title,
            body=body,
            url=_settings_url(actor.dynamic_id),
            tag=f"eg-dc-{domain_id[:8]}",
            dynamic_id=actor.dynamic_id,
        )
    policy = _policy(db, actor.dynamic_id, row.membership_id)
    if policy is not None:
        policy.updated_at = _now()
    db.commit()
    return snapshot(db, actor)


def update_policy(
    db: Session,
    actor: Membership,
    *,
    locked: bool | None,
    require_enabled: bool | None,
    membership_id: str | None,
) -> dict:
    _require_keyholder(actor)
    target = _resolve_target(db, actor, membership_id)
    policy = _ensure_policy(db, target.dynamic_id, target.id)
    if locked is not None:
        policy.locked = bool(locked)
    if require_enabled is not None:
        policy.require_enabled = bool(require_enabled)
    policy.updated_at = _now()
    if target.id != actor.id:
        _notify(
            db,
            user_ids={target.user_id},
            title="Edge Guard updated",
            body="Your keyholder changed Edge Guard settings",
            url=_settings_url(actor.dynamic_id),
            tag=f"eg-pol-{target.id[:8]}",
            dynamic_id=actor.dynamic_id,
        )
    db.commit()
    return snapshot(db, actor)


def _push_off(db: Session, policy: EdgeGuardPolicy) -> None:
    name = _member_name(db, policy.membership_id)
    _notify(
        db,
        user_ids=_keyholder_user_ids(db, policy.dynamic_id),
        title="Edge Guard is off",
        body=(
            f"{name}'s Edge Guard is off or the VPN permission was revoked. "
            "Uninstall and VPN revoke can only be detected."
        ),
        url=_settings_url(policy.dynamic_id),
        tag=f"eg-off-{policy.membership_id[:8]}",
        dynamic_id=policy.dynamic_id,
    )


def _push_stale(db: Session, policy: EdgeGuardPolicy) -> None:
    name = _member_name(db, policy.membership_id)
    _notify(
        db,
        user_ids=_keyholder_user_ids(db, policy.dynamic_id),
        title="Edge Guard not checking in",
        body=f"{name}'s Edge Guard has not checked in for over 6 hours.",
        url=_settings_url(policy.dynamic_id),
        tag=f"eg-stale-{policy.membership_id[:8]}",
        dynamic_id=policy.dynamic_id,
    )


def record_heartbeat(
    db: Session,
    actor: Membership,
    *,
    enabled: bool,
    running: bool,
    vpn_permission: bool,
    domain_count: int,
) -> dict:
    """Heartbeat is always for the signed-in member's own phone."""
    policy = _ensure_policy(db, actor.dynamic_id, actor.id)
    now = _now()
    policy.last_heartbeat = now
    policy.last_status = json.dumps(
        {
            "enabled": bool(enabled),
            "running": bool(running),
            "vpn_permission": bool(vpn_permission),
            "domain_count": int(domain_count or 0),
        }
    )
    policy.updated_at = now
    # A fresh check-in ends the stale episode so the next 6-hour gap can alert once.
    policy.stale_notified_at = None
    reported_off = not bool(enabled)
    if not reported_off:
        policy.off_notified_at = None
    elif _should_watch(db, policy) and policy.off_notified_at is None:
        _push_off(db, policy)
        policy.off_notified_at = now
    db.commit()
    return snapshot(db, actor)


def scan_alerts(db: Session) -> int:
    """Notify once per stale episode, and once if a stored status is off but unsent."""
    now = _now()
    sent = 0
    policies = db.query(EdgeGuardPolicy).all()
    for policy in policies:
        if not _should_watch(db, policy):
            continue
        anchor = as_naive_utc(policy.last_heartbeat or policy.updated_at)
        if (
            anchor is not None
            and now - anchor >= STALE_AFTER
            and policy.stale_notified_at is None
        ):
            _push_stale(db, policy)
            policy.stale_notified_at = now
            sent += 1
        status_doc = _parse_status(policy.last_status)
        if (
            policy.last_heartbeat is not None
            and status_doc.get("enabled") is False
            and policy.off_notified_at is None
        ):
            _push_off(db, policy)
            policy.off_notified_at = now
            sent += 1
    if sent:
        db.commit()
    return sent


def removal_inbox_items(db: Session, dynamic_id: str, membership: Membership) -> list[dict]:
    if membership.role != PartnerRole.dominant:
        return []
    rows = (
        db.query(EdgeGuardDomain)
        .filter(
            EdgeGuardDomain.dynamic_id == dynamic_id,
            EdgeGuardDomain.removal_requested_at.isnot(None),
        )
        .order_by(EdgeGuardDomain.removal_requested_at.desc())
        .all()
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": f"edge-guard-removal-{row.id}",
                "kind": "edge_guard_removal",
                "title": "Edge Guard removal requested",
                "body": f"{_member_name(db, row.membership_id)} asked to unblock {row.domain}",
                "occurred_at": row.removal_requested_at,
                "path": f"/settings?focus=edge-guard&dynamic={dynamic_id}",
                "edge_guard_domain_id": row.id,
            }
        )
    return items


def start_edge_guard_loop() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def _loop() -> None:
        while not _stop.wait(120):
            from ..database import SessionLocal

            db = SessionLocal()
            try:
                scan_alerts(db)
            except Exception:
                logger.exception("edge guard alert scan failed")
                db.rollback()
            finally:
                db.close()

    _thread = threading.Thread(target=_loop, name="ubetra-edge-guard", daemon=True)
    _thread.start()


def stop_edge_guard_loop() -> None:
    _stop.set()
