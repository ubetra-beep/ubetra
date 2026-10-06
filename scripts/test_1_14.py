"""UBETRA 1.14 checks. Throwaway sqlite only — does not touch the live database."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException

from app.database import Base
from app.models import (
    ChastityLockup,
    Dynamic,
    LockupStatus,
    Membership,
    PartnerRole,
    Task,
    TaskCompletion,
    TaskList,
    TaskRecurrence,
    User,
)
from app.routers.tasks import _perform_task_complete
from app.services.chastity import validate_break_times
from app.services.chastity_goals import _count_tasks_completed, note_orgasm_gift, parse_goals, serialize_goals
from app.services.chastity_release import maybe_relock_after_orgasm, orgasm_end_kind
from app.services.tasks_service import advance_due_date, build_inbox
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _couple(db):
    dom_user = User(username="t114-dom", email="t114-dom@example.com", password_hash="x")
    sub_user = User(username="t114-sub", email="t114-sub@example.com", password_hash="x")
    db.add_all([dom_user, sub_user])
    db.flush()
    dynamic = Dynamic(name="T114", invite_code="T114CODE1", chastity_auto_relock_after_orgasm=True)
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
    return dynamic, dom, sub, sub_user


def _task(db, dynamic, dom, sub, *, content, recurrence, due, interval=None, tags="Domestic"):
    task_list = TaskList(dynamic_id=dynamic.id, title="List", created_by_membership_id=dom.id)
    db.add(task_list)
    db.flush()
    task = Task(
        task_list_id=task_list.id,
        content=content,
        created_by_membership_id=dom.id,
        assigned_to_membership_id=sub.id,
        tags=tags,
        recurrence=recurrence,
        recurrence_interval=interval,
        due_at=due,
        next_due_at=due,
    )
    db.add(task)
    db.commit()
    db.refresh(task_list)
    return task_list, task


def test_recurring_completion_counts_for_goal():
    db = _session()
    dynamic, dom, sub, sub_user = _couple(db)
    due = datetime.utcnow() - timedelta(hours=2)
    task_list, task = _task(
        db, dynamic, dom, sub, content="Coffee", recurrence=TaskRecurrence.daily, due=due, interval=1
    )
    _perform_task_complete(db, task_list, task, sub, sub_user, datetime.utcnow())
    db.commit()
    db.refresh(task)
    rows = db.query(TaskCompletion).filter(TaskCompletion.task_id == task.id).all()
    assert len(rows) == 1, rows
    assert task.completed_at is None
    assert task.next_due_at and task.next_due_at > datetime.utcnow()
    since = datetime.utcnow() - timedelta(days=2)
    assert _count_tasks_completed(db, dynamic.id, sub.id, since, tag="domestic") == 1


def test_inbox_skips_next_day_beyond_reminder():
    db = _session()
    dynamic, _dom, sub, _user = _couple(db)
    tomorrow = datetime.utcnow() + timedelta(days=1)
    _task(db, dynamic, _dom, sub, content="Tomorrow", recurrence=TaskRecurrence.daily, due=tomorrow, interval=1)
    inbox = build_inbox(db, dynamic.id, sub)
    kinds = [item.get("kind") for item in inbox.get("items") or []]
    assert "task_due_soon" not in kinds, inbox
    assert "task_overdue" not in kinds, inbox


def test_ruined_does_not_end_cheated_does():
    assert orgasm_end_kind(["ruined orgasm"]) is None
    assert orgasm_end_kind(["ruined orgasm", "cheated"]) == "cheated_orgasm"
    assert orgasm_end_kind(["full orgasm"]) == "released_orgasm"


def test_auto_relock_creates_active_lockup():
    db = _session()
    dynamic, dom, sub, _user = _couple(db)
    ended = datetime.utcnow() - timedelta(minutes=5)
    lockup = ChastityLockup(
        dynamic_id=dynamic.id,
        for_membership_id=sub.id,
        started_by_membership_id=dom.id,
        started_at=ended - timedelta(days=3),
        ended_at=ended,
        ended_kind="released_orgasm",
        status=LockupStatus.ended,
    )
    db.add(lockup)
    db.commit()
    fresh = maybe_relock_after_orgasm(db, lockup)
    db.commit()
    assert fresh is not None
    assert fresh.status == LockupStatus.active
    assert fresh.started_at == ended
    assert maybe_relock_after_orgasm(db, lockup) is None


def test_historical_break_rejected_outside_window():
    db = _session()
    dynamic, dom, sub, _user = _couple(db)
    start = datetime(2026, 1, 1, 8, 0)
    end = datetime(2026, 1, 3, 8, 0)
    lockup = ChastityLockup(
        dynamic_id=dynamic.id,
        for_membership_id=sub.id,
        started_by_membership_id=dom.id,
        started_at=start,
        ended_at=end,
        status=LockupStatus.ended,
        ended_kind="unlocked",
    )
    db.add(lockup)
    db.commit()
    try:
        validate_break_times(
            lockup,
            started_at=datetime(2026, 1, 4, 23, 0),
            ended_at=datetime(2026, 1, 5, 7, 0),
        )
        raised = False
    except HTTPException:
        raised = True
    assert raised


def test_goal_history_yellow_when_gift_unmet():
    db = _session()
    dynamic, _dom, sub, _user = _couple(db)
    dynamic.chastity_goals = serialize_goals({
        "goals": [{
            "id": "g1",
            "kind": "ruin_gift",
            "title": "Earned Ruin",
            "for_membership_id": sub.id,
            "requirements": [{"type": "tasks_completed", "value": 3}],
            "start_mode": "rolling_ruin",
            "reset_at": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
            "active": True,
            "repeat_count": 0,
            "history": [],
        }]
    })
    db.add(dynamic)
    db.commit()
    note_orgasm_gift(
        db,
        dynamic,
        sub_id=sub.id,
        occurred_at=datetime.utcnow(),
        tags=["ruined orgasm"],
    )
    db.commit()
    db.refresh(dynamic)
    goals = parse_goals(dynamic.chastity_goals)["goals"]
    assert goals and goals[0]["history"]
    assert goals[0]["history"][-1]["outcome"] == "reset"


def test_advance_due_every_n_days():
    start = datetime(2026, 10, 1, 8, 0)
    nxt = advance_due_date(start, TaskRecurrence.daily, 3)
    assert nxt == datetime(2026, 10, 4, 8, 0)
    weekly = advance_due_date(start, TaskRecurrence.weekly, None)
    assert weekly == datetime(2026, 10, 8, 8, 0)


if __name__ == "__main__":
    test_recurring_completion_counts_for_goal()
    test_inbox_skips_next_day_beyond_reminder()
    test_ruined_does_not_end_cheated_does()
    test_auto_relock_creates_active_lockup()
    test_historical_break_rejected_outside_window()
    test_goal_history_yellow_when_gift_unmet()
    test_advance_due_every_n_days()
    print("test_1_14 ok")
