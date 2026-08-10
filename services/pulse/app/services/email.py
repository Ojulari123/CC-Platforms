import logging
import httpx
from app.config import settings
from app.services.identity_client import IdentityResolutionError, resolve_emails

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

class EmailNotConfigured(Exception):
    pass

class EmailSendError(Exception):
    pass

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
        # Log it so failures aren't opaque, but never log the API key.
        logger.error("Brevo rejected email to %s: HTTP %s — %s", to, resp.status_code, resp.text[:500])
        raise EmailSendError(f"Provider rejected the email (HTTP {resp.status_code})")

def build_report_ready_html(report, review_url: str) -> str:
    return (
        f"<p>A weekly report (#{report.id}) is ready for your review.</p>"
        f'<p><a href="{review_url}">Open the report</a> to approve, reject, or request changes.</p>'
        "<p>If this wasn't expected, you can ignore this email.</p>"
    )

def build_no_approver_html(report, repo, review_url: str) -> str:
    return (
        f"<p>Your weekly report (#{report.id}) was submitted, but nobody is named to review it.</p>"
        f"<p><b>{repo.full_name}</b> hasn't been filed under a department and has no lead or deputy.</p>"
        "<p>Ask a platform admin to file the repository under a department (or name a repo "
        "lead) — the report is already submitted and becomes reviewable as soon as they do.</p>"
        f'<p><a href="{review_url}">Open the report</a></p>'
    )

def _notify_no_approver(report, repo) -> None:
    logger.warning(
        "report %s submitted with no named approver — repo %s has no department, lead, or deputy",
        report.id, repo.id,
    )
    email = resolve_emails([report.author_user_id]).get(report.author_user_id)
    if not email:
        logger.warning("report %s: could not resolve the author's email to warn them", report.id)
        return
    send(
        to=email,
        subject="Your report was submitted, but has no reviewer yet",
        html=build_no_approver_html(report, repo, f"{settings.FRONTEND_URL}/reports/{report.id}"),
    )

def notify_report_ready(report) -> None:
    try:
        repo = report.repository
        approver_ids = [uid for uid in (repo.lead_user_id, repo.deputy_user_id) if uid is not None]
        if not approver_ids:
            if report.dept_id is None:
                _notify_no_approver(report, repo)
            else:
                logger.info("report %s ready for review — no approvers to notify", report.id)
            return

        emails = resolve_emails(approver_ids)
        if not emails:
            logger.warning("report %s ready for review — no approver emails resolved for %s", report.id, approver_ids)
            return

        review_url = f"{settings.FRONTEND_URL}/reports/{report.id}"
        html = build_report_ready_html(report, review_url)
    except (IdentityResolutionError, EmailNotConfigured, EmailSendError) as e:
        logger.warning("notify_report_ready skipped for report %s: %s", getattr(report, "id", "?"), e)
        return
    except Exception as e:
        logger.error("notify_report_ready failed for report %s: %s", getattr(report, "id", "?"), e)
        return

    for user_id, email in emails.items():
        try:
            send(to=email, subject="A report is ready for your review", html=html)
        except (EmailNotConfigured, EmailSendError) as e:
            logger.warning("notify_report_ready: report %s not emailed to %s (user %s): %s", report.id, email, user_id, e)
        except Exception as e:
            logger.error("notify_report_ready: report %s unexpected failure emailing %s (user %s): %s", report.id, email, user_id, e)
