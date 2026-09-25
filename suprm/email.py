"""Transactional email: verification, password reset, release status."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("suprm.email")

# The console backend keeps sent mail here so tests (and you, locally) can read it.
SENT: list[dict] = []


class EmailError(RuntimeError):
    pass


def send_email(to: str, subject: str, text: str) -> None:
    backend = settings.email_backend
    if backend == "console":
        SENT.append({"to": to, "subject": subject, "text": text})
        log.warning("EMAIL to=%s subject=%s\n%s", to, subject, text)
    elif backend == "smtp":
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
        msg.set_content(text)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailError(str(exc)) from exc
    elif backend == "resend":
        import httpx

        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "text": text},
            timeout=20,
        )
        if resp.status_code >= 300:
            raise EmailError(f"Resend rejected the email ({resp.status_code}): {resp.text[:300]}")
    else:
        raise EmailError(f"Unknown EMAIL_BACKEND {backend!r}")
