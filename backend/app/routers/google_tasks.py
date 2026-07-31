from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..config import settings
from ..database import get_db
from ..models import Dynamic, User
from ..schemas import GoogleTasksStatusOut, GoogleTasksSyncOut
from ..services.google_tasks import (
    build_auth_url,
    exchange_code_for_tokens,
    google_oauth_configured,
    pull_completions_from_google,
    push_open_tasks,
    sync_target_user,
)

router = APIRouter(prefix="/google", tags=["google-tasks"])

_pending_states: dict[str, str] = {}


@router.get("/status", response_model=GoogleTasksStatusOut)
def google_tasks_status(
    user: Annotated[User, Depends(get_current_user)],
) -> GoogleTasksStatusOut:
    return GoogleTasksStatusOut(
        configured=google_oauth_configured(),
        connected=bool((user.google_refresh_token or "").strip()),
        list_id=(user.google_tasks_list_id or "@default"),
    )


@router.get("/connect")
def google_connect(
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    state = secrets.token_urlsafe(24)
    _pending_states[state] = user.id
    return {"auth_url": build_auth_url(state=state)}


@router.get("/callback")
def google_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    app_url = settings.public_app_url.rstrip("/")
    if error:
        return RedirectResponse(f"{app_url}/#/settings?google=error&detail={quote(error)}")
    if not code or not state or state not in _pending_states:
        return RedirectResponse(f"{app_url}/#/settings?google=error")

    user_id = _pending_states.pop(state)
    user = db.get(User, user_id)
    if user is None:
        return RedirectResponse(f"{app_url}/#/settings?google=error")

    try:
        tokens = exchange_code_for_tokens(code)
    except HTTPException:
        return RedirectResponse(f"{app_url}/#/settings?google=error")

    refresh = (tokens.get("refresh_token") or "").strip()
    if refresh:
        user.google_refresh_token = refresh
    elif not (user.google_refresh_token or "").strip():
        return RedirectResponse(f"{app_url}/#/settings?google=error&detail=no_refresh_token")
    if not (user.google_tasks_list_id or "").strip():
        user.google_tasks_list_id = "@default"
    db.commit()
    return RedirectResponse(f"{app_url}/#/settings?google=connected")


@router.delete("/disconnect", response_model=GoogleTasksStatusOut)
def google_disconnect(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GoogleTasksStatusOut:
    user.google_refresh_token = ""
    db.commit()
    return google_tasks_status(user)


@router.post("/dynamics/{dynamic_id}/sync", response_model=GoogleTasksSyncOut)
def sync_google_tasks(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GoogleTasksSyncOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    owner = sync_target_user(db, dynamic_id, user)
    errors: list[str] = []
    pushed = 0
    completed = 0
    try:
        completed = pull_completions_from_google(db, owner=owner, dynamic_id=dynamic_id)
        pushed = push_open_tasks(db, owner=owner, actor=user, dynamic=dynamic)
        db.commit()
    except HTTPException as exc:
        db.rollback()
        errors.append(str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        errors.append(str(exc))

    return GoogleTasksSyncOut(
        pushed=pushed,
        completed_from_google=completed,
        errors=errors,
    )


@router.put("/list-id")
def set_google_list_id(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    list_id: Annotated[str, Query(min_length=1, max_length=128)] = "@default",
) -> GoogleTasksStatusOut:
    user.google_tasks_list_id = list_id.strip() or "@default"
    db.commit()
    return google_tasks_status(user)
