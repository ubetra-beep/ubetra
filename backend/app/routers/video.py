"""1:1 video calls: REST signaling for WebRTC plus keyholder session controls."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..config import settings
from ..database import get_db
from ..models import Dynamic, Membership, User, VideoCall, VideoCallSignal
from ..schemas import (
    VideoCallControls,
    VideoCallControlsUpdate,
    VideoCallCreate,
    VideoCallCurrentOut,
    VideoCallOut,
    VideoSignalIn,
    VideoSignalOut,
)
from ..services.push import notify_call_push_async
from ..services.settings_policy import is_dominant

router = APIRouter(prefix="/dynamics", tags=["video"])

RING_TIMEOUT_SEC = 90
SIGNAL_KINDS = frozenset({"offer", "answer", "ice", "hangup"})
DEFAULT_CONTROLS = {
    "sensor": False,
    "red_light": False,
    "mute_audio": False,
    "demand_camera": False,
    "demand_screen": False,
    "kiosk_locked": False,
    "hide_chrome": False,
    "disable_touch": False,
    "kiosk_url": "",
    "camera_facing": "",
    "torch": False,
    "torch_level": 0.0,
    "instructor_paused": False,
}


def _ice_servers() -> list[dict]:
    servers: list[dict] = []
    for url in [u.strip() for u in (settings.stun_urls or "").split(",") if u.strip()]:
        servers.append({"urls": url})
    turn = (settings.turn_url or "").strip()
    if turn:
        entry: dict = {"urls": turn}
        if settings.turn_username:
            entry["username"] = settings.turn_username
            entry["credential"] = settings.turn_credential
        servers.append(entry)
    if not servers:
        servers = [{"urls": "stun:stun.l.google.com:19302"}]
    return servers


def _parse_controls(raw: str | None) -> dict:
    data = dict(DEFAULT_CONTROLS)
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            for key, default in DEFAULT_CONTROLS.items():
                if key not in parsed:
                    continue
                if isinstance(default, bool):
                    data[key] = bool(parsed[key])
                elif isinstance(default, float):
                    try:
                        data[key] = max(0.0, min(1.0, float(parsed[key])))
                    except (TypeError, ValueError):
                        pass
                else:
                    data[key] = str(parsed[key] or "")[:120]
    except (TypeError, json.JSONDecodeError):
        pass
    return data


def _member_name(db: Session, membership_id: str) -> str:
    m = db.get(Membership, membership_id)
    return (m.display_name if m else "") or "Partner"


def _partner(db: Session, dynamic_id: str, membership_id: str) -> Membership:
    members = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    for member in members:
        if member.id != membership_id:
            return member
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Video calls need a partner in this dynamic",
    )


def _call_out(db: Session, call: VideoCall, membership: Membership) -> VideoCallOut:
    return VideoCallOut(
        id=call.id,
        status=call.status,
        you_are_caller=call.caller_membership_id == membership.id,
        you_are_dominant=is_dominant(membership),
        caller_name=_member_name(db, call.caller_membership_id),
        callee_name=_member_name(db, call.callee_membership_id),
        controls=VideoCallControls(**_parse_controls(call.controls_json)),
        ice_servers=_ice_servers(),
        created_at=call.created_at,
        answered_at=call.answered_at,
    )


def _expire_stale_rings(db: Session, dynamic_id: str) -> None:
    cutoff = datetime.utcnow() - timedelta(seconds=RING_TIMEOUT_SEC)
    stale = (
        db.query(VideoCall)
        .filter(
            VideoCall.dynamic_id == dynamic_id,
            VideoCall.status == "ringing",
            VideoCall.created_at < cutoff,
        )
        .all()
    )
    now = datetime.utcnow()
    for call in stale:
        call.status = "ended"
        call.ended_at = now


def _active_call(db: Session, dynamic_id: str) -> VideoCall | None:
    _expire_stale_rings(db, dynamic_id)
    return (
        db.query(VideoCall)
        .filter(
            VideoCall.dynamic_id == dynamic_id,
            VideoCall.status.in_(("ringing", "active")),
        )
        .order_by(VideoCall.created_at.desc())
        .first()
    )


def _get_party_call(db: Session, dynamic_id: str, call_id: str, membership: Membership) -> VideoCall:
    call = (
        db.query(VideoCall)
        .filter(VideoCall.id == call_id, VideoCall.dynamic_id == dynamic_id)
        .first()
    )
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    if membership.id not in (call.caller_membership_id, call.callee_membership_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a party to this call")
    return call


@router.get("/{dynamic_id}/video/call", response_model=VideoCallCurrentOut)
def current_video_call(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VideoCallCurrentOut:
    membership = get_membership(dynamic_id, user, db)
    if db.get(Dynamic, dynamic_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    call = _active_call(db, dynamic_id)
    db.commit()
    if call is None:
        return VideoCallCurrentOut(call=None)
    if membership.id not in (call.caller_membership_id, call.callee_membership_id):
        return VideoCallCurrentOut(call=None)
    return VideoCallCurrentOut(call=_call_out(db, call, membership))


@router.post(
    "/{dynamic_id}/video/calls",
    response_model=VideoCallOut,
    status_code=status.HTTP_201_CREATED,
)
def start_video_call(
    dynamic_id: str,
    payload: VideoCallCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> VideoCallOut:
    membership = get_membership(dynamic_id, user, db)
    if db.get(Dynamic, dynamic_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    existing = _active_call(db, dynamic_id)
    if existing is not None:
        if membership.id in (existing.caller_membership_id, existing.callee_membership_id):
            db.commit()
            return _call_out(db, existing, membership)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A call is already in progress",
        )
    partner = _partner(db, dynamic_id, membership.id)
    controls = dict(DEFAULT_CONTROLS)
    if payload.demand_camera:
        controls["demand_camera"] = True
    call = VideoCall(
        dynamic_id=dynamic_id,
        caller_membership_id=membership.id,
        callee_membership_id=partner.id,
        status="ringing",
        controls_json=json.dumps(controls),
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    background_tasks.add_task(
        notify_call_push_async,
        dynamic_id=dynamic_id,
        sender_membership_id=membership.id,
        title="Camera on" if payload.demand_camera else "Incoming video call",
        body=(
            f"{membership.display_name or 'Partner'} turned your camera on"
            if payload.demand_camera
            else f"{membership.display_name or 'Partner'} is calling"
        ),
    )
    return _call_out(db, call, membership)


@router.post("/{dynamic_id}/video/calls/{call_id}/accept", response_model=VideoCallOut)
def accept_video_call(
    dynamic_id: str,
    call_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VideoCallOut:
    membership = get_membership(dynamic_id, user, db)
    call = _get_party_call(db, dynamic_id, call_id, membership)
    if call.status == "ended":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Call already ended")
    if call.callee_membership_id != membership.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the callee can accept")
    if call.status == "ringing":
        call.status = "active"
        call.answered_at = datetime.utcnow()
        db.commit()
        db.refresh(call)
    return _call_out(db, call, membership)


@router.post("/{dynamic_id}/video/calls/{call_id}/end", response_model=VideoCallOut)
def end_video_call(
    dynamic_id: str,
    call_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VideoCallOut:
    membership = get_membership(dynamic_id, user, db)
    call = _get_party_call(db, dynamic_id, call_id, membership)
    if call.status != "ended":
        call.status = "ended"
        call.ended_at = datetime.utcnow()
        call.ended_by_membership_id = membership.id
        db.add(
            VideoCallSignal(
                call_id=call.id,
                sender_membership_id=membership.id,
                kind="hangup",
                payload="{}",
            )
        )
        db.commit()
        db.refresh(call)
    return _call_out(db, call, membership)


@router.patch("/{dynamic_id}/video/calls/{call_id}/controls", response_model=VideoCallOut)
def update_video_controls(
    dynamic_id: str,
    call_id: str,
    payload: VideoCallControlsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VideoCallOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can change call controls",
        )
    call = _get_party_call(db, dynamic_id, call_id, membership)
    if call.status == "ended":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Call already ended")
    controls = _parse_controls(call.controls_json)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key not in DEFAULT_CONTROLS:
            continue
        default = DEFAULT_CONTROLS[key]
        if isinstance(default, bool):
            controls[key] = bool(value)
        elif isinstance(default, float):
            try:
                controls[key] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
        else:
            controls[key] = str(value or "")[:500]
    if controls.get("torch") and not controls.get("torch_level"):
        controls["torch_level"] = 1.0
    if not controls.get("torch"):
        controls["torch_level"] = 0.0
    if "mute_audio" not in updates:
        if controls.get("red_light") and updates.get("red_light") is True:
            controls["mute_audio"] = True
        elif updates.get("red_light") is False:
            controls["mute_audio"] = False
    if controls.get("kiosk_locked"):
        controls["hide_chrome"] = True
        controls["disable_touch"] = True
    call.controls_json = json.dumps(controls)
    db.commit()
    db.refresh(call)
    return _call_out(db, call, membership)


@router.post(
    "/{dynamic_id}/video/calls/{call_id}/signals",
    response_model=VideoSignalOut,
    status_code=status.HTTP_201_CREATED,
)
def post_video_signal(
    dynamic_id: str,
    call_id: str,
    payload: VideoSignalIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VideoSignalOut:
    membership = get_membership(dynamic_id, user, db)
    call = _get_party_call(db, dynamic_id, call_id, membership)
    if call.status == "ended":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Call already ended")
    kind = (payload.kind or "").strip().lower()
    if kind not in SIGNAL_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown signal kind")
    row = VideoCallSignal(
        call_id=call.id,
        sender_membership_id=membership.id,
        kind=kind,
        payload=json.dumps(payload.payload if payload.payload is not None else {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    parsed = json.loads(row.payload) if row.payload else {}
    return VideoSignalOut(id=row.id, kind=row.kind, payload=parsed, created_at=row.created_at)


@router.get(
    "/{dynamic_id}/video/calls/{call_id}/signals",
    response_model=list[VideoSignalOut],
)
def list_video_signals(
    dynamic_id: str,
    call_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    after: str | None = None,
) -> list[VideoSignalOut]:
    membership = get_membership(dynamic_id, user, db)
    call = _get_party_call(db, dynamic_id, call_id, membership)
    rows = (
        db.query(VideoCallSignal)
        .filter(
            VideoCallSignal.call_id == call.id,
            VideoCallSignal.sender_membership_id != membership.id,
        )
        .order_by(VideoCallSignal.created_at.asc())
        .all()
    )
    if after:
        idx = next((i for i, row in enumerate(rows) if row.id == after), None)
        if idx is not None:
            rows = rows[idx + 1 :]
    out: list[VideoSignalOut] = []
    for row in rows:
        try:
            parsed = json.loads(row.payload) if row.payload else {}
        except json.JSONDecodeError:
            parsed = {}
        out.append(
            VideoSignalOut(id=row.id, kind=row.kind, payload=parsed, created_at=row.created_at)
        )
    return out
