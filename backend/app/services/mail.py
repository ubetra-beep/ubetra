"""Shared SMTP helpers for MFA, password reset, etc."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import settings

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    """True when SMTP can plausibly send (host/from set; password if user set)."""
    if not (settings.smtp_host and settings.smtp_from):
        return False
    if settings.smtp_user and not settings.smtp_password:
        return False
    return True


def send_email(*, to_email: str, subject: str, body: str) -> None:
    if not smtp_configured():
        logger.warning("SMTP not configured — email to %s subject=%s\n%s", to_email, subject, body)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(body)

    host = settings.smtp_host
    port = int(settings.smtp_port or 587)
    user = settings.smtp_user or ""
    password = settings.smtp_password or ""
    use_ssl = (not settings.smtp_tls) or port == 465

    if use_ssl and port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            if user:
                server.login(user, password)
            server.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        if settings.smtp_tls:
            server.starttls()
            server.ehlo()
        if user:
            server.login(user, password)
        server.send_message(msg)
