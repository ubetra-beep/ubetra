from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Membership, SleepSession, User

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
FITNESS_SLEEP_SCOPE = "https://www.googleapis.com/auth/fitness.sleep.read"
FITNESS_SESSIONS_URL = "https://www.googleapis.com/fitness/v1/users/me/sessions"

GARMIN_AUTH_URL = "https://connect.garmin.com/oauthConfirm"
# Garmin Wellness API OAuth2 (Connect developer program)
GARMIN_AUTHORIZE_URL = "https://connect.garmin.com/oauth2Confirm"
GARMIN_TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"
GARMIN_SLEEP_URL = "https://apis.garmin.com/wellness-api/rest/sleeps"

_pending_oauth: dict[str, dict] = {}


def google_fitness_configured() -> bool:
    return bool(settings.google_client_id.strip() and settings.google_client_secret.strip())


def garmin_configured() -> bool:
    return bool(settings.garmin_client_id.strip() and settings.garmin_client_secret.strip())


def build_google_sleep_auth_url(*, user_id: str, dynamic_id: str) -> str:
    if not google_fitness_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured. Set UBETRA_GOOGLE_CLIENT_ID/SECRET.",
        )
    state = secrets.token_urlsafe(24)
    _pending_oauth[state] = {
        "provider": "google",
        "user_id": user_id,
        "dynamic_id": dynamic_id,
    }
    params = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_fitness_redirect_uri,
            "response_type": "code",
            "scope": FITNESS_SLEEP_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH_URL}?{params}"


def build_garmin_auth_url(*, user_id: str, dynamic_id: str) -> str:
    if not garmin_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Garmin OAuth is not configured. Set UBETRA_GARMIN_CLIENT_ID/SECRET.",
        )
    state = secrets.token_urlsafe(24)
    _pending_oauth[state] = {
        "provider": "garmin",
        "user_id": user_id,
        "dynamic_id": dynamic_id,
    }
    params = urllib.parse.urlencode(
        {
            "client_id": settings.garmin_client_id,
            "response_type": "code",
            "redirect_uri": settings.garmin_redirect_uri,
            "state": state,
        }
    )
    return f"{GARMIN_AUTHORIZE_URL}?{params}"


def pop_oauth_state(state: str) -> dict | None:
    return _pending_oauth.pop(state, None)


def _exchange_google_code(code: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_fitness_redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google token exchange failed: {body}",
        ) from exc


def _google_access_token(user: User) -> str:
    refresh = (user.google_refresh_token or "").strip()
    if not refresh:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Google sleep sync first.",
        )
    data = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))
    return tokens["access_token"]


def store_google_sleep_tokens(user: User, tokens: dict) -> None:
    refresh = (tokens.get("refresh_token") or "").strip()
    if refresh:
        user.google_refresh_token = refresh
    scopes = (tokens.get("scope") or FITNESS_SLEEP_SCOPE).strip()
    user.google_fitness_scopes = scopes


def _exchange_garmin_code(code: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": settings.garmin_client_id,
            "client_secret": settings.garmin_client_secret,
            "code": code,
            "redirect_uri": settings.garmin_redirect_uri,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GARMIN_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Garmin token exchange failed: {body}",
        ) from exc


def store_garmin_tokens(user: User, tokens: dict) -> None:
    user.garmin_access_token = (tokens.get("access_token") or "").strip()
    refresh = (tokens.get("refresh_token") or "").strip()
    if refresh:
        user.garmin_refresh_token = refresh
    expires_in = tokens.get("expires_in")
    if expires_in:
        user.garmin_token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))


