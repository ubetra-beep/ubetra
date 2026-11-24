"""client_event_id retries return the same row and do not double-apply."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Dynamic, Membership, OrgEventType, PartnerRole, User
from app.routers.org_tracking import log_tracking_entry
from app.schemas import OrgasmDetailCreate, OrgTrackingEntryCreate
from app.services.client_events import incoming_is_older
from datetime import datetime


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _couple(db):
    user = User(username="local", email="local@example.com", password_hash="x")
    db.add(user)
    db.flush()
    dynamic = Dynamic(name="Phone", invite_code="PHONE123")
    db.add(dynamic)
    db.flush()
    member = Membership(
        user_id=user.id,
        dynamic_id=dynamic.id,
        role=PartnerRole.submissive,
        display_name="You",
        chastity_enabled=True,
    )
    db.add(member)
    db.commit()
    return user, dynamic, member


def test_retry_returns_same_tracking_row():
    db = _session()
    user, dynamic, member = _couple(db)
    payload = OrgTrackingEntryCreate(
        for_membership_id=member.id,
        event_type=OrgEventType.orgasm,
        notes="once",
        orgasms=[OrgasmDetailCreate(tags=["Full Orgasm"])],
        client_event_id="evt-1",
        updated_at=datetime(2026, 11, 23, 12, 0, 0),
    )
    first = log_tracking_entry(dynamic.id, payload, user, db)
    second = log_tracking_entry(dynamic.id, payload, user, db)
    assert first.id == second.id
    from app.models import OrgTrackingEntry

    assert db.query(OrgTrackingEntry).count() == 1


def test_older_stamp_loses():
    older = datetime(2026, 11, 23, 11, 0, 0)
    newer = datetime(2026, 11, 23, 12, 0, 0)
    assert incoming_is_older(newer, older)
    assert not incoming_is_older(older, newer)
    assert not incoming_is_older(None, newer)


if __name__ == "__main__":
    test_older_stamp_loses()
    test_retry_returns_same_tracking_row()
    print("client events ok")
