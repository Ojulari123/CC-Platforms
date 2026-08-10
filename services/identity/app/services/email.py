import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

class EmailNotConfigured(Exception):
    pass

class EmailSendError(Exception):
    pass

def is_configured() -> bool:
    """Checked up-front by flows that must not leak whether an address has an account:
    a 503 for global misconfig has to fire the same way regardless of the user."""
    return bool(settings.BREVO_API_KEY and settings.EMAIL_FROM)

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
    except httpx.HTTPError as e:
        logger.error("Email transport failure to %s: %s", to, e)
        raise EmailSendError(f"Failed to send email: {e}") from e

    if resp.status_code >= 400:
        # Brevo puts the actual reason in the body ("unrecognised IP address",
        # "sender not validated", ...). Without logging it, every failure looks
        # identical from the outside. Never log the API key.
        logger.error("Brevo rejected email to %s: HTTP %s — %s", to, resp.status_code, resp.text[:500])
        raise EmailSendError(f"Provider rejected the email (HTTP {resp.status_code})")

def send_invite(to: str, dept_name: str, role: str, raw_token: str, team_name: str | None = None) -> None:
    link = f"{settings.FRONTEND_URL}/invites/accept?token={raw_token}"
    where = f"{dept_name} — {team_name}" if team_name else dept_name
    placement = (
        f"<p>You've been invited to join the <strong>{team_name}</strong> team "
        f"in <strong>{dept_name}</strong> as <strong>{role}</strong>.</p>"
        if team_name else
        f"<p>You've been invited to join <strong>{dept_name}</strong> as "
        f"<strong>{role}</strong>.</p>"
    )
    send(
        to=to,
        subject=f"You've been invited to {where} on CypherCrescent Platforms",
        html=(
            placement
            + f'<p><a href="{link}">Accept your invitation</a> '
            f"(link expires in {settings.INVITE_EXPIRE_DAYS} days).</p>"
            f"<p>If you weren't expecting this, you can ignore this email.</p>"
        ),
    )

def send_password_reset(to: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    send(
        to=to,
        subject="Reset your CypherCrescent Platforms password",
        html=(
            "<p>We got a request to reset your password. "
            f'<a href="{link}">Choose a new password</a> '
            f"(link expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes).</p>"
            "<p>If you didn't ask for this, you can ignore this email — your "
            "password stays the same.</p>"
        ),
    )
