"""Wear summary and device pairing checks. Throwaway sqlite only."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.auth import create_access_token, user_from_token
from app.config import settings
from app.database import Base
from app.migrate import ensure_watch_tables
from app.models import (
    ChastityBreak,
    ChastityBreakType,
    ChastityLockup,
    CycleLog,
    Dynamic,
    FeelingCheckIn,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    PartnerRole,
    SleepSession,
    User,
    WatchDevice,
    WatchPairCode,
)
from app.routers.watch import watch_summary
from app.services.watch import (
    claim_pair_code,
    hash_device_secret,
    issue_pair_code,
    list_watch_devices,
    normalize_pair_code,
    refresh_watch_token,
    resolve_api_base,
    revoke_watch_device,
)


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _couple(db, *, features: list[str] | None = None, feelings_mode: str = "soft"):
    dom_user = User(username="watch-dom", email="watch-dom@example.com", password_hash="x")
    sub_user = User(username="watch-sub", email="watch-sub@example.com", password_hash="x")
    db.add_all([dom_user, sub_user])
    db.flush()
    dynamic = Dynamic(
        name="Watch",
        invite_code="WATCH123",
        enabled_features=json.dumps(features) if features is not None else "",
        feelings_prompt_mode=feelings_mode,
    )
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
    return dynamic, dom, sub, dom_user, sub_user


def _ids(actions, membership_id=None):
    chosen = actions
    if membership_id is not None:
        chosen = [item for item in actions if item.for_membership_id == membership_id]
    return {item.id for item in chosen}


def test_summary_role_visibility_and_actions():
    db = _session()
    dynamic, dom, sub, dom_user, sub_user = _couple(
        db,
        features=["chastity", "org_tracking", "sleep_tracking", "cycle_tracking", "feelings"],
    )
    started = datetime.utcnow() - timedelta(hours=2, minutes=5)
    planned = datetime.utcnow() - timedelta(minutes=10)
    lockup = ChastityLockup(
        dynamic_id=dynamic.id,
        for_membership_id=sub.id,
        started_by_membership_id=dom.id,
        started_at=started,
        planned_end_at=planned,
        show_planned_end=False,
        status=LockupStatus.active,
    )
    woke = datetime.utcnow() - timedelta(hours=2)
    slept = woke - timedelta(hours=7, minutes=30)
    db.add(lockup)
    db.add(
        SleepSession(
            dynamic_id=dynamic.id,
            subject_membership_id=sub.id,
            source="manual",
            start_at=slept,
            end_at=woke,
            duration_min=450,
        )
    )
    db.add(
        SleepSession(
            dynamic_id=dynamic.id,
            subject_membership_id=dom.id,
            source="manual",
            start_at=slept,
            end_at=woke,
            duration_min=400,
        )
    )
    today = date.today().isoformat()
    db.add(
        CycleLog(
            dynamic_id=dynamic.id,
            subject_membership_id=sub.id,
            day=today,
            flow="medium",
            source="manual",
        )
    )
    db.add(
        OrgTrackingEntry(
            dynamic_id=dynamic.id,
            logged_by_membership_id=dom.id,
            for_membership_id=sub.id,
            event_type=OrgEventType.orgasm,
            occurred_at=datetime.utcnow() - timedelta(hours=3),
        )
    )
    db.commit()

    sub_view = watch_summary(dynamic.id, sub_user, db)
    dom_view = watch_summary(dynamic.id, dom_user, db)

    assert sub_view.role == "submissive"
    assert sub_view.chastity.enabled is True
    assert len(sub_view.chastity.subjects) == 1
    snap = sub_view.chastity.subjects[0]
    assert snap.state == "locked"
    assert snap.duration_label == "2h 5m"
    assert snap.timer_overdue is True
    assert snap.planned_end_visible is False
    assert snap.planned_end_at is None
    assert "Sub locked for 2h 5m" == sub_view.chastity.summary_label

    dom_snap = dom_view.chastity.subjects[0]
    assert dom_snap.planned_end_visible is True
    assert dom_snap.planned_end_at is not None
    assert dom_snap.timer_overdue is True

    sub_actions = _ids(sub_view.allowed_actions, sub.id)
    assert sub_actions == {"sleep_break", "hygiene_break", "unlock", "log_full", "log_ruined", "log_denied", "log_play"}
    hygiene = next(item for item in sub_view.allowed_actions if item.id == "hygiene_break")
    assert hygiene.body["break_type"] == "emergency_hygiene"
    sleep_break = next(item for item in sub_view.allowed_actions if item.id == "sleep_break")
    assert sleep_break.body["break_type"] == "authorized_sleep"
    unlock = next(item for item in sub_view.allowed_actions if item.id == "unlock")
    assert unlock.body["ended_kind"] == "unlocked"
    assert unlock.finish_on_phone is False
    assert all(item.for_membership_id == sub.id for item in sub_view.allowed_actions)

    dom_actions = _ids(dom_view.allowed_actions, sub.id)
    assert {"extend_1h", "extend_4h", "confirm_release", "unlock", "hygiene_break"} <= dom_actions
    dom_hygiene = next(
        item for item in dom_view.allowed_actions if item.id == "hygiene_break" and item.for_membership_id == sub.id
    )
    assert dom_hygiene.body["break_type"] == "authorized_hygiene"
    assert _ids(dom_view.allowed_actions, dom.id) == {"log_full", "log_ruined", "log_denied", "log_play"}
    extend = next(item for item in dom_view.allowed_actions if item.id == "extend_1h")
    assert extend.method == "PATCH"
    assert extend.path.endswith("/timer/extend")
    assert extend.body == {"hours": 1}

    assert sub_view.sleep.enabled is True
    assert len(sub_view.sleep.nights) == 1
    assert sub_view.sleep.nights[0].membership_id == sub.id
    assert sub_view.sleep.nights[0].duration_label == "7h 30m"
    assert [night.membership_id for night in dom_view.sleep.nights] == [sub.id]

    sub_cycle = next(person for person in sub_view.cycle.people if person.membership_id == sub.id)
    assert sub_view.cycle.enabled is True
    assert sub_cycle.on_period is True
    assert sub_cycle.cycle_day == 1
    assert sub_cycle.today_flow == "medium"
    assert "logs" not in sub_cycle.model_dump()

    assert "Sub: 1" in sub_view.orgasm.recent_orgasm_label
    assert sub_view.orgasm.recent_orgasm_label.endswith("(last 7 days)")
    sub_count = next(partner for partner in sub_view.orgasm.partners if partner.membership_id == sub.id)
    assert sub_count.count_7d == 1
    assert "cumulative_30d" not in sub_view.model_dump()

    lockup.show_planned_end = True
    db.commit()
    shared = watch_summary(dynamic.id, sub_user, db)
    assert shared.chastity.subjects[0].planned_end_visible is True
    assert shared.chastity.subjects[0].planned_end_at is not None

    dynamic.feelings_prompt_mode = "hard"
    db.commit()
    gated = watch_summary(dynamic.id, sub_user, db)
    gated_unlock = next(item for item in gated.allowed_actions if item.id == "unlock")
    gated_log = next(item for item in gated.allowed_actions if item.id == "log_full")
    assert gated_unlock.finish_on_phone is True
    assert gated_log.finish_on_phone is True

    db.add(
        FeelingCheckIn(
            dynamic_id=dynamic.id,
            for_membership_id=sub.id,
            logged_by_membership_id=sub.id,
            context="after_play",
            occurred_at=datetime.utcnow(),
        )
    )
    db.commit()
    after = watch_summary(dynamic.id, sub_user, db)
    assert next(item for item in after.allowed_actions if item.id == "unlock").finish_on_phone is False
    assert next(item for item in after.allowed_actions if item.id == "log_full").finish_on_phone is True
    print("watch summary ok")


def test_break_relock_and_feature_off():
    db = _session()
    dynamic, dom, sub, _dom_user, sub_user = _couple(
        db,
        features=["chastity", "org_tracking"],
    )
    lockup = ChastityLockup(
        dynamic_id=dynamic.id,
        for_membership_id=sub.id,
        started_by_membership_id=dom.id,
        started_at=datetime.utcnow() - timedelta(hours=5),
        status=LockupStatus.active,
    )
    db.add(lockup)
    db.flush()
    db.add(
        ChastityBreak(
            lockup_id=lockup.id,
            break_type=ChastityBreakType.authorized_sleep,
            break_reason="Sleep",
            started_at=datetime.utcnow() - timedelta(minutes=20),
            created_by_membership_id=sub.id,
        )
    )
    db.add(
        SleepSession(
            dynamic_id=dynamic.id,
            subject_membership_id=sub.id,
            source="manual",
            start_at=datetime.utcnow() - timedelta(hours=8),
            end_at=datetime.utcnow() - timedelta(hours=1),
            duration_min=420,
        )
    )
    db.commit()
    view = watch_summary(dynamic.id, sub_user, db)
    assert view.chastity.subjects[0].state == "on_break"
    assert view.chastity.subjects[0].break_label == "Sleep"
    assert "sleep_break" not in _ids(view.allowed_actions)
    assert "relock" in _ids(view.allowed_actions)
    assert "extend_1h" not in _ids(view.allowed_actions)
    assert view.sleep.enabled is False
    assert view.sleep.nights == []
    assert view.cycle.enabled is False
    assert view.cycle.people == []
    print("watch break and feature gates ok")


def test_free_duration_when_unlocked():
    db = _session()
    dynamic, dom, sub, _dom_user, sub_user = _couple(db, features=["chastity"])
    ended = datetime.utcnow() - timedelta(minutes=30)
    db.add(
        ChastityLockup(
            dynamic_id=dynamic.id,
            for_membership_id=sub.id,
            started_by_membership_id=dom.id,
            started_at=ended - timedelta(days=1),
            ended_at=ended,
            status=LockupStatus.ended,
        )
    )
    db.commit()
    view = watch_summary(dynamic.id, sub_user, db)
    snap = view.chastity.subjects[0]
    assert snap.state == "unlocked"
    assert snap.duration_label == "30m"
    assert _ids(view.allowed_actions) == {"lock"}
    assert view.orgasm.enabled is False
    print("watch free duration ok")


def test_pairing_claim_refresh_revoke():
    db = _session()
    user = User(username="watch-phone", email="watch-phone@example.com", password_hash="not-the-token")
    other = User(username="watch-other", email="watch-other@example.com", password_hash="x")
    db.add_all([user, other])
    db.commit()

    try:
        resolve_api_base("javascript:alert(1)")
        raise AssertionError("bad api_base should fail")
    except HTTPException as exc:
        assert exc.status_code == 400
    try:
        resolve_api_base("https://user:secret@example.com")
        raise AssertionError("credentials in api_base should fail")
    except HTTPException as exc:
        assert exc.status_code == 400

    issued = issue_pair_code(db, user, "https://ubetra.example/app/")
    assert issued["api_base"] == "https://ubetra.example/app"
    assert issued["expires_in"] == 300
    stored = (
        db.query(WatchPairCode)
        .filter(WatchPairCode.user_id == user.id, WatchPairCode.consumed_at.is_(None))
        .one()
    )
    assert stored.code_hash == hash_device_secret(normalize_pair_code(issued["code"]))
    assert stored.code_hash != issued["code"]
    assert len(stored.code_hash) == 64

    replaced = issue_pair_code(db, user, None)
    assert replaced["api_base"] == (settings.public_app_url or "").strip().rstrip("/")
    try:
        claim_pair_code(db, issued["code"])
        raise AssertionError("replaced code should not claim")
    except HTTPException as exc:
        assert exc.status_code == 400

    claimed = claim_pair_code(db, replaced["code"], label="Wrist")
    assert claimed["user_id"] == user.id
    assert claimed["api_base"] == replaced["api_base"]
    assert claimed["token_type"] == "bearer"
    assert "password" not in claimed
    assert claimed["access_token"].count(".") == 2
    claims = jwt.decode(claimed["access_token"], settings.secret_key, algorithms=[settings.algorithm])
    remaining = claims["exp"] - time.time()
    assert 11 * 3600 < remaining < 13 * 3600
    assert claims["purpose"] == "watch"
    assert claims["wdid"] == claimed["device_id"]
    assert claims["sub"] == user.id
    assert user_from_token(claimed["access_token"], db).id == user.id
    phone = create_access_token(user.id)
    assert user_from_token(phone, db).id == user.id

    listed = list_watch_devices(db, user)
    assert len(listed) == 1
    assert listed[0]["label"] == "Wrist"
    assert listed[0]["revoked"] is False
    assert "refresh_token" not in listed[0]
    assert "refresh_token_hash" not in listed[0]
    assert "code_hash" not in listed[0]

    try:
        claim_pair_code(db, replaced["code"])
        raise AssertionError("consumed code should not claim again")
    except HTTPException as exc:
        assert exc.status_code == 400

    rotated = refresh_watch_token(db, claimed["refresh_token"])
    assert rotated["device_id"] == claimed["device_id"]
    assert rotated["refresh_token"] != claimed["refresh_token"]
    assert user_from_token(rotated["access_token"], db).id == user.id
    try:
        refresh_watch_token(db, claimed["refresh_token"])
        raise AssertionError("rotated refresh token should fail")
    except HTTPException as exc:
        assert exc.status_code == 401

    device = db.get(WatchDevice, claimed["device_id"])
    device.last_seen_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()
    user_from_token(rotated["access_token"], db)
    seen = db.get(WatchDevice, claimed["device_id"]).last_seen_at
    assert seen is not None and (datetime.utcnow() - seen).total_seconds() < 30

    try:
        revoke_watch_device(db, other, claimed["device_id"])
        raise AssertionError("other user should not revoke")
    except HTTPException as exc:
        assert exc.status_code == 404

    revoked = revoke_watch_device(db, user, claimed["device_id"])
    assert revoked["revoked"] is True
    assert "refresh_token" not in revoked
    try:
        user_from_token(rotated["access_token"], db)
        raise AssertionError("revoked watch token should fail")
    except HTTPException as exc:
        assert exc.status_code == 401
    try:
        refresh_watch_token(db, rotated["refresh_token"])
        raise AssertionError("revoked refresh token should fail")
    except HTTPException as exc:
        assert exc.status_code == 401

    expired = issue_pair_code(db, user, "https://ubetra.example")
    row = (
        db.query(WatchPairCode)
        .filter(WatchPairCode.user_id == user.id, WatchPairCode.consumed_at.is_(None))
        .one()
    )
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    try:
        claim_pair_code(db, expired["code"])
        raise AssertionError("expired code should fail")
    except HTTPException as exc:
        assert exc.status_code == 400
    print("watch pairing ok")


def test_watch_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        ensure_watch_tables(conn)
        names = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        assert "watch_pair_codes" in names
        assert "watch_devices" in names
        ensure_watch_tables(conn)
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(watch_devices)")).fetchall()
        }
    assert "refresh_token_hash" in columns
    assert "revoked_at" in columns
    print("watch migration ok")


def main():
    test_summary_role_visibility_and_actions()
    test_break_relock_and_feature_off()
    test_free_duration_when_unlocked()
    test_pairing_claim_refresh_revoke()
    test_watch_migration_is_idempotent()
    print("watch tests passed")


if __name__ == "__main__":
    main()
