import logging
import httpx
from app.config import settings
from app.services.identity_client import IdentityResolutionError, resolve_emails

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

class EmailNotConfigured(Exception):
    """BREVO_API_KEY / EMAIL_FROM missing from the environment."""

class EmailSendError(Exception):
    """Brevo rejected the request or was unreachable."""

def send(to: str, subject: str, html: str) -> None:
    # Settings are read lazily inside the function so importing this module never
    # touches config/network. Keeps the CI import check green.
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
        # Brevo puts the actual reason in the body
        # Log it so failures aren't opaque, but never log the API key.
        logger.error("Brevo rejected email to %s: HTTP %s — %s", to, resp.status_code, resp.text[:500])
        raise EmailSendError(f"Provider rejected the email (HTTP {resp.status_code})")

def build_report_ready_html(report, review_url: str) -> str:
    """HTML body for the 'report ready for review' email. review_url points at the
    frontend report page. NOTE: the frontend is Week 5, so the link won't resolve yet
    — same known state as identity's invite emails."""
    return (
        f"<p>A weekly report (#{report.id}) is ready for your review.</p>"
        f'<p><a href="{review_url}">Open the report</a> to approve, reject, or request changes.</p>'
        "<p>If this wasn't expected, you can ignore this email.</p>"
    )

def notify_report_ready(db, report) -> None:
    """Best-effort notification that a report is now awaiting review. Called AFTER the
    submit commit so a notification problem can never roll back or block the submission.

    Resolves the repo's approvers (lead/deputy) to email addresses via identity, then
    emails each one a link to the report. The WHOLE thing is wrapped so it can NEVER
    raise: identity down, resolution failing, email misconfigured, or Brevo erroring are
    all logged and swallowed. A submit must never fail because a notification did.
    """
    try:
        repo = report.repository
        approver_ids = [uid for uid in (repo.lead_user_id, repo.deputy_user_id) if uid is not None]
        if not approver_ids:
            logger.info("report %s ready for review — no approvers to notify", report.id)
            return

        emails = resolve_emails(approver_ids)
        if not emails:
            logger.warning("report %s ready for review — no approver emails resolved for %s", report.id, approver_ids)
            return

        review_url = f"{settings.FRONTEND_URL}/reports/{report.id}"
        html = build_report_ready_html(report, review_url)
        for email in emails.values():
            send(to=email, subject="A report is ready for your review", html=html)
    except (IdentityResolutionError, EmailNotConfigured, EmailSendError) as e:
        # Expected failure modes (identity/config/provider) — warn, don't alarm.
        logger.warning("notify_report_ready skipped for report %s: %s", getattr(report, "id", "?"), e)
    except Exception as e:
        logger.error("notify_report_ready failed for report %s: %s", getattr(report, "id", "?"), e)
