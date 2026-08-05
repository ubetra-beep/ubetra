"""Shared SMTP helpers for MFA, password reset, etc."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import settings

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(*, to_email: str, subject: str, body: str) -> None:
    if not smtp_configured():
        logger.warning("SMTP not configured — email to %s subject=%s\n%s", to_email, subject, body)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(body)

    if settings.smtp_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
