"""Playtime Instructor: local redgifs media, keyholder config, sessions, live overlay."""
from __future__ import annotations

from datetime import datetime
import random
import time
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import (
    Dynamic,
    InstructorSession,
    Membership,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    TaskSource,
    User,
    VaultImage,
)
from ..schemas import (
    InstructorAssignIn,
    InstructorConfigOut,
    InstructorConfigUpdate,
    InstructorLiveOut,
    InstructorLiveUpdate,
    InstructorSessionCreate,
    InstructorSessionEnd,
    InstructorSessionOut,
    TaskListOut,
)
from ..services.chat_events import post_system_event
from ..services.instructor_game import (
    init_live_session,
    media_key,
    merge_live,
    parse_config,
    parse_live,
    save_config,
)
from ..services.redgifs_media import (
    list_playlists,
    mime_for,
    redgifs_root,
    resolve_media_file,
    root_ok,
)
from ..services.settings_policy import is_dominant
from ..services.tags import tags_to_string
from ..services.tasks_service import task_list_out

router = APIRouter()


def _member_name(db: Session, membership_id: str) -> str:
    m = db.get(Membership, membership_id)
    return m.display_name if m else ""


def _session_out(db: Session, row: InstructorSession) -> InstructorSessionOut:
    return InstructorSessionOut(
        id=row.id,
        membership_id=row.membership_id,
        member_name=_member_name(db, row.membership_id),
        title=row.title or "",
        source=row.source or "manual",
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_sec=int(row.duration_sec or 0),
        task_id=row.task_id,
    )


def _config_out(data: dict) -> InstructorConfigOut:
    return InstructorConfigOut.model_validate(data)


def _live_out(data: dict) -> InstructorLiveOut:
    cmd = data.get("command")
    evt = data.get("command_event")
    return InstructorLiveOut(
        paused=bool(data.get("paused")),
        red_light=bool(data.get("red_light")),
        lock_input=bool(data.get("lock_input")),
        force_end=bool(data.get("force_end")),
        mute=bool(data.get("mute")),
        session_id=str(data.get("session_id") or ""),
        media_keys=list(data.get("media_keys") or []),
        media_index=int(data.get("media_index") or 0),
        media_seq=int(data.get("media_seq") or 0),
        media_until=int(data.get("media_until") or 0),
        beat_speed=float(data.get("beat_speed") or 1.0),
        playing=bool(data.get("playing")),
        sub_ready=bool(data.get("sub_ready")),
        command=cmd if isinstance(cmd, dict) else None,
        command_event=evt if isinstance(evt, dict) else None,
        want_camera=bool(data.get("want_camera")),
        want_dom_camera=bool(data.get("want_dom_camera")),
        camera_device_id=str(data.get("camera_device_id") or ""),
        cameras=list(data.get("cameras") or []),
        recording=str(data.get("recording") or "off"),
        beat_epoch_ms=int(data.get("beat_epoch_ms") or 0),
    )


