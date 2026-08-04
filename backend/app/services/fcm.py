"""Native FCM (Android APK) push via Firebase HTTP v1."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

from ..config import settings

logger = logging.getLogger(__name__)

_cached_creds = None
_cached_project: str | None = None


def fcm_configured() -> bool:
    path = (settings.fcm_service_account_file or "").strip()
    return bool(path and Path(path).is_file())


def _load_credentials():
    global _cached_creds, _cached_project
    if _cached_creds is not None:
        return _cached_creds, _cached_project
    path = Path(settings.fcm_service_account_file.strip())
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        str(path),
        scopes=["https://www.googleapis.com/auth/firebase.messaging"],
    )
    project = (settings.fcm_project_id or "").strip() or creds.project_id
    _cached_creds = creds
    _cached_project = project
    return creds, project


def send_fcm_data_message(
    token: str,
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    kind: str = "chat",
) -> str:
    """Send a high-priority FCM notification+data message.

    Returns 'ok', 'stale', or 'error'.
    """
    if not fcm_configured():
        return "error"
    try:
        creds, project = _load_credentials()
        if not project:
            logger.warning("FCM project id missing")
            return "error"
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        access = creds.token
        payload_data = {k: str(v) for k, v in (data or {}).items()}
        payload_data.setdefault("title", title)
        payload_data.setdefault("body", body)
        payload_data.setdefault("kind", kind)
        channel = "ubetra_calls" if kind == "call" else "ubetra_chat"
        message = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": payload_data,
                "android": {
                    "priority": "HIGH",
                    "ttl": "86400s",
                    "notification": {
                        "channel_id": channel,
                        "notification_priority": "PRIORITY_MAX" if kind == "call" else "PRIORITY_HIGH",
                        "default_vibrate_timings": True,
                        "default_sound": True,
                    },
                },
            }
        }
        req = urllib.request.Request(
            f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
            data=json.dumps(message).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return "ok"
    except urllib.error.HTTPError as exc:
        body_txt = ""
        try:
            body_txt = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        if exc.code in (404, 410):
            logger.info("FCM stale token (%s): %s", exc.code, token[:24])
            return "stale"
        if exc.code == 400 and ("UNREGISTERED" in body_txt or "INVALID_ARGUMENT" in body_txt):
            return "stale"
        logger.warning("FCM send failed (%s): %s", exc.code, body_txt)
        return "error"
    except Exception as exc:
        logger.warning("FCM send error: %s", exc)
        return "error"
