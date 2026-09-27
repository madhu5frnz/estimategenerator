"""Outgoing email. Development uses the console sender, which logs the message (and its
links) instead of sending it, so the full sign-up flow works without an email provider."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, email: Email) -> None: ...


class ConsoleEmailSender:
    def send(self, email: Email) -> None:
        log.info("email_console", to=email.to, subject=email.subject, body=email.body)


class SmtpEmailSender:
    def send(self, email: Email) -> None:
        settings = get_settings()
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.body)
        assert settings.smtp_host, "SMTP_HOST must be set when EMAIL_PROVIDER=smtp"
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            smtp.send_message(message)


@lru_cache(maxsize=1)
def _default_sender() -> EmailSender:
    if get_settings().email_provider == "smtp":
        return SmtpEmailSender()
    return ConsoleEmailSender()


def get_email_sender() -> EmailSender:
    """FastAPI dependency (tests override it with an in-memory sender)."""
    return _default_sender()
