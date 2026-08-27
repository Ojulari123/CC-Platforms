import logging
import httpx
from app.config import settings
from app.services.identity_client import IdentityResolutionError, resolve_dept_admin_emails, resolve_emails, resolve_platform_admin_emails

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

class EmailNotConfigured(Exception):
    pass

class EmailSendError(Exception):
    pass

def send(to: str, subject: str, html: str) -> None:
    if not settings.BREVO_API_KEY or not settings.EMAIL_FROM:
        missing = [
            name for name, value in (
                ("BREVO_API_KEY", settings.BREVO_API_KEY),
                ("EMAIL_FROM", settings.EMAIL_FROM),
            ) if not value
        ]
        # Which variable is missing is an operator's problem, so it goes in the log and
        # not in a message a caller could one day pass on.
        logger.error(
            "Email sending is not configured: BREVO_API_KEY and EMAIL_FROM must both be set (missing: %s)",
            ", ".join(missing),
        )
        raise EmailNotConfigured("Email sending is not configured on this server")
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
        # The transport error can name the provider host and any proxy in front of it;
        # it stays in the log line above.
        logger.error("Email transport failure to %s: %s", to, e)
        raise EmailSendError("Could not reach the email provider") from e

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

def build_unfiled_repo_html(report, repo, review_url: str) -> str:
    return (
        f"<p>Your weekly report (#{report.id}) was submitted. <b>{repo.full_name}</b> hasn't "
        "been filed under a department and has no lead or deputy, so it has no named reviewer.</p>"
        "<p>The platform admins have been emailed and can decide it as it stands. Filing the "
        "repository under a department, or naming a repo lead, hands it to someone closer to "
        "the work.</p>"
        f'<p><a href="{review_url}">Open the report</a></p>'
    )

def build_no_approver_html(report, repo, review_url: str) -> str:
    return (
        f"<p>Your weekly report (#{report.id}) was submitted, but nobody is named to review it.</p>"
        f"<p><b>{repo.full_name}</b> hasn't been filed under a department and has no lead or deputy.</p>"
        "<p>Ask a platform admin to file the repository under a department (or name a repo "
        "lead). The report is already submitted and becomes reviewable as soon as they do.</p>"
        f'<p><a href="{review_url}">Open the report</a></p>'
    )

def _notify_author_of_unfiled_repo(report, repo, backstopped: bool) -> None:
    """Told either way, but not the same thing either way: if platform admins were
    reached the report is genuinely reviewable now, and saying "nobody can review this"
    would send the author chasing an admin for nothing."""
    logger.warning(
        "report %s submitted against unfiled repo %s (no department, lead, or deputy); platform admins notified: %s",
        report.id, repo.id, backstopped,
    )
    try:
        email = resolve_emails([report.author_user_id]).get(report.author_user_id)
        if not email:
            logger.warning("report %s: could not resolve the author's email to warn them", report.id)
            return
        build = build_unfiled_repo_html if backstopped else build_no_approver_html
        send(
            to=email,
            subject="Your report was submitted, but has no named reviewer",
            html=build(report, repo, f"{settings.FRONTEND_URL}/reports/{report.id}"),
        )
    except (IdentityResolutionError, EmailNotConfigured, EmailSendError) as e:
        logger.warning("report %s: could not warn the author about the unfiled repo: %s", report.id, e)

def _approver_emails(report, repo) -> dict[int, str]:
    """Whoever reports._can_approve would let decide this report, as addresses.

    The three branches are that function read back out: the named lead and deputy first;
    failing that every admin of the report's department, who are already in that queue and
    were simply never told; failing even a department, the platform admins, who are the
    backstop _can_approve has always granted and the only people who can act at all.
    """
    approver_ids = [uid for uid in (repo.lead_user_id, repo.deputy_user_id) if uid is not None]
    if approver_ids:
        return resolve_emails(approver_ids)
    if report.dept_id is not None:
        return resolve_dept_admin_emails(report.dept_id)
    return resolve_platform_admin_emails()

def notify_report_ready(report) -> None:
    try:
        repo = report.repository
        unfiled = repo.lead_user_id is None and repo.deputy_user_id is None and report.dept_id is None
    except Exception as e:
        logger.error("notify_report_ready failed for report %s: %s", getattr(report, "id", "?"), e)
        return

    # Deliberately not one try around both halves. The author's warning is the only
    # thing that reaches a person at all when the repo is unfiled, so an identity outage
    # while looking up the backstop must not swallow it as well.
    emails: dict[int, str] = {}
    try:
        emails = _approver_emails(report, repo)
        # Nobody approves their own report, so mailing an admin their own submission
        # would be an invitation to do something the API refuses.
        emails.pop(report.author_user_id, None)
        if not emails:
            named = [uid for uid in (repo.lead_user_id, repo.deputy_user_id) if uid is not None]
            if named:
                # A named approver whose address didn't come back is a fault; a repo that
                # names nobody is a state of the world. Keep them apart in the log.
                logger.warning("report %s ready for review — no approver emails resolved for %s", report.id, named)
            else:
                logger.info("report %s ready for review — no approvers to notify", report.id)
    except (IdentityResolutionError, EmailNotConfigured, EmailSendError) as e:
        logger.warning("notify_report_ready skipped for report %s: %s", getattr(report, "id", "?"), e)
    except Exception as e:
        logger.error("notify_report_ready failed for report %s: %s", getattr(report, "id", "?"), e)

    if emails:
        html = build_report_ready_html(report, f"{settings.FRONTEND_URL}/reports/{report.id}")
        for user_id, email in emails.items():
            try:
                send(to=email, subject="A report is ready for your review", html=html)
            except (EmailNotConfigured, EmailSendError) as e:
                logger.warning("notify_report_ready: report %s not emailed to %s (user %s): %s", report.id, email, user_id, e)
            except Exception as e:
                logger.error("notify_report_ready: report %s unexpected failure emailing %s (user %s): %s", report.id, email, user_id, e)

    if unfiled:
        _notify_author_of_unfiled_repo(report, repo, backstopped=bool(emails))
