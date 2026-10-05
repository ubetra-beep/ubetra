"""Lock, remove, and heartbeat checks for Edge Guard. In-memory sqlite only."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Dynamic, Membership, PartnerRole, User
from app.routers.edge_guard import remove_edge_guard_domain
from app.services import edge_guard as eg


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _couple(db):
    dom_user = User(username="eg-dom", email="eg-dom@example.com", password_hash="x")
    sub_user = User(username="eg-sub", email="eg-sub@example.com", password_hash="x")
    db.add_all([dom_user, sub_user])
    db.flush()
    dynamic = Dynamic(name="Edge", invite_code="EDGE1234")
    db.add(dynamic)
    db.flush()
    dom = Membership(
        user_id=dom_user.id,
        dynamic_id=dynamic.id,
        role=PartnerRole.dominant,
        display_name="Key",
    )
    sub = Membership(
        user_id=sub_user.id,
        dynamic_id=dynamic.id,
        role=PartnerRole.submissive,
        display_name="Sub",
    )
    db.add_all([dom, sub])
    db.commit()
    return dynamic, dom, sub, dom_user, sub_user


def _install_push_log():
    sent = []

    def _fake(_db, **kwargs):
        sent.append(kwargs)

    eg._notify = _fake
    return sent


def _domain_id(db, dynamic, sub, name):
    from app.models import EdgeGuardDomain

    row = (
        db.query(EdgeGuardDomain)
        .filter(
            EdgeGuardDomain.dynamic_id == dynamic.id,
            EdgeGuardDomain.membership_id == sub.id,
            EdgeGuardDomain.domain == name,
        )
        .one()
    )
    return row.id


def test_lock_remove_and_requests():
    db = _session()
    sent = _install_push_log()
    dynamic, dom, sub, dom_user, sub_user = _couple(db)
    added = eg.add_domains(db, sub, ["https://www.reddit.com/r/all", "not a domain", "reddit.com"])
    assert added["added"] == ["reddit.com"]
    domain_id = _domain_id(db, dynamic, sub, "reddit.com")

    try:
        eg.update_policy(db, sub, locked=True, require_enabled=None, membership_id=None)
        raise AssertionError("sub locked the list")
    except HTTPException as exc:
        assert exc.status_code == 403

    eg.update_policy(db, dom, locked=True, require_enabled=False, membership_id=sub.id)
    assert eg.snapshot(db, sub)["you"]["locked"] is True

    try:
        eg.remove_domain(db, sub, domain_id)
        raise AssertionError("locked sub removed a site")
    except HTTPException as exc:
        assert exc.status_code == 403

    try:
        remove_edge_guard_domain(dynamic.id, domain_id, sub_user, db)
        raise AssertionError("router allowed a locked remove")
    except HTTPException as exc:
        assert exc.status_code == 403

    eg.add_domains(db, sub, ["example.com"])
    assert "example.com" in {row["domain"] for row in eg.snapshot(db, sub)["you"]["domains"]}

    before = len(sent)
    eg.request_removal(db, sub, domain_id)
    assert len(sent) == before + 1
    assert sent[-1]["title"] == "Edge Guard removal requested"
    eg.request_removal(db, sub, domain_id)
    assert len(sent) == before + 1

    try:
        eg.request_removal(db, dom, domain_id)
        raise AssertionError("keyholder used the request endpoint")
    except HTTPException as exc:
        assert exc.status_code == 400

    items = eg.removal_inbox_items(db, dynamic.id, dom)
    assert len(items) == 1 and items[0]["edge_guard_domain_id"] == domain_id
    assert eg.removal_inbox_items(db, dynamic.id, sub) == []

    other = _domain_id(db, dynamic, sub, "example.com")
    try:
        eg.decide_removal(db, sub, domain_id, "deny")
        raise AssertionError("sub decided a removal")
    except HTTPException as exc:
        assert exc.status_code == 403

    eg.decide_removal(db, dom, domain_id, "deny")
    denied_rows = [
        row
        for member in eg.snapshot(db, dom)["members"]
        for row in member["domains"]
        if row["domain"] == "reddit.com"
    ]
    assert denied_rows and denied_rows[0]["removal_requested_at"] is None

    eg.request_removal(db, sub, domain_id)
    eg.decide_removal(db, dom, domain_id, "approve")
    assert "reddit.com" not in {row["domain"] for row in eg.snapshot(db, sub)["you"]["domains"]}

    eg.remove_domain(db, dom, other)
    assert eg.snapshot(db, sub)["you"]["domains"] == []
    print("lock / remove / removal request ok")


def test_heartbeat_off_and_stale_once():
    db = _session()
    sent = _install_push_log()
    dynamic, dom, sub, _dom_user, _sub_user = _couple(db)

    eg.record_heartbeat(db, sub, enabled=False, running=False, vpn_permission=True, domain_count=0)
    assert sent == []

    eg.add_domains(db, sub, ["reddit.com"])
    eg.record_heartbeat(db, sub, enabled=False, running=False, vpn_permission=False, domain_count=1)
    assert len(sent) == 1
    assert sent[-1]["title"] == "Edge Guard is off"
    eg.record_heartbeat(db, sub, enabled=False, running=False, vpn_permission=False, domain_count=1)
    assert len(sent) == 1

    eg.record_heartbeat(db, sub, enabled=True, running=True, vpn_permission=True, domain_count=1)
    assert len(sent) == 1
    eg.record_heartbeat(db, sub, enabled=False, running=False, vpn_permission=True, domain_count=1)
    assert len(sent) == 2

    assert eg.scan_alerts(db) == 0
    from app.models import EdgeGuardPolicy

    policy = (
        db.query(EdgeGuardPolicy)
        .filter(EdgeGuardPolicy.membership_id == sub.id)
        .one()
    )
    policy.last_heartbeat = datetime.utcnow() - timedelta(hours=7)
    policy.last_status = '{"enabled": true}'
    policy.stale_notified_at = None
    policy.off_notified_at = datetime.utcnow()
    db.commit()
    assert eg.scan_alerts(db) == 1
    assert sent[-1]["title"] == "Edge Guard not checking in"
    assert eg.scan_alerts(db) == 0

    eg.record_heartbeat(db, sub, enabled=True, running=True, vpn_permission=True, domain_count=1)
    policy = (
        db.query(EdgeGuardPolicy)
        .filter(EdgeGuardPolicy.membership_id == sub.id)
        .one()
    )
    policy.last_heartbeat = datetime.utcnow() - timedelta(hours=8)
    policy.stale_notified_at = None
    db.commit()
    assert eg.scan_alerts(db) == 1
    assert eg.scan_alerts(db) == 0
    assert dynamic.id
    print("heartbeat off / stale once ok")


def main():
    test_lock_remove_and_requests()
    test_heartbeat_off_and_stale_once()
    print("edge guard ok")


if __name__ == "__main__":
    main()
