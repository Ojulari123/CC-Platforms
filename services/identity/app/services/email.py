"""Thin email layer — ONE send() function so swapping providers later is a
one-file change. Provider: Brevo transactional API (supervisor sign-off
pending, user-confirmed to build now)."""
import httpx
from app.config import settings

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

class EmailNotConfigured(Exception):
    """BREVO_API_KEY / EMAIL_FROM missing from the environment."""

class EmailSendError(Exception):
    """Brevo rejected the request or was unreachable."""

def send(to: str, subject: str, html: str) -> None:
    if not settings.BREVO_API_KEY or not settings.EMAIL_FROM:
        raise EmailNotConfigured("Set BREVO_API_KEY and EMAIL_FROM in .env")
    try:
        resp = httpx.post(
            BREVO_URL,
            headers={"api-key": settings.BREVO_API_KEY, "content-type": "application/json"},
            json={
                "sender": {"email": settings.EMAIL_FROM, "name": "CypherCrescent Platforms"},
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise EmailSendError(f"Failed to send email: {e}") from e

def send_invite(to: str, org_name: str, role: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_URL}/invites/accept?token={raw_token}"
    send(
        to=to,
        subject=f"You've been invited to {org_name} on CypherCrescent Platforms",
        html=(
            f"<p>You've been invited to join <strong>{org_name}</strong> as "
            f"<strong>{role}</strong>.</p>"
            f'<p><a href="{link}">Accept your invitation</a> '
            f"(link expires in {settings.INVITE_EXPIRE_DAYS} days).</p>"
            f"<p>If you weren't expecting this, you can ignore this email.</p>"
        ),
    )
