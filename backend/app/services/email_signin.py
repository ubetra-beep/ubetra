"""Email a one-time code and link that signs an account in without a password."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote

from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..config import settings
from ..models import EmailSignInChallenge, User
from .mail import send_email, smtp_configured
from .mfa import generate_otp

logger = logging.getLogger(__name__)

SIGNIN_TTL_MINUTES = 20
RESEND_COOLDOWN_SECONDS = 45
GENERIC_OK = {
    "ok": True,
    "detail": "If that email is registered, a sign-in message was sent.",
}


def _link(email: str, token: str) -> str:
    base = (settings.public_app_url or "").rstrip("/") or "http://127.0.0.1:8000"
    return f"{base}/#/email-signin?email={quote(email)}&token={quote(token)}"


def request_email_signin(db: Session, email: str) -> dict:
    """Always return the same shape — no email enumeration."""
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized:
        return GENERIC_OK

    user = db.query(User).filter(User.email == normalized, User.email != "").first()
    if user is None:
        return GENERIC_OK

    db.query(EmailSignInChallenge).filter(
        EmailSignInChallenge.user_id == user.id,
        EmailSignInChallenge.expires_at < datetime.utcnow(),
    ).delete(synchronize_session=False)
    recent = (
        db.query(EmailSignInChallenge)
        .filter(
            EmailSignInChallenge.user_id == user.id,
            EmailSignInChallenge.consumed_at.is_(None),
            EmailSignInChallenge.created_at
            >= datetime.utcnow() - timedelta(seconds=RESEND_COOLDOWN_SECONDS),
        )
        .order_by(EmailSignInChallenge.created_at.desc())
        .first()
    )
    if recent:
        return GENERIC_OK

    code = generate_otp()
    token = secrets.token_urlsafe(32)
    db.add(
        EmailSignInChallenge(
            user_id=user.id,
            code_hash=hash_password(code),
            token_hash=hash_password(token),
            expires_at=datetime.utcnow() + timedelta(minutes=SIGNIN_TTL_MINUTES),
        )
    )
    db.flush()

    link = _link(normalized, token)
    body = (
        "Sign in to UBETRA.\n\n"
        f"One-time code: {code}\n\n"
        f"Or open this link:\n{link}\n\n"
        f"This expires in {SIGNIN_TTL_MINUTES} minutes.\n"
        "If you did not request this, you can ignore this message.\n"
    )
    mailed = False
    if smtp_configured() and (settings.smtp_password or not settings.smtp_user):
        try:
            send_email(to_email=normalized, subject="Your UBETRA sign-in link", body=body)
            mailed = True
        except Exception as exc:
            logger.warning("Sign-in email failed for %s: %s", normalized, exc)

    pushed = 0
    try:
        from .push import notify_user_devices

        pushed = notify_user_devices(
            db,
            user_id=user.id,
            title="UBETRA sign-in",
            body=f"Code {code} — tap to sign in (expires soon).",
            url=f"/#/email-signin?email={quote(normalized)}&token={quote(token)}&code={quote(code)}",
            tag="ubetra-email-signin",
            kind="email_signin",
            respect_push_enabled=False,
        )
    except Exception as exc:
        logger.warning("Sign-in push failed for %s: %s", user.username, exc)

    if settings.mfa_log_codes or not mailed:
        logger.warning(
            "Email sign-in for %s (%s): code=%s mailed=%s pushed=%s",
            user.username,
            normalized,
            code,
            mailed,
            pushed,
        )
    return GENERIC_OK


def confirm_email_signin(
    db: Session,
    *,
    email: str,
    code: str | None = None,
    token: str | None = None,
) -> User:
    normalized = (email or "").strip().lower()
    code = (code or "").strip().replace(" ", "").replace("-", "")
    token = (token or "").strip()
    if not normalized or (not code and not token):
        raise ValueError("Enter the email code or open the sign-in link")

    user = db.query(User).filter(User.email == normalized, User.email != "").first()
    if user is None:
        raise ValueError("Invalid or expired sign-in link")

    challenges = (
        db.query(EmailSignInChallenge)
        .filter(
            EmailSignInChallenge.user_id == user.id,
            EmailSignInChallenge.consumed_at.is_(None),
            EmailSignInChallenge.expires_at >= datetime.utcnow(),
        )
        .order_by(EmailSignInChallenge.created_at.desc())
        .all()
    )
    matched: EmailSignInChallenge | None = None
    for challenge in challenges:
        if code and verify_password(code, challenge.code_hash):
            matched = challenge
            break
        if token and verify_password(token, challenge.token_hash):
            matched = challenge
            break
    if matched is None:
        raise ValueError("Invalid or expired sign-in link")

    matched.consumed_at = datetime.utcnow()
    return user
