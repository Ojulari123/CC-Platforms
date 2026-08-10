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
        monkeypatch.setattr("app.services.reports.notify_report_ready",
                            lambda report: calls.append(report.id))
        r = _open_submitted(client, act_as, repo_id)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "submitted"
        assert len(calls) == 1

    def test_a_broken_notifier_never_breaks_submit(self, client, act_as, db, monkeypatch):
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


def _report(lead=LEAD_ID, deputy=DEPUTY_ID, rid=7, dept_id=DEPT, author=10):
    return SimpleNamespace(
        id=rid,
        dept_id=dept_id,
        author_user_id=author,
        repository=SimpleNamespace(id=1, full_name="org/alpha", lead_user_id=lead, deputy_user_id=deputy),
    )


class TestNotifyRealSend:

    def test_two_approvers_each_get_a_send(self, monkeypatch):
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails",
                            lambda ids: {20: "lead@x.com", 25: "deputy@x.com"})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append((to, subject, html)))
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://front")

        notify_report_ready(_report())

        assert {s[0] for s in sends} == {"lead@x.com", "deputy@x.com"}
        assert len(sends) == 2
        assert all(s[1] == "A report is ready for your review" for s in sends)
        assert all("http://front/reports/7" in s[2] for s in sends)

    def test_only_resolved_ids_are_emailed(self, monkeypatch):
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {20: "lead@x.com"})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        notify_report_ready(_report())
        assert sends == ["lead@x.com"]

    def test_identity_failure_is_swallowed_no_send(self, monkeypatch, caplog):
        sends = []

        def _fail(ids):
            raise IdentityResolutionError("identity down")

        monkeypatch.setattr(email_mod, "resolve_emails", _fail)
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(_report())
        assert sends == []
        assert "skipped" in caplog.text

    def test_one_bad_address_still_notifies_the_other_approver(self, monkeypatch, caplog):
        sends = []

        def _send(*, to, subject, html):
            if to == "lead@x.com":
                raise EmailSendError("invalid recipient")
            sends.append(to)

        monkeypatch.setattr(email_mod, "resolve_emails",
                            lambda ids: {20: "lead@x.com", 25: "deputy@x.com"})
        monkeypatch.setattr(email_mod, "send", _send)
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(_report())

        assert sends == ["deputy@x.com"]
        assert "lead@x.com" in caplog.text

    def test_an_unexpected_send_failure_also_only_skips_that_recipient(self, monkeypatch, caplog):
        sends = []

        def _send(*, to, subject, html):
            if to == "lead@x.com":
                raise RuntimeError("socket exploded")
            sends.append(to)

        monkeypatch.setattr(email_mod, "resolve_emails",
                            lambda ids: {20: "lead@x.com", 25: "deputy@x.com"})
        monkeypatch.setattr(email_mod, "send", _send)
        with caplog.at_level(logging.ERROR, logger="app.services.email"):
            notify_report_ready(_report())

        assert sends == ["deputy@x.com"]
        assert "lead@x.com" in caplog.text

    def test_brevo_send_error_is_swallowed(self, monkeypatch):
        def _boom(*, to, subject, html):
            raise EmailSendError("provider rejected")

        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {20: "lead@x.com"})
        monkeypatch.setattr(email_mod, "send", _boom)
        notify_report_ready(_report())

    def test_unconfigured_secret_skips_cleanly(self, monkeypatch, caplog):
        sends = []
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(_report())
        assert sends == []
        assert "skipped" in caplog.text

    def test_approvers_but_none_resolve_logs_and_returns(self, monkeypatch, caplog):
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(_report())
        assert sends == []
        assert "no approver emails resolved" in caplog.text

    def test_no_approvers_but_a_department_logs_and_returns(self, monkeypatch, caplog):
        sends = []
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.INFO, logger="app.services.email"):
            notify_report_ready(_report(lead=None, deputy=None))
        assert sends == []
        assert "no approvers" in caplog.text


class TestNoApproverWarning:

    def test_the_author_is_warned_and_told_what_to_ask_for(self, monkeypatch, caplog):
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {10: "author@x.com"})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append((to, subject, html)))
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://front")
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(_report(lead=None, deputy=None, dept_id=None))

        assert len(sends) == 1
        to, subject, html = sends[0]
        assert to == "author@x.com"
        assert subject == "Your report was submitted, but has no reviewer yet"
        assert "org/alpha" in html and "platform admin" in html
        assert "http://front/reports/7" in html
        assert "no named approver" in caplog.text

    def test_an_unresolvable_author_only_logs(self, monkeypatch, caplog):
        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            notify_report_ready(_report(lead=None, deputy=None, dept_id=None))
        assert sends == []
        assert "could not resolve the author's email" in caplog.text

    def test_a_failed_warning_never_escapes(self, monkeypatch):
        def _boom(*, to, subject, html):
            raise EmailSendError("provider rejected")

        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {10: "author@x.com"})
        monkeypatch.setattr(email_mod, "send", _boom)
        notify_report_ready(_report(lead=None, deputy=None, dept_id=None))

    def test_submitting_onto_an_unfiled_repo_warns_the_author(self, client, act_as, db, monkeypatch):
        repo = Repository(github_repo_id=2, full_name="org/unfiled", owner="org", name="unfiled",
                          dept_id=None, lead_user_id=None, deputy_user_id=None)
        db.add(repo)
        db.commit()
        db.refresh(repo)
        db.add(Commit(repo_id=repo.id, sha="unfiled-10", author_user_id=10,
                      committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        db.commit()

        sends = []
        monkeypatch.setattr(email_mod, "resolve_emails", lambda ids: {10: "author@x.com"})
        monkeypatch.setattr(email_mod, "send",
                            lambda *, to, subject, html: sends.append(to))
        r = _open_submitted(client, act_as, repo.id)
        assert r.status_code == 200, r.text
        assert sends == ["author@x.com"]
