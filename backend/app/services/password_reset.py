from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote

from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..config import settings
from ..models import MfaChallenge, PasswordResetChallenge, User
from .mail import send_email, smtp_configured
from .mfa import generate_otp

logger = logging.getLogger(__name__)

RESET_TTL_MINUTES = 30
RESEND_COOLDOWN_SECONDS = 45
GENERIC_OK = {"ok": True, "detail": "If that email is registered, a reset message was sent."}


def purge_expired_resets(db: Session, user_id: str | None = None) -> None:
    q = db.query(PasswordResetChallenge).filter(
        PasswordResetChallenge.expires_at < datetime.utcnow()
    )
    if user_id:
        q = q.filter(PasswordResetChallenge.user_id == user_id)
    q.delete(synchronize_session=False)


def _reset_link(email: str, token: str) -> str:
    base = (settings.public_app_url or "").rstrip("/") or "http://127.0.0.1:8000"
    return f"{base}/#/reset-password?email={quote(email)}&token={quote(token)}"


def request_password_reset(db: Session, email: str) -> dict:
    """Always return the same shape — no email enumeration."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return GENERIC_OK

    user = db.query(User).filter(User.email == normalized, User.email != "").first()
    if user is None:
        return GENERIC_OK

    purge_expired_resets(db, user.id)
    recent = (
        db.query(PasswordResetChallenge)
        .filter(
            PasswordResetChallenge.user_id == user.id,
            PasswordResetChallenge.consumed_at.is_(None),
            PasswordResetChallenge.created_at
            >= datetime.utcnow() - timedelta(seconds=RESEND_COOLDOWN_SECONDS),
        )
        .order_by(PasswordResetChallenge.created_at.desc())
        .first()
    )
    if recent:
        return GENERIC_OK

    code = generate_otp()
    token = secrets.token_urlsafe(32)
    challenge = PasswordResetChallenge(
        user_id=user.id,
        code_hash=hash_password(code),
        token_hash=hash_password(token),
        expires_at=datetime.utcnow() + timedelta(minutes=RESET_TTL_MINUTES),
    )
    db.add(challenge)
    db.flush()

    link = _reset_link(normalized, token)
    body = (
        f"Reset your UBETRA password.\n\n"
        f"One-time code: {code}\n\n"
        f"Or open this link:\n{link}\n\n"
        f"This expires in {RESET_TTL_MINUTES} minutes.\n"
        "If you did not request a reset, you can ignore this message.\n"
    )
    send_email(to_email=normalized, subject="Reset your UBETRA password", body=body)
    if settings.mfa_log_codes or not smtp_configured():
        logger.info(
            "Password reset for %s (%s): code=%s token=%s",
            user.username,
            normalized,
            code,
            token,
        )
    return GENERIC_OK


def confirm_password_reset(
    db: Session,
    *,
    email: str,
    new_password: str,
    code: str | None = None,
    token: str | None = None,
) -> User:
    normalized = (email or "").strip().lower()
    code = (code or "").strip()
    token = (token or "").strip()
    if not normalized or not new_password:
        raise ValueError("Email and new password are required")
    if not code and not token:
        raise ValueError("Enter the email code or use the reset link")
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters")

    user = db.query(User).filter(User.email == normalized, User.email != "").first()
    if user is None:
        raise ValueError("Invalid or expired reset")

    purge_expired_resets(db, user.id)
    challenges = (
        db.query(PasswordResetChallenge)
        .filter(
            PasswordResetChallenge.user_id == user.id,
            PasswordResetChallenge.consumed_at.is_(None),
            PasswordResetChallenge.expires_at >= datetime.utcnow(),
        )
        .order_by(PasswordResetChallenge.created_at.desc())
        .all()
    )
    matched: PasswordResetChallenge | None = None
    for challenge in challenges:
        if code and verify_password(code, challenge.code_hash):
            matched = challenge
            break
        if token and verify_password(token, challenge.token_hash):
            matched = challenge
            break
    if matched is None:
        raise ValueError("Invalid or expired reset")

    matched.consumed_at = datetime.utcnow()
    user.password_hash = hash_password(new_password)
    # Invalidate outstanding MFA challenges after a password change.
    db.query(MfaChallenge).filter(
        MfaChallenge.user_id == user.id,
        MfaChallenge.consumed_at.is_(None),
    ).update({MfaChallenge.consumed_at: datetime.utcnow()}, synchronize_session=False)
    return user
