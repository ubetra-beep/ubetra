"""Focused checks for chastity, tracking, and task bulk PATCH plus interval repair.

Uses a throwaway sqlite database. Does not touch the live UBETRA database.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    ChastityEndedKind,
    ChastityLockup,
    Dynamic,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    PartnerRole,
    Task,
    TaskList,
    TaskRecurrence,
    User,
)
from app.routers.chastity import _apply_chastity_bulk
from app.routers.org_tracking import _apply_tracking_bulk
from app.routers.tasks import bulk_update_tasks
from app.schemas import (
    ChastityBulkIn,
    ChastityLockupBulkUpdate,
    OrgTrackingBulkIn,
    OrgTrackingBulkUpdate,
    TaskBulkUpdateIn,
    TaskBulkUpdateItem,
)


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _couple(db):
    dom_user = User(username="bulk-dom", email="bulk-dom@example.com", password_hash="x")
    sub_user = User(username="bulk-sub", email="bulk-sub@example.com", password_hash="x")
    db.add_all([dom_user, sub_user])
    db.flush()
    dynamic = Dynamic(name="Bulk", invite_code="BULK1234")
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
        chastity_enabled=True,
    )
    db.add_all([dom, sub])
    db.commit()
    return dynamic, dom, sub, dom_user


def test_chastity_bulk_validates_and_repairs():
    db = _session()
    dynamic, dom, sub, _user = _couple(db)
    lockup = ChastityLockup(
        dynamic_id=dynamic.id,
        for_membership_id=sub.id,
        started_by_membership_id=dom.id,
        started_at=datetime(2026, 1, 1, 8, 0),
        status=LockupStatus.active,
        device_notes="before",
    )
    orgasm_at = datetime(2026, 1, 10, 21, 0)
    entry = OrgTrackingEntry(
        dynamic_id=dynamic.id,
        logged_by_membership_id=dom.id,
        for_membership_id=sub.id,
        event_type=OrgEventType.orgasm,
        tags="full orgasm",
        occurred_at=orgasm_at,
    )
    db.add_all([lockup, entry])
    db.commit()

    try:
        _apply_chastity_bulk(
            db,
            dynamic.id,
            dom,
            ChastityBulkIn(updates=[ChastityLockupBulkUpdate(
                id=lockup.id,
                ended_at=datetime(2025, 1, 1, 8, 0),
            )]),
        )
        raise AssertionError("end before start should fail")
    except HTTPException as exc:
        assert exc.status_code == 400
        db.rollback()

    fresh = db.get(ChastityLockup, lockup.id)
    assert fresh.device_notes == "before"
    assert fresh.ended_at is None

    _apply_chastity_bulk(
        db,
        dynamic.id,
        dom,
        ChastityBulkIn(updates=[ChastityLockupBulkUpdate(id=lockup.id, device_notes="after")]),
    )
    fresh = db.get(ChastityLockup, lockup.id)
    assert fresh.device_notes == "after"
    assert fresh.ended_kind == ChastityEndedKind.released_orgasm.value
    assert fresh.ended_at == orgasm_at
    print("chastity bulk + repair ok")


def test_tracking_bulk_update_delete_and_repair():
    db = _session()
    dynamic, dom, sub, _user = _couple(db)
    keep = OrgTrackingEntry(
        dynamic_id=dynamic.id,
        logged_by_membership_id=dom.id,
        for_membership_id=sub.id,
        event_type=OrgEventType.no_orgasm,
        notes="keep",
        occurred_at=datetime(2026, 2, 1, 20, 0),
        ended_at=datetime(2026, 2, 1, 21, 0),
    )
    drop = OrgTrackingEntry(
        dynamic_id=dynamic.id,
        logged_by_membership_id=dom.id,
        for_membership_id=sub.id,
        event_type=OrgEventType.no_orgasm,
        notes="drop",
        occurred_at=datetime(2026, 2, 2, 20, 0),
    )
    orgasm_at = datetime(2026, 2, 3, 22, 0)
    orgasm = OrgTrackingEntry(
        dynamic_id=dynamic.id,
        logged_by_membership_id=dom.id,
        for_membership_id=sub.id,
        event_type=OrgEventType.orgasm,
        tags="full orgasm",
        occurred_at=orgasm_at,
    )
    lockup = ChastityLockup(
        dynamic_id=dynamic.id,
        for_membership_id=sub.id,
        started_by_membership_id=dom.id,
        started_at=datetime(2026, 2, 1, 8, 0),
        status=LockupStatus.active,
    )
    db.add_all([keep, drop, orgasm, lockup])
    db.commit()
    result = _apply_tracking_bulk(
        db,
        dynamic.id,
        OrgTrackingBulkIn(
            updates=[OrgTrackingBulkUpdate(id=keep.id, notes="kept")],
            deletes=[drop.id],
        ),
    )
    assert result.updated == 1 and result.deleted == 1
    assert db.get(OrgTrackingEntry, keep.id).notes == "kept"
    assert db.get(OrgTrackingEntry, drop.id) is None
    fresh = db.get(ChastityLockup, lockup.id)
    assert fresh.ended_kind == ChastityEndedKind.released_orgasm.value
    assert fresh.ended_at == orgasm_at
    print("tracking bulk + repair ok")


def test_task_bulk_update():
    db = _session()
    dynamic, dom, sub, dom_user = _couple(db)
    task_list = TaskList(dynamic_id=dynamic.id, title="Daily", created_by_membership_id=dom.id)
    db.add(task_list)
    db.flush()
    due = datetime(2026, 3, 1, 18, 0)
    keep = Task(task_list_id=task_list.id, content="Dishes", due_at=due, position=0)
    drop = Task(task_list_id=task_list.id, content="Laundry", due_at=due, position=1)
    db.add_all([keep, drop])
    db.commit()
    out = bulk_update_tasks(
        dynamic.id,
        TaskBulkUpdateIn(
            updates=[TaskBulkUpdateItem(
                id=keep.id,
                content="Dishes tonight",
                due_shift_minutes=30,
                assigned_to_membership_id=sub.id,
            )],
            deletes=[drop.id],
        ),
        dom_user,
        db,
    )
    assert out
    fresh = db.get(Task, keep.id)
    assert fresh.content == "Dishes tonight"
    assert fresh.due_at == datetime(2026, 3, 1, 18, 30)
    assert fresh.assigned_to_membership_id == sub.id
    assert db.get(Task, drop.id) is None
    print("task bulk-update ok")


def main():
    test_chastity_bulk_validates_and_repairs()
    test_tracking_bulk_update_delete_and_repair()
    test_task_bulk_update()
    print("bulk patch tests passed")


if __name__ == "__main__":
    main()
