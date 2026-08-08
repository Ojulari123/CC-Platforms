"""Week-4 Wave 3: report-ready notification.

Covers the whole notify path WITHOUT touching the network: the submit trigger fires,
a broken notifier can never break submit (log-and-continue), send() enforces config and
speaks the Brevo contract, and the real notify path resolves the repo's lead/deputy to
emails and actually attempts a send per approver.

Email resolution goes through identity; here it's mocked (resolve_emails) so no network
is touched. These tests pin the real-send-attempt behaviour, not the old log-only stub.
"""
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from app.config import settings
from app.models import Commit, Repository
from app.services import email as email_mod
from app.services.email import (
    EmailNotConfigured,
    EmailSendError,
    notify_report_ready,
    send,
)
from app.services.identity_client import IdentityResolutionError

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25
ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])


def _seed_repo(db, lead=LEAD_ID, deputy=DEPUTY_ID):
    """A repo engineer 10 has a commit in, so they may open + submit a report on it."""
    repo = Repository(
        github_repo_id=1, full_name="org/alpha", owner="org", name="alpha",
        dept_id=DEPT, lead_user_id=lead, deputy_user_id=deputy,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    db.add(Commit(repo_id=repo.id, sha="alpha-10", author_user_id=10,
                  committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db.commit()
    return repo.id


def _open_submitted(client, act_as, repo_id):
    act_as(**ENGINEER)
    rid = client.post("/reports", json={"repo_id": repo_id, "summary_manager": "did the work"}).json()["id"]
    return client.post(f"/reports/{rid}/submit")


class TestSubmitTrigger:
    def test_submit_fires_notify_exactly_once(self, client, act_as, db, monkeypatch):
        repo_id = _seed_repo(db)
        calls = []
        # Patch the name bound in reports.py (imported there), not the source module.
        monkeypatch.setattr("app.services.reports.notify_report_ready",
                            lambda _db, report: calls.append(report.id))
        r = _open_submitted(client, act_as, repo_id)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "submitted"
        assert len(calls) == 1

    def test_a_broken_notifier_never_breaks_submit(self, client, act_as, db, monkeypatch):
        # Make the REAL notifier blow up in an UNEXPECTED way (resolve_emails raises a bare
        # RuntimeError, not a typed error). The catch-all inside notify_report_ready must
        # swallow it and the submit must still succeed.
        repo_id = _seed_repo(db)

        def _boom(*a, **k):
            raise RuntimeError("notifier exploded")

        monkeypatch.setattr(email_mod, "resolve_emails", _boom)
        r = _open_submitted(client, act_as, repo_id)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "submitted"


class TestSend:
    def test_empty_config_raises_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "BREVO_API_KEY", "")
        monkeypatch.setattr(settings, "EMAIL_FROM", "")
        with pytest.raises(EmailNotConfigured):
            send("who@x.com", "hi", "<p>hi</p>")

    def test_happy_path_hits_brevo_contract_no_network(self, monkeypatch):
        monkeypatch.setattr(settings, "BREVO_API_KEY", "secret-key")
        monkeypatch.setattr(settings, "EMAIL_FROM", "noreply@cc.com")
        captured = {}

        def _fake_post(url, *, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return SimpleNamespace(status_code=201, text="")

        monkeypatch.setattr(email_mod.httpx, "post", _fake_post)
        send("dest@x.com", "A report is ready", "<p>body</p>")

        assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
        assert captured["headers"]["api-key"] == "secret-key"
        assert captured["json"]["to"] == [{"email": "dest@x.com"}]

    def test_provider_error_raises_send_error(self, monkeypatch):
        monkeypatch.setattr(settings, "BREVO_API_KEY", "secret-key")
        monkeypatch.setattr(settings, "EMAIL_FROM", "noreply@cc.com")
        monkeypatch.setattr(email_mod.httpx, "post",
                            lambda *a, **k: SimpleNamespace(status_code=400, text="sender not validated"))
        with pytest.raises(EmailSendError):
            send("dest@x.com", "s", "<p>h</p>")


def _report(lead=LEAD_ID, deputy=DEPUTY_ID, rid=7):
    return SimpleNamespace(
        id=rid,
        repository=SimpleNamespace(lead_user_id=lead, deputy_user_id=deputy),
    )


class TestNotifyRealSend:
    """notify_report_ready now resolves approver ids to emails and actually attempts a
    send per approver — best-effort, never raising."""

    def test_two_approvers_each_get_a_send(self, monkeypatch):
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails",
                            lambda ids: {20: "lead@x.com", 25: "deputy@x.com"})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append((to, subject, html)))
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://front")

        notify_report_ready(None, _report())

        assert {s[0] for s in sends} == {"lead@x.com", "deputy@x.com"}
        assert len(sends) == 2
        # subject + link are what the approver actually sees.
        assert all(s[1] == "A report is ready for your review" for s in sends)
        assert all("http://front/reports/7" in s[2] for s in sends)

    def test_only_resolved_ids_are_emailed(self, monkeypatch):
        # deputy id resolves to nothing (unknown id omitted by identity) → one send only.
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {20: "lead@x.com"})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        notify_report_ready(None, _report())
        assert sends == ["lead@x.com"]

    def test_identity_failure_is_swallowed_no_send(self, monkeypatch, caplog):
        sends = []

        def _fail(ids):
            raise IdentityResolutionError("identity down")

        monkeypatch.setattr(email_mod, "resolve_emails", _fail)
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(None, _report())  # must NOT raise
        assert sends == []
        assert "skipped" in caplog.text

    def test_brevo_send_error_is_swallowed(self, monkeypatch):
        def _boom(*, to, subject, html):
            raise EmailSendError("provider rejected")

        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {20: "lead@x.com"})
        monkeypatch.setattr(email_mod, "send", _boom)
        notify_report_ready(None, _report())  # swallowed, no raise

    def test_unconfigured_secret_skips_cleanly(self, monkeypatch, caplog):
        # Real resolve_emails with no client secret raises immediately → log-and-skip.
        sends = []
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(None, _report())
        assert sends == []
        assert "skipped" in caplog.text

    def test_approvers_but_none_resolve_logs_and_returns(self, monkeypatch, caplog):
        # Identity succeeds but knows none of the ids (all unknown/omitted) → empty dict,
        # so there's nothing to send.
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(None, _report())
        assert sends == []
        assert "no approver emails resolved" in caplog.text

    def test_no_approvers_logs_and_returns(self, monkeypatch, caplog):
        sends = []
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.INFO, logger="app.services.email"):
            notify_report_ready(None, _report(lead=None, deputy=None))
        assert sends == []
        assert "no approvers" in caplog.text