def _upsert_session(
    db: Session,
    *,
    dynamic_id: str,
    membership_id: str,
    source: str,
    external_id: str,
    start_at: datetime,
    end_at: datetime,
    sleep_score: int | None = None,
    stages: dict | list | None = None,
    notes: str = "",
) -> SleepSession:
    existing = None
    if external_id:
        existing = (
            db.query(SleepSession)
            .filter(
                SleepSession.dynamic_id == dynamic_id,
                SleepSession.source == source,
                SleepSession.external_id == external_id,
            )
            .first()
        )
    duration = max(0, int((end_at - start_at).total_seconds() // 60))
    stages_json = json.dumps(stages) if stages is not None else ""
    if existing:
        existing.start_at = start_at
        existing.end_at = end_at
        existing.duration_min = duration
        existing.sleep_score = sleep_score
        existing.stages_json = stages_json
        existing.notes = notes or existing.notes
        existing.synced_at = datetime.utcnow()
        return existing
    row = SleepSession(
        dynamic_id=dynamic_id,
        subject_membership_id=membership_id,
        source=source,
        external_id=external_id or "",
        start_at=start_at,
        end_at=end_at,
        duration_min=duration,
        sleep_score=sleep_score,
        stages_json=stages_json,
        notes=notes or "",
        synced_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def sync_google_sleep(
    db: Session,
    *,
    user: User,
    membership: Membership,
    dynamic_id: str,
    days: int = 14,
) -> int:
    token = _google_access_token(user)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    # Google Fitness sessions API uses millis
    params = urllib.parse.urlencode(
        {
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endTime": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "activityType": 72,  # sleep
        }
    )
    req = urllib.request.Request(
        f"{FITNESS_SESSIONS_URL}?{params}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Fitness error: {body}",
        ) from exc

    count = 0
    for session in payload.get("session") or []:
        name = (session.get("name") or session.get("activityType") or "sleep").lower()
        if "sleep" not in str(name) and session.get("activityType") not in (72, "72"):
            continue
        start_ms = int(session.get("startTimeMillis") or 0)
        end_ms = int(session.get("endTimeMillis") or 0)
        if not start_ms or not end_ms:
            continue
        start_at = datetime.utcfromtimestamp(start_ms / 1000.0)
        end_at = datetime.utcfromtimestamp(end_ms / 1000.0)
        external_id = str(session.get("id") or f"gfit-{start_ms}")
        _upsert_session(
            db,
            dynamic_id=dynamic_id,
            membership_id=membership.id,
            source="google",
            external_id=external_id,
            start_at=start_at,
            end_at=end_at,
            stages=session.get("application") or {},
        )
        count += 1
    return count


def sync_garmin_sleep(
    db: Session,
    *,
    user: User,
    membership: Membership,
    dynamic_id: str,
    days: int = 14,
) -> int:
    token = (user.garmin_access_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Garmin sleep sync first.",
        )
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    params = urllib.parse.urlencode(
        {"uploadStartTimeInSeconds": int(datetime.combine(start, datetime.min.time()).timestamp())}
    )
    req = urllib.request.Request(
        f"{GARMIN_SLEEP_URL}?{params}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Garmin sleep API error: {body}",
        ) from exc

    rows = payload if isinstance(payload, list) else payload.get("sleeps") or []
    count = 0
    for item in rows:
        start_sec = int(item.get("startTimeInSeconds") or 0)
        duration = int(item.get("durationInSeconds") or 0)
        if start_sec and duration:
            start_at = datetime.utcfromtimestamp(start_sec)
            end_at = start_at + timedelta(seconds=duration)
        else:
            cal = item.get("calendarDate")
            if not cal:
                continue
            start_at = datetime.fromisoformat(f"{cal}T00:00:00")
            end_at = start_at + timedelta(seconds=duration or 0)
        external_id = str(item.get("summaryId") or item.get("id") or f"garmin-{start_at.isoformat()}")
        score = item.get("overallSleepScore") or item.get("sleepScores", {}).get("overall", {}).get("value")
        _upsert_session(
            db,
            dynamic_id=dynamic_id,
            membership_id=membership.id,
            source="garmin",
            external_id=external_id,
            start_at=start_at,
            end_at=end_at,
            sleep_score=int(score) if score is not None else None,
            stages=item.get("sleepLevelsMap") or item.get("sleepLevels") or {},
        )
        count += 1
    return count


def import_apple_sessions(
    db: Session,
    *,
    membership: Membership,
    dynamic_id: str,
    sessions: list[dict],
) -> int:
    count = 0
    for item in sessions:
        try:
            start_at = datetime.fromisoformat(str(item["start_at"]).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
            end_at = datetime.fromisoformat(str(item["end_at"]).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Apple sleep session: {exc}",
            ) from exc
        external_id = str(item.get("external_id") or f"apple-{start_at.isoformat()}")
        score = item.get("sleep_score")
        _upsert_session(
            db,
            dynamic_id=dynamic_id,
            membership_id=membership.id,
            source="apple",
            external_id=external_id,
            start_at=start_at,
            end_at=end_at,
            sleep_score=int(score) if score is not None else None,
            stages=item.get("stages"),
            notes=str(item.get("notes") or ""),
        )
        count += 1
    return count
