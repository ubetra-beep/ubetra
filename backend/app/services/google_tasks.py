from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import (
    Dynamic,
    Membership,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    User,
)
from .llm import generate_text, is_llm_configured
from .tasks_service import schedule_next_occurrence

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TASKS_BASE = "https://tasks.googleapis.com/tasks/v1"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"


def google_oauth_configured() -> bool:
    return bool(settings.google_client_id.strip() and settings.google_client_secret.strip())


def build_auth_url(*, state: str) -> str:
    if not google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Tasks is not configured. Set UBETRA_GOOGLE_CLIENT_ID and UBETRA_GOOGLE_CLIENT_SECRET.",
        )
    params = {
        "client_id": settings.google_client_id.strip(),
        "redirect_uri": settings.google_redirect_uri.strip(),
        "response_type": "code",
        "scope": TASKS_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    data: dict | None = None,
    form: dict | None = None,
) -> dict:
    body = None
    req_headers = dict(headers or {})
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google API error ({exc.code}): {detail[:300]}",
        ) from exc


def exchange_code_for_tokens(code: str) -> dict:
    return _http_json(
        "POST",
        GOOGLE_TOKEN_URL,
        form={
            "code": code,
            "client_id": settings.google_client_id.strip(),
            "client_secret": settings.google_client_secret.strip(),
            "redirect_uri": settings.google_redirect_uri.strip(),
            "grant_type": "authorization_code",
        },
    )


def refresh_access_token(user: User) -> str:
    if not (user.google_refresh_token or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Google Tasks in Settings first.",
        )
    payload = _http_json(
        "POST",
        GOOGLE_TOKEN_URL,
        form={
            "client_id": settings.google_client_id.strip(),
            "client_secret": settings.google_client_secret.strip(),
            "refresh_token": user.google_refresh_token.strip(),
            "grant_type": "refresh_token",
        },
    )
    token = (payload.get("access_token") or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not refresh Google access token.",
        )
    return token


def _list_id(user: User) -> str:
    return (user.google_tasks_list_id or "@default").strip() or "@default"


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def generate_public_code_word(
    *,
    user: User,
    dynamic: Dynamic,
    content: str,
) -> str:
    if not is_llm_configured(user, dynamic):
        words = [w for w in content.split() if w.isalpha()]
        return " ".join(words[:3]).title() or "Personal errand"

    prompt = f"""Convert this private task into a short, innocent, G-rated code phrase for a normal todo list.

Rules:
- No sexual, BDSM, kink, body, or suggestive language
- Sound like a mundane errand, chore, or reminder
- 2–6 words max
- Return ONLY the code phrase, nothing else

Private task:
{content.strip()}
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context="Create a discreet public label only.",
        dynamic=dynamic,
        system_instruction=(
            "You invent innocent code words for private tasks. "
            "Never include adult or kink content. Reply with only the code phrase."
        ),
    )
    line = (raw or "").strip().splitlines()[0].strip().strip("\"'")
    return line[:200] or "Personal errand"


def push_task_to_google(
    db: Session,
    *,
    owner: User,
    actor: User,
    dynamic: Dynamic,
    task: Task,
) -> None:
    if not google_oauth_configured() or not (owner.google_refresh_token or "").strip():
        return
    if task.approval_status != TaskApprovalStatus.approved:
        return
    if task.completed_at is not None:
        return

    if not (task.public_code_word or "").strip():
        task.public_code_word = generate_public_code_word(
            user=actor,
            dynamic=dynamic,
            content=task.content,
        )

    access = refresh_access_token(owner)
    list_id = urllib.parse.quote(_list_id(owner), safe="")
    due = task.next_due_at or task.due_at
    body: dict = {
        "title": task.public_code_word.strip(),
        "notes": "UBETRA discreet task",
    }
    if due is not None:
        body["due"] = due.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    if (task.google_task_id or "").strip():
        task_id = urllib.parse.quote(task.google_task_id.strip(), safe="")
        _http_json(
            "PATCH",
            f"{GOOGLE_TASKS_BASE}/lists/{list_id}/tasks/{task_id}",
            headers=_auth_headers(access),
            data=body,
        )
        return

    created = _http_json(
        "POST",
        f"{GOOGLE_TASKS_BASE}/lists/{list_id}/tasks",
        headers=_auth_headers(access),
        data=body,
    )
    task.google_task_id = (created.get("id") or "").strip()


def complete_google_task(owner: User, task: Task) -> None:
    if not (task.google_task_id or "").strip():
        return
    if not google_oauth_configured() or not (owner.google_refresh_token or "").strip():
        return
    access = refresh_access_token(owner)
    list_id = urllib.parse.quote(_list_id(owner), safe="")
    task_id = urllib.parse.quote(task.google_task_id.strip(), safe="")
    _http_json(
        "PATCH",
        f"{GOOGLE_TASKS_BASE}/lists/{list_id}/tasks/{task_id}",
        headers=_auth_headers(access),
        data={"status": "completed"},
    )


def _submissive_user(db: Session, dynamic_id: str) -> User | None:
    membership = (
        db.query(Membership)
        .options(joinedload(Membership.user))
        .filter(
            Membership.dynamic_id == dynamic_id,
            Membership.role == PartnerRole.submissive,
        )
        .first()
    )
    return membership.user if membership else None


def sync_target_user(db: Session, dynamic_id: str, fallback: User) -> User:
    sub = _submissive_user(db, dynamic_id)
    if sub and (sub.google_refresh_token or "").strip():
        return sub
    if (fallback.google_refresh_token or "").strip():
        return fallback
    return sub or fallback


def pull_completions_from_google(
    db: Session,
    *,
    owner: User,
    dynamic_id: str,
) -> int:
    if not google_oauth_configured() or not (owner.google_refresh_token or "").strip():
        return 0

    access = refresh_access_token(owner)
    list_id = urllib.parse.quote(_list_id(owner), safe="")
    payload = _http_json(
        "GET",
        f"{GOOGLE_TASKS_BASE}/lists/{list_id}/tasks?showCompleted=true&showHidden=true&maxResults=100",
        headers=_auth_headers(access),
    )
    completed_ids = {
        item.get("id")
        for item in payload.get("items") or []
        if item.get("status") == "completed" and item.get("id")
    }
    if not completed_ids:
        return 0

    rows = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(
            TaskList.dynamic_id == dynamic_id,
            Task.google_task_id != "",
            Task.completed_at.is_(None),
            Task.approval_status == TaskApprovalStatus.approved,
        )
        .all()
    )
    updated = 0
    now = datetime.utcnow()
    for task in rows:
        if task.google_task_id not in completed_ids:
            continue
        if task.recurrence != TaskRecurrence.none:
            schedule_next_occurrence(task, from_time=task.next_due_at or task.due_at or now)
        else:
            task.completed_at = now
        updated += 1
    return updated


def push_open_tasks(
    db: Session,
    *,
    owner: User,
    actor: User,
    dynamic: Dynamic,
) -> int:
    rows = (
        db.query(Task)
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(
            TaskList.dynamic_id == dynamic.id,
            Task.completed_at.is_(None),
            Task.approval_status == TaskApprovalStatus.approved,
        )
        .all()
    )
    pushed = 0
    for task in rows:
        before = task.google_task_id
        push_task_to_google(db, owner=owner, actor=actor, dynamic=dynamic, task=task)
        if task.google_task_id and (not before or task.public_code_word):
            pushed += 1
    return pushed
