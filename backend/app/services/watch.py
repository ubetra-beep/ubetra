"""Wear OS pairing and the glance summary for one dynamic.

The published watch app does not call this module. It pairs with the phone
and the phone syncs. These helpers stay for older watches that still hold a
device token.

Auth choice
-----------
Claim does not return the account password or the 30-day browser access
token. The phone creates a short-lived pairing code (about five minutes).
The server stores a SHA-256 hash of that code and, after claim, a SHA-256
hash of a per-device refresh token.

Claim and refresh return:

- an access JWT that lasts 12 hours, with the user id in ``sub`` and the
  watch device id in ``wdid`` (``purpose`` is ``watch``)
- a new device refresh token, shown once

``user_from_token`` accepts that access JWT on the existing write routes, so
the watch acts as the paired user. A token that carries ``wdid`` is rejected
as soon as the device row is missing or revoked, including before it expires.
``POST /api/devices/watch/refresh`` rotates the refresh token; the previous
one stops working.

``api_base`` on the pair-code request is the origin the phone fills in for a
self-hosted server. When the phone omits it, the response uses the server's
public app URL as a hint. The same value is returned to the watch on claim.

The summary is a small role-aware snapshot. Feelings hard-gates stay on the
write routes and still return 409. Actions those gates would block are marked
``finish_on_phone`` so the watch can send the person to the phone.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..auth import WATCH_ACCESS_TOKEN_MINUTES, create_watch_access_token
from ..config import settings
from ..models import (
    ChastityBreakType,
    ChastityLockup,
    CycleLog,
    Dynamic,
    LockupStatus,
    Membership,
    PartnerRole,
    SleepSession,
    User,
    WatchDevice,
    WatchPairCode,
)
from ..services.chastity import (
    BREAK_TYPE_LABELS,
    active_break,
    active_lockup,
    effective_locked_seconds,
    is_dominant,
    sub_may_log_break,
)
from ..services.features import is_feature_enabled
from ..services.feelings import feelings_status, has_recent_context_checkin
from ..services.sleep_nights import group_sleep_nights
from ..services.tracking import format_duration, lockup_duration_seconds, recent_orgasm_glance

PAIR_CODE_MINUTES = 5
PAIR_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_device_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_pair_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def resolve_api_base(value: str | None) -> str:
    """Origin or path the watch should call. Empty input uses the public app URL."""
    raw = (value or "").strip()
    if not raw:
        return (settings.public_app_url or "").strip().rstrip("/")
    raw = raw.rstrip("/")
    if len(raw) > 300:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="api_base is too long")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_base must be an http(s) URL",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_base must be an origin or path, without credentials or a query",
        )
    return raw


def _new_pair_code() -> str:
    raw = "".join(secrets.choice(PAIR_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def issue_pair_code(db: Session, user: User, api_base: str | None) -> dict:
    now = datetime.utcnow()
    base = resolve_api_base(api_base)
    db.query(WatchPairCode).filter(WatchPairCode.expires_at < now).delete(synchronize_session=False)
    db.query(WatchPairCode).filter(
        WatchPairCode.user_id == user.id,
        WatchPairCode.consumed_at.is_(None),
    ).update({WatchPairCode.consumed_at: now}, synchronize_session=False)
    code = _new_pair_code()
    expires_at = now + timedelta(minutes=PAIR_CODE_MINUTES)
    db.add(
        WatchPairCode(
            user_id=user.id,
            code_hash=hash_device_secret(normalize_pair_code(code)),
            api_base=base,
            expires_at=expires_at,
            created_at=now,
        )
    )
    db.commit()
    return {
        "code": code,
        "expires_at": expires_at,
        "expires_in": PAIR_CODE_MINUTES * 60,
        "api_base": base,
    }


def claim_pair_code(db: Session, code: str, label: str | None = None) -> dict:
    now = datetime.utcnow()
    normalized = normalize_pair_code(code)
    if len(normalized) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired pairing code")
    row = (
        db.query(WatchPairCode)
        .filter(
            WatchPairCode.code_hash == hash_device_secret(normalized),
            WatchPairCode.consumed_at.is_(None),
            WatchPairCode.expires_at > now,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired pairing code")
    consumed = (
        db.query(WatchPairCode)
        .filter(
            WatchPairCode.id == row.id,
            WatchPairCode.consumed_at.is_(None),
            WatchPairCode.expires_at > now,
        )
        .update({WatchPairCode.consumed_at: now}, synchronize_session=False)
    )
    if consumed != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired pairing code")
    refresh = _new_refresh_token()
    device = WatchDevice(
        user_id=row.user_id,
        label=_clean_label(label),
        refresh_token_hash=hash_device_secret(refresh),
        api_base=row.api_base or "",
        created_at=now,
        last_seen_at=now,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return _token_pair(device, refresh)


def refresh_watch_token(db: Session, refresh_token: str) -> dict:
    now = datetime.utcnow()
    presented = (refresh_token or "").strip()
    if len(presented) < 10:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Watch access revoked")
    old_hash = hash_device_secret(presented)
    device = (
        db.query(WatchDevice)
        .filter(
            WatchDevice.refresh_token_hash == old_hash,
            WatchDevice.revoked_at.is_(None),
        )
        .first()
    )
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Watch access revoked")
    refresh = _new_refresh_token()
    rotated = (
        db.query(WatchDevice)
        .filter(
            WatchDevice.id == device.id,
            WatchDevice.refresh_token_hash == old_hash,
            WatchDevice.revoked_at.is_(None),
        )
        .update(
            {
                WatchDevice.refresh_token_hash: hash_device_secret(refresh),
                WatchDevice.last_seen_at: now,
            },
            synchronize_session=False,
        )
    )
    if rotated != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Watch access revoked")
    db.commit()
    db.refresh(device)
    return _token_pair(device, refresh)


def revoke_watch_device(db: Session, user: User, device_id: str) -> dict:
    device = db.get(WatchDevice, (device_id or "").strip())
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watch not found")
    if device.revoked_at is None:
        device.revoked_at = datetime.utcnow()
        device.refresh_token_hash = None
        db.add(device)
        db.commit()
        db.refresh(device)
    return device_public(device)


def list_watch_devices(db: Session, user: User) -> list[dict]:
    rows = (
        db.query(WatchDevice)
        .filter(WatchDevice.user_id == user.id)
        .order_by(WatchDevice.created_at.desc())
        .all()
    )
    return [device_public(row) for row in rows]


def device_public(row: WatchDevice) -> dict:
    return {
        "id": row.id,
        "label": row.label or "Wear OS",
        "created_at": row.created_at,
        "last_seen_at": row.last_seen_at,
        "revoked_at": row.revoked_at,
        "revoked": row.revoked_at is not None,
    }


def _token_pair(device: WatchDevice, refresh: str) -> dict:
    return {
        "device_id": device.id,
        "user_id": device.user_id,
        "access_token": create_watch_access_token(device.user_id, device.id),
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": WATCH_ACCESS_TOKEN_MINUTES * 60,
        "api_base": device.api_base or "",
    }


def _clean_label(label: str | None) -> str:
    cleaned = " ".join((label or "").split())[:64]
    return cleaned or "Wear OS"


def build_watch_summary(db: Session, dynamic_id: str, caller: Membership) -> dict:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    members = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    chastity_on = is_feature_enabled(dynamic, "chastity")
    sleep_on = is_feature_enabled(dynamic, "sleep_tracking")
    cycle_on = is_feature_enabled(dynamic, "cycle_tracking")
    orgasm_on = is_feature_enabled(dynamic, "org_tracking")
    actions: list[dict] = []
    if chastity_on:
        subjects = _chastity_subjects(caller, members)
        chastity_rows = [_chastity_subject(db, dynamic_id, caller, subject) for subject in subjects]
        actions.extend(_chastity_actions(db, dynamic, caller, chastity_rows))
        chastity = {
            "enabled": True,
            "summary_label": _chastity_summary_label(chastity_rows),
            "subjects": [_public_subject(row) for row in chastity_rows],
        }
    else:
        chastity = {
            "enabled": False,
            "summary_label": "Chastity is off",
            "subjects": [],
        }
    if orgasm_on:
        actions.extend(_log_actions(db, dynamic, caller, members))
        glance = recent_orgasm_glance(db, dynamic_id, members)
        orgasm = {
            "enabled": True,
            "recent_orgasm_label": glance["recent_orgasm_label"],
            "partners": [
                {
                    "membership_id": partner["membership_id"],
                    "name": partner["name"],
                    "count_7d": partner["orgasm_count"],
                }
                for partner in glance["partners"]
            ],
        }
    else:
        orgasm = {"enabled": False, "recent_orgasm_label": "", "partners": []}
    return {
        "dynamic_id": dynamic_id,
        "role": caller.role.value,
        "you_membership_id": caller.id,
        "display_name": caller.display_name,
        "chastity": chastity,
        "sleep": _sleep_block(db, dynamic_id, caller, members, enabled=sleep_on),
        "cycle": _cycle_block(db, dynamic_id, caller, members, enabled=cycle_on),
        "orgasm": orgasm,
        "allowed_actions": actions,
        "generated_at": datetime.utcnow(),
    }


def _chastity_subjects(caller: Membership, members: list[Membership]) -> list[Membership]:
    subs = [member for member in members if member.role == PartnerRole.submissive]
    if is_dominant(caller):
        return sorted(subs, key=lambda member: member.display_name.lower())
    return [member for member in subs if member.id == caller.id]


def _chastity_subject(db: Session, dynamic_id: str, caller: Membership, subject: Membership) -> dict:
    if not subject.chastity_enabled:
        return {
            "membership_id": subject.id,
            "name": subject.display_name,
            "chastity_enabled": False,
            "state": "not_tracked",
            "duration_label": None,
            "timer_overdue": False,
            "planned_end_visible": False,
            "planned_end_at": None,
            "active_lockup_id": None,
            "active_break_id": None,
            "break_label": None,
            "lockup": None,
            "break": None,
        }
    now = datetime.utcnow()
    lockup = active_lockup(db, dynamic_id, subject.id)
    brk = active_break(lockup) if lockup else None
    state = "unlocked"
    duration_label = None
    if lockup and brk:
        state = "on_break"
        duration_label = format_duration(lockup_duration_seconds(brk.started_at, now))
    elif lockup:
        state = "locked"
        duration_label = format_duration(effective_locked_seconds(lockup, until=now))
    else:
        last_ended = (
            db.query(ChastityLockup)
            .filter(
                ChastityLockup.dynamic_id == dynamic_id,
                ChastityLockup.for_membership_id == subject.id,
                ChastityLockup.status == LockupStatus.ended,
                ChastityLockup.ended_at.isnot(None),
            )
            .order_by(ChastityLockup.ended_at.desc())
            .first()
        )
        if last_ended and last_ended.ended_at:
            duration_label = format_duration(lockup_duration_seconds(last_ended.ended_at, now))
    planned_end_at = lockup.planned_end_at if lockup else None
    timer_overdue = bool(
        lockup
        and lockup.status == LockupStatus.active
        and planned_end_at
        and planned_end_at <= now
    )
    visible = bool(lockup and planned_end_at and (is_dominant(caller) or lockup.show_planned_end))
    return {
        "membership_id": subject.id,
        "name": subject.display_name,
        "chastity_enabled": True,
        "state": state,
        "duration_label": duration_label,
        "timer_overdue": timer_overdue,
        "planned_end_visible": visible,
        "planned_end_at": planned_end_at if visible else None,
        "active_lockup_id": lockup.id if lockup else None,
        "active_break_id": brk.id if brk else None,
        "break_label": BREAK_TYPE_LABELS.get(brk.break_type.value, brk.break_type.value) if brk else None,
        "lockup": lockup,
        "break": brk,
    }


def _public_subject(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in {"lockup", "break"}}


def _chastity_summary_label(rows: list[dict]) -> str:
    tracked = [row for row in rows if row["chastity_enabled"]]
    if not tracked:
        return "Chastity not enabled for any submissive"
    locked = next((row for row in tracked if row["state"] == "locked"), None)
    if locked:
        return f"{locked['name']} locked for {locked['duration_label']}"
    on_break = next((row for row in tracked if row["state"] == "on_break"), None)
    if on_break:
        return f"{on_break['name']} on break for {on_break['duration_label']}"
    free = next((row for row in tracked if row["duration_label"]), None)
    if free:
        return f"{free['name']} free for {free['duration_label']}"
    return "No lockup history yet"


def _finish_on_phone(db: Session, dynamic: Dynamic, caller: Membership, context: str) -> bool:
    info = feelings_status(db, dynamic.id, caller, dynamic)
    if not info.get("hard_gate_active"):
        return False
    return not has_recent_context_checkin(
        db, dynamic.id, caller.id, context, within_hours=12
    )


def _action(
    *,
    action_id: str,
    label: str,
    method: str,
    path: str,
    for_membership_id: str,
    subject_name: str,
    finish_on_phone: bool = False,
    body: dict | None = None,
) -> dict:
    return {
        "id": action_id,
        "label": label,
        "method": method,
        "path": path,
        "for_membership_id": for_membership_id,
        "subject_name": subject_name,
        "finish_on_phone": finish_on_phone,
        "body": body,
    }


def _named(base: str, name: str, multiple: bool) -> str:
    if multiple and name:
        return f"{base} · {name}"
    return base


def _chastity_actions(db: Session, dynamic: Dynamic, caller: Membership, rows: list[dict]) -> list[dict]:
    actionable = [row for row in rows if row["chastity_enabled"]]
    multiple = len(actionable) > 1
    phone_after = _finish_on_phone(db, dynamic, caller, "after_play")
    actions: list[dict] = []
    dominant = is_dominant(caller)
    for row in actionable:
        subject_id = row["membership_id"]
        name = row["name"]
        lockup = row["lockup"]
        brk = row["break"]
        base = f"/api/dynamics/{dynamic.id}/chastity"
        if lockup is None:
            actions.append(
                _action(
                    action_id="lock",
                    label=_named("Lock", name, multiple),
                    method="POST",
                    path=f"{base}/start",
                    for_membership_id=subject_id,
                    subject_name=name,
                    body={"for_membership_id": subject_id},
                )
            )
            continue
        if brk is None:
            _append_break_action(
                actions,
                caller=caller,
                subject_id=subject_id,
                name=name,
                multiple=multiple,
                break_type=ChastityBreakType.authorized_sleep,
                action_id="sleep_break",
                label=_named("Sleep break", name, multiple),
                path=f"{base}/{lockup.id}/break",
            )
            hygiene = (
                ChastityBreakType.authorized_hygiene
                if dominant
                else ChastityBreakType.emergency_hygiene
            )
            _append_break_action(
                actions,
                caller=caller,
                subject_id=subject_id,
                name=name,
                multiple=multiple,
                break_type=hygiene,
                action_id="hygiene_break",
                label=_named("Hygiene break", name, multiple),
                path=f"{base}/{lockup.id}/break",
            )
        else:
            actions.append(
                _action(
                    action_id="relock",
                    label=_named("Relock", name, multiple),
                    method="PATCH",
                    path=f"{base}/{lockup.id}/break/{brk.id}/finish",
                    for_membership_id=subject_id,
                    subject_name=name,
                )
            )
        actions.append(
            _action(
                action_id="unlock",
                label=_named("Unlock", name, multiple),
                method="PATCH",
                path=f"{base}/{lockup.id}/end",
                for_membership_id=subject_id,
                subject_name=name,
                finish_on_phone=phone_after,
                body={"ended_kind": "unlocked"},
            )
        )
        if dominant:
            for hours, action_id, label in (
                (1, "extend_1h", "Extend +1h"),
                (4, "extend_4h", "Extend +4h"),
            ):
                actions.append(
                    _action(
                        action_id=action_id,
                        label=_named(label, name, multiple),
                        method="PATCH",
                        path=f"{base}/{lockup.id}/timer/extend",
                        for_membership_id=subject_id,
                        subject_name=name,
                        body={"hours": hours},
                    )
                )
            if row["timer_overdue"]:
                actions.append(
                    _action(
                        action_id="confirm_release",
                        label=_named("Confirm release", name, multiple),
                        method="PATCH",
                        path=f"{base}/{lockup.id}/timer/release",
                        for_membership_id=subject_id,
                        subject_name=name,
                    )
                )
    return actions


def _append_break_action(
    actions: list[dict],
    *,
    caller: Membership,
    subject_id: str,
    name: str,
    multiple: bool,
    break_type: ChastityBreakType,
    action_id: str,
    label: str,
    path: str,
) -> None:
    if not sub_may_log_break(
        is_dominant_member=is_dominant(caller),
        is_subject=caller.id == subject_id,
        break_type=break_type,
    ):
        return
    actions.append(
        _action(
            action_id=action_id,
            label=label,
            method="POST",
            path=path,
            for_membership_id=subject_id,
            subject_name=name,
            body={"break_type": break_type.value},
        )
    )


def _log_targets(caller: Membership, members: list[Membership]) -> list[Membership]:
    if is_dominant(caller):
        return sorted(members, key=lambda member: (member.id != caller.id, member.display_name.lower()))
    return [caller]


def _log_actions(db: Session, dynamic: Dynamic, caller: Membership, members: list[Membership]) -> list[dict]:
    targets = _log_targets(caller, members)
    multiple = len(targets) > 1
    phone_before = _finish_on_phone(db, dynamic, caller, "before_play")
    path = f"/api/dynamics/{dynamic.id}/tracking"
    specs = (
        ("log_full", "Log full", "orgasm", ["full orgasm"], True),
        ("log_ruined", "Log ruined", "orgasm", ["ruined orgasm"], True),
        ("log_denied", "Log denied", "no_orgasm", ["denied"], False),
        ("log_play", "Log play", "no_orgasm", [], False),
    )
    actions: list[dict] = []
    for target in targets:
        for action_id, label, event_type, tags, with_orgasm in specs:
            body: dict = {
                "for_membership_id": target.id,
                "event_type": event_type,
                "tags": list(tags),
                "orgasms": [{"tags": list(tags)}] if with_orgasm else [],
            }
            actions.append(
                _action(
                    action_id=action_id,
                    label=_named(label, target.display_name, multiple),
                    method="POST",
                    path=path,
                    for_membership_id=target.id,
                    subject_name=target.display_name,
                    finish_on_phone=phone_before,
                    body=body,
                )
            )
    return actions


def _sleep_block(
    db: Session,
    dynamic_id: str,
    caller: Membership,
    members: list[Membership],
    *,
    enabled: bool,
) -> dict:
    if not enabled:
        return {"enabled": False, "nights": []}
    if is_dominant(caller):
        subjects = [member for member in members if member.id != caller.id]
    else:
        subjects = [caller]
    subjects = sorted(subjects, key=lambda member: member.display_name.lower())
    nights = []
    since = datetime.utcnow() - timedelta(hours=36)
    for subject in subjects:
        recent = (
            db.query(SleepSession)
            .filter(
                SleepSession.dynamic_id == dynamic_id,
                SleepSession.subject_membership_id == subject.id,
                SleepSession.end_at >= since,
            )
            .order_by(SleepSession.end_at.desc())
            .limit(12)
            .all()
        )
        grouped = group_sleep_nights(recent)
        night = max(grouped, key=lambda item: item.end_at) if grouped else None
        nights.append(
            {
                "membership_id": subject.id,
                "name": subject.display_name,
                "is_you": subject.id == caller.id,
                "night_date": night.night_date if night else None,
                "duration_min": night.duration_min if night else None,
                "duration_label": format_duration(night.duration_min * 60) if night else None,
                "start_at": night.start_at if night else None,
                "end_at": night.end_at if night else None,
            }
        )
    return {"enabled": True, "nights": nights}


def _cycle_block(
    db: Session,
    dynamic_id: str,
    caller: Membership,
    members: list[Membership],
    *,
    enabled: bool,
) -> dict:
    if not enabled:
        return {"enabled": False, "people": []}
    from ..routers.cycle import summarize_cycle

    logs = db.query(CycleLog).filter(CycleLog.dynamic_id == dynamic_id).all()
    today = date.today().isoformat()
    people = []
    ordered = sorted(members, key=lambda member: (member.id != caller.id, member.display_name.lower()))
    for member in ordered:
        mine = [row for row in logs if row.subject_membership_id == member.id]
        summary = summarize_cycle(mine)
        today_row = next((row for row in mine if row.day == today), None)
        people.append(
            {
                "membership_id": member.id,
                "name": member.display_name,
                "is_you": member.id == caller.id,
                "cycle_day": summary.cycle_day,
                "on_period": summary.on_period,
                "last_period_start": summary.last_period_start,
                "predicted_next": summary.predicted_next,
                "typical_length": summary.typical_length,
                "period_length": summary.period_length,
                "today_flow": (today_row.flow if today_row else "") or "",
            }
        )
    return {"enabled": True, "people": people}
