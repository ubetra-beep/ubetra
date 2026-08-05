from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..config import settings
from ..models import MfaChallenge, User
from .mail import send_email, smtp_configured

logger = logging.getLogger(__name__)

MFA_PURPOSE = "mfa"
OTP_LENGTH = 6
OTP_TTL_MINUTES = 10
RESEND_COOLDOWN_SECONDS = 45

# Re-export for callers that imported smtp_configured from mfa.
__all__ = [
    "generate_otp",
    "create_mfa_token",
    "decode_mfa_token",
    "smtp_configured",
    "send_otp_email",
    "purge_expired_challenges",
    "create_challenge",
    "verify_challenge",
]


def generate_otp() -> str:
    return "".join(random.choices(string.digits, k=OTP_LENGTH))


def create_mfa_token(user_id: str, challenge_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    payload = {
        "sub": user_id,
        "purpose": MFA_PURPOSE,
        "cid": challenge_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_mfa_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired verification session") from exc
    if payload.get("purpose") != MFA_PURPOSE or not payload.get("sub") or not payload.get("cid"):
        raise ValueError("Invalid verification session")
    return payload


def send_otp_email(to_email: str, code: str) -> None:
    send_email(
        to_email=to_email,
        subject="Your sign-in code",
        body=(
            f"Your sign-in code is {code}.\n\n"
            f"It expires in {OTP_TTL_MINUTES} minutes.\n"
            "If you did not request this, you can ignore this message.\n"
        ),
    )


def purge_expired_challenges(db: Session, user_id: str | None = None) -> None:
    q = db.query(MfaChallenge).filter(MfaChallenge.expires_at < datetime.utcnow())
    if user_id:
        q = q.filter(MfaChallenge.user_id == user_id)
    q.delete(synchronize_session=False)


def create_challenge(db: Session, user: User) -> tuple[MfaChallenge, str]:
    purge_expired_challenges(db, user.id)
    recent = (
        db.query(MfaChallenge)
        .filter(
            MfaChallenge.user_id == user.id,
            MfaChallenge.created_at
            >= datetime.utcnow() - timedelta(seconds=RESEND_COOLDOWN_SECONDS),
        )
        .order_by(MfaChallenge.created_at.desc())
        .first()
    )
    if recent and not recent.consumed_at:
        raise ValueError("Please wait before requesting another code")

    code = generate_otp()
    challenge = MfaChallenge(
        user_id=user.id,
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    db.add(challenge)
    db.flush()
    send_otp_email(user.email, code)
    if settings.mfa_log_codes or not smtp_configured():
        logger.info("MFA code for user %s (%s): %s", user.username, user.email, code)
    return challenge, code


def verify_challenge(db: Session, challenge_id: str, user_id: str, code: str) -> MfaChallenge:
    challenge = db.get(MfaChallenge, challenge_id)
    if (
        challenge is None
        or challenge.user_id != user_id
        or challenge.consumed_at is not None
        or challenge.expires_at < datetime.utcnow()
    ):
        raise ValueError("Invalid or expired code")
    if not verify_password(code.strip(), challenge.code_hash):
        raise ValueError("Invalid or expired code")
    challenge.consumed_at = datetime.utcnow()
    return challenge
