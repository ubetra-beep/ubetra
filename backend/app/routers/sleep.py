from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..config import settings
from ..database import get_db
from ..models import Dynamic, SleepSession, User
from ..services.features import is_feature_enabled
from ..services.sleep_sync import (
    build_garmin_auth_url,
    build_google_sleep_auth_url,
    garmin_configured,
    google_fitness_configured,
    import_apple_sessions,
    pop_oauth_state,
    store_garmin_tokens,
    store_google_sleep_tokens,
    sync_garmin_sleep,
    sync_google_sleep,
    _exchange_garmin_code,
    _exchange_google_code,
)

router = APIRouter(prefix="/dynamics", tags=["sleep"])


class SleepSessionOut(BaseModel):
    id: str
    source: str
    start_at: datetime
    end_at: datetime
    duration_min: int
    sleep_score: int | None = None
    notes: str = ""
    stages_json: str = ""
    synced_at: datetime | None = None

    class Config:
        from_attributes = True


class SleepManualCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    sleep_score: int | None = None
    notes: str = ""


class SleepAppleImport(BaseModel):
    sessions: list[dict] = Field(default_factory=list)


class SleepStatusOut(BaseModel):
    feature_enabled: bool
    google_configured: bool
    google_connected: bool
    garmin_configured: bool
    garmin_connected: bool
    apple_connected: bool
    apple_native_required: bool = True


class SleepSyncOut(BaseModel):
    imported: int
    source: str


def _require_sleep(dynamic: Dynamic) -> None:
    if not is_feature_enabled(dynamic, "sleep_tracking"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sleep tracking is not enabled for this dynamic.",
        )


@router.get("/{dynamic_id}/sleep/status", response_model=SleepStatusOut)
def sleep_status(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SleepStatusOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    return SleepStatusOut(
        feature_enabled=is_feature_enabled(dynamic, "sleep_tracking"),
        google_configured=google_fitness_configured(),
        google_connected=bool((user.google_refresh_token or "").strip())
        and (
            "fitness.sleep" in (user.google_fitness_scopes or "")
            or bool((user.google_fitness_scopes or "").strip())
        ),
        garmin_configured=garmin_configured(),
        garmin_connected=bool((user.garmin_access_token or "").strip()),
        apple_connected=bool(user.apple_health_connected),
        apple_native_required=True,
    )


@router.get("/{dynamic_id}/sleep", response_model=list[SleepSessionOut])
def list_sleep(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SleepSessionOut]:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_sleep(dynamic)
    rows = (
        db.query(SleepSession)
        .filter(SleepSession.dynamic_id == dynamic_id)
        .order_by(SleepSession.start_at.desc())
        .limit(60)
        .all()
    )
    return [SleepSessionOut.model_validate(r) for r in rows]


@router.post("/{dynamic_id}/sleep", response_model=SleepSessionOut)
def create_manual_sleep(
    dynamic_id: str,
    payload: SleepManualCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SleepSessionOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_sleep(dynamic)
    if payload.end_at <= payload.start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")
    duration = int((payload.end_at - payload.start_at).total_seconds() // 60)
    row = SleepSession(
        dynamic_id=dynamic_id,
        subject_membership_id=membership.id,
        source="manual",
        start_at=payload.start_at,
        end_at=payload.end_at,
        duration_min=duration,
        sleep_score=payload.sleep_score,
        notes=(payload.notes or "").strip(),
        synced_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return SleepSessionOut.model_validate(row)


@router.delete("/{dynamic_id}/sleep/{session_id}")
def delete_sleep(
    dynamic_id: str,
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_sleep(dynamic)
    row = db.get(SleepSession, session_id)
    if row is None or row.dynamic_id != dynamic_id:
        raise HTTPException(status_code=404, detail="Not found")
    if row.subject_membership_id != membership.id:
        raise HTTPException(status_code=403, detail="You can only delete your own sleep entries")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/{dynamic_id}/sleep/google/connect")
def google_sleep_connect(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    return {"auth_url": build_google_sleep_auth_url(user_id=user.id, dynamic_id=dynamic_id)}


@router.post("/{dynamic_id}/sleep/google/sync", response_model=SleepSyncOut)
def google_sleep_sync(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SleepSyncOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_sleep(dynamic)
    imported = sync_google_sleep(db, user=user, membership=membership, dynamic_id=dynamic_id)
    db.commit()
    return SleepSyncOut(imported=imported, source="google")


@router.get("/{dynamic_id}/sleep/garmin/connect")
def garmin_sleep_connect(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    return {"auth_url": build_garmin_auth_url(user_id=user.id, dynamic_id=dynamic_id)}


@router.post("/{dynamic_id}/sleep/garmin/sync", response_model=SleepSyncOut)
def garmin_sleep_sync(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SleepSyncOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_sleep(dynamic)
    imported = sync_garmin_sleep(db, user=user, membership=membership, dynamic_id=dynamic_id)
    db.commit()
    return SleepSyncOut(imported=imported, source="garmin")


@router.post("/{dynamic_id}/sleep/apple/import", response_model=SleepSyncOut)
def apple_sleep_import(
    dynamic_id: str,
    payload: SleepAppleImport,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SleepSyncOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_sleep(dynamic)
    imported = import_apple_sessions(
        db,
        membership=membership,
        dynamic_id=dynamic_id,
        sessions=payload.sessions,
    )
    user.apple_health_connected = True
    db.commit()
    return SleepSyncOut(imported=imported, source="apple")


# OAuth callbacks live at /api/sleep/... (mounted separately)
callback_router = APIRouter(prefix="/sleep", tags=["sleep-oauth"])


@callback_router.get("/google/callback")
def google_sleep_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    app_url = settings.public_app_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{app_url}/#/settings?sleep=google_error&detail={quote(error or 'missing')}")
    pending = pop_oauth_state(state)
    if not pending or pending.get("provider") != "google":
        return RedirectResponse(f"{app_url}/#/settings?sleep=google_error")
    user = db.get(User, pending["user_id"])
    if user is None:
        return RedirectResponse(f"{app_url}/#/settings?sleep=google_error")
    try:
        tokens = _exchange_google_code(code)
        store_google_sleep_tokens(user, tokens)
        db.commit()
    except Exception:
        return RedirectResponse(f"{app_url}/#/settings?sleep=google_error")
    dyn = pending.get("dynamic_id") or ""
    return RedirectResponse(f"{app_url}/#/dynamic/{dyn}/sleep?sleep=google_ok")


@callback_router.get("/garmin/callback")
def garmin_sleep_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    app_url = settings.public_app_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{app_url}/#/settings?sleep=garmin_error")
    pending = pop_oauth_state(state)
    if not pending or pending.get("provider") != "garmin":
        return RedirectResponse(f"{app_url}/#/settings?sleep=garmin_error")
    user = db.get(User, pending["user_id"])
    if user is None:
        return RedirectResponse(f"{app_url}/#/settings?sleep=garmin_error")
    try:
        tokens = _exchange_garmin_code(code)
        store_garmin_tokens(user, tokens)
        db.commit()
    except Exception:
        return RedirectResponse(f"{app_url}/#/settings?sleep=garmin_error")
    dyn = pending.get("dynamic_id") or ""
    return RedirectResponse(f"{app_url}/#/dynamic/{dyn}/sleep?sleep=garmin_ok")