@router.get("/dynamics/{dynamic_id}/vault/redgifs")
def list_redgifs_playlists(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    playlists = list_playlists()
    return {
        "ok": root_ok(),
        "root": str(redgifs_root()),
        "playlists": playlists,
        "empty_message": "No playlists yet. Drop media into subfolders of the shared redgifs directory.",
    }


@router.get("/dynamics/{dynamic_id}/vault/redgifs/{folder}/{filename:path}")
def stream_redgifs_file(
    dynamic_id: str,
    folder: str,
    filename: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    get_membership(dynamic_id, user, db)
    try:
        path = resolve_media_file(folder, filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=mime_for(path),
        filename=path.name,
        headers={"Cache-Control": "private, max-age=120"},
    )


@router.get("/dynamics/{dynamic_id}/instructor/config", response_model=InstructorConfigOut)
def get_instructor_config(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstructorConfigOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return _config_out(parse_config(getattr(dynamic, "instructor_config", None)))


@router.put("/dynamics/{dynamic_id}/instructor/config", response_model=InstructorConfigOut)
def put_instructor_config(
    dynamic_id: str,
    payload: InstructorConfigUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstructorConfigOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    current = parse_config(getattr(dynamic, "instructor_config", None))
    if current.get("locked") and not is_dominant(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keyholder locked this game")
    if not is_dominant(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can edit Instructor")
    data = save_config(dynamic, payload.model_dump(exclude_unset=True))
    db.commit()
    return _config_out(data)


@router.get("/dynamics/{dynamic_id}/instructor/live", response_model=InstructorLiveOut)
def get_instructor_live(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstructorLiveOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return _live_out(parse_live(getattr(dynamic, "instructor_live", None)))


@router.patch("/dynamics/{dynamic_id}/instructor/live", response_model=InstructorLiveOut)
def patch_instructor_live(
    dynamic_id: str,
    payload: InstructorLiveUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstructorLiveOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    body = payload.model_dump(exclude_unset=True)
    dom = is_dominant(membership)
    sub_keys = {
        "sub_ready",
        "playing",
        "force_end",
        "media_index",
        "command_ack",
        "command_failed",
        "advance_media",
        "at_ms",
        "message",
        "reason",
        "cameras",
        "camera_device_id",
    }
    if dom:
        if body.get("command") is not None and isinstance(body["command"], dict):
            body["command"] = dict(body["command"])
        data = merge_live(dynamic, body)
    else:
        allowed = {k: v for k, v in body.items() if k in sub_keys}
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can control the live overlay")
        if allowed.get("command_failed"):
            allowed["reason"] = allowed.get("reason") or "timeout"
        data = merge_live(dynamic, allowed)
    db.commit()
    return _live_out(data)


@router.get("/dynamics/{dynamic_id}/instructor/sessions", response_model=list[InstructorSessionOut])
def list_instructor_sessions(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 40,
) -> list[InstructorSessionOut]:
    membership = get_membership(dynamic_id, user, db)
    q = db.query(InstructorSession).filter(InstructorSession.dynamic_id == dynamic_id)
    if not is_dominant(membership):
        q = q.filter(InstructorSession.membership_id == membership.id)
    rows = q.order_by(InstructorSession.started_at.desc()).limit(max(1, min(limit, 200))).all()
    return [_session_out(db, row) for row in rows]


@router.post(
    "/dynamics/{dynamic_id}/instructor/sessions",
    response_model=InstructorSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def start_instructor_session(
    dynamic_id: str,
    payload: InstructorSessionCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstructorSessionOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    config = parse_config(getattr(dynamic, "instructor_config", None))
    catalog_media = _build_catalog_media(db, dynamic_id, dynamic, membership, config)
    keys = [item["key"] for item in catalog_media]
    random.shuffle(keys)
    stroke_min = float(config.get("stroke_min") or 0.25)
    stroke_max = float(config.get("stroke_max") or 4.0)
    beat_speed = (stroke_min + stroke_max) / 2.0
    row = InstructorSession(
        dynamic_id=dynamic_id,
        membership_id=membership.id,
        title=(payload.title or "Instructor")[:200],
        source=(payload.source or "manual").strip()[:32] or "manual",
        task_id=payload.task_id,
        started_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    init_live_session(
        dynamic,
        session_id=row.id,
        media_keys=keys,
        beat_speed=beat_speed,
        slide_duration=int(config.get("slide_duration") or 10),
    )
    db.commit()
    db.refresh(row)
    return _session_out(db, row)


@router.patch("/dynamics/{dynamic_id}/instructor/sessions/{session_id}", response_model=InstructorSessionOut)
def end_instructor_session(
    dynamic_id: str,
    session_id: str,
    payload: InstructorSessionEnd,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstructorSessionOut:
    membership = get_membership(dynamic_id, user, db)
    row = db.get(InstructorSession, session_id)
    if row is None or row.dynamic_id != dynamic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row.membership_id != membership.id and not is_dominant(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    row.ended_at = datetime.utcnow()
    if payload.title is not None:
        row.title = payload.title[:200]
    if payload.duration_sec is not None:
        row.duration_sec = payload.duration_sec
    else:
        start = row.started_at or row.ended_at
        row.duration_sec = max(0, int((row.ended_at - start).total_seconds()))
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is not None:
        merge_live(dynamic, {
            "force_end": True,
            "paused": False,
            "red_light": False,
            "session_id": "",
            "playing": False,
            "sub_ready": False,
            "command": None,
            "want_camera": False,
            "want_dom_camera": False,
        })
    db.commit()
    db.refresh(row)
    return _session_out(db, row)


def _build_catalog_media(
    db: Session,
    dynamic_id: str,
    dynamic: Dynamic,
    membership: Membership,
    config: dict,
) -> list[dict]:
    playlists = list_playlists()
    selected = set(config.get("playlists") or [])
    if selected:
        playlists = [p for p in playlists if p["id"] in selected]
    wanted = set(config.get("media_kinds") or ["picture", "gif", "video"])

    def _media_kind(name: str, kind: str) -> str:
        lower = (name or "").lower()
        if lower.endswith(".gif") or kind == "gif":
            return "gif"
        if kind == "video" or lower.endswith((".mp4", ".webm", ".mov", ".mkv", ".m4v")):
            return "video"
        return "picture"

    media: list[dict] = []
    for playlist in playlists:
        folder = playlist["id"]
        for item in playlist.get("files") or []:
            kind = _media_kind(item["name"], item["kind"])
            if kind not in wanted:
                continue
            media.append(
                {
                    "key": media_key({"playlist": folder, "name": item["name"]}),
                    "playlist": folder,
                    "playlist_title": playlist["title"],
                    "name": item["name"],
                    "kind": "video" if kind == "video" else "image",
                    "media_type": kind,
                    "size": item["size"],
                    "url": (
                        f"/api/dynamics/{dynamic_id}/vault/redgifs/"
                        f"{quote(folder, safe='')}/{quote(item['name'], safe='')}"
                    ),
                }
            )
    if config.get("include_chat_vault"):
        images = (
            db.query(VaultImage)
            .filter(VaultImage.dynamic_id == dynamic.id)
            .order_by(VaultImage.created_at.desc())
            .limit(80)
            .all()
        )
        for image in images:
            kind = (getattr(image, "media_kind", None) or "image")
            media_type = "video" if kind == "video" else "picture"
            if media_type not in wanted:
                continue
            media.append(
                {
                    "key": media_key({"vault_id": image.id}),
                    "playlist": "vault",
                    "playlist_title": "Chat vault",
                    "name": image.title or image.id,
                    "kind": kind if kind in ("image", "video") else "image",
                    "media_type": media_type,
                    "size": 0,
                    "url": f"vault:{image.id}",
                    "vault_id": image.id,
                    "image_encrypted": image.image_encrypted,
                    "image_blurred": bool(image.image_blurred),
                    "is_yours": image.uploaded_by_membership_id == membership.id,
                }
            )
    return media


@router.get("/dynamics/{dynamic_id}/instructor/catalog")
def instructor_catalog(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    config = parse_config(getattr(dynamic, "instructor_config", None))
    media = _build_catalog_media(db, dynamic_id, dynamic, membership, config)
    for item in media:
        if "key" not in item:
            item["key"] = media_key(item)
    return {
        "ok": root_ok(),
        "config": config,
        "live": parse_live(getattr(dynamic, "instructor_live", None)),
        "media": media,
        "playlists": [{"id": p["id"], "title": p["title"], "count": p["count"]} for p in list_playlists()],
        "empty": not media,
    }


@router.post(
    "/dynamics/{dynamic_id}/instructor/assign-task",
    response_model=TaskListOut,
    status_code=status.HTTP_201_CREATED,
)
def assign_instructor_task(
    dynamic_id: str,
    payload: InstructorAssignIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TaskListOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can assign this")
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    config = parse_config(getattr(dynamic, "instructor_config", None))
    mins = payload.duration_min or int(config.get("duration_min") or 5)
    max_m = int(config.get("duration_max") or mins)
    label = f"Instructor ({mins}–{max_m} min)" if max_m != mins else f"Instructor ({mins} min)"
    target_id = payload.assigned_to_membership_id
    if not target_id:
        partner = (
            db.query(Membership)
            .filter(Membership.dynamic_id == dynamic_id, Membership.role == PartnerRole.submissive)
            .first()
        )
        target_id = partner.id if partner else None
    if not target_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose who to assign")
    task_list = TaskList(
        dynamic_id=dynamic_id,
        title="Instructor",
        created_by_membership_id=membership.id,
    )
    db.add(task_list)
    db.flush()
    db.add(
        Task(
            task_list_id=task_list.id,
            position=0,
            content=label,
            tags=tags_to_string(["Instructor"]),
            approval_status=TaskApprovalStatus.approved,
            source=TaskSource.dom,
            created_by_membership_id=membership.id,
            recurrence=TaskRecurrence.none,
            assigned_to_membership_id=target_id,
            web_url="instructor:",
            web_minutes=mins,
        )
    )
    post_system_event(db, dynamic_id, membership, f"assigned Instructor task ({mins} min)")
    db.commit()
    loaded = (
        db.query(TaskList)
        .options(
            joinedload(TaskList.tasks).joinedload(Task.assigned_to),
            joinedload(TaskList.dynamic).joinedload(Dynamic.memberships),
        )
        .filter(TaskList.id == task_list.id)
        .first()
    )
    return task_list_out(loaded, membership)
