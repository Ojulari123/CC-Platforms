"""Week-4 Wave 3: report-ready notification.

Covers the whole notify path WITHOUT touching the network: the submit trigger fires,
a broken notifier can never break submit (log-and-continue), send() enforces config and
speaks the Brevo contract, and the approver-gathering picks the repo's lead/deputy.

Email address resolution (user_id -> address) is Week 5, so notify_report_ready only
LOGS today — these tests pin that behaviour so Week 5 can swap in a real send() safely.
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
        # Make the REAL notifier blow up internally (its INFO log raises). The try/except
        # inside notify_report_ready must swallow it and the submit must still succeed.
        repo_id = _seed_repo(db)

        def _boom(*a, **k):
            raise RuntimeError("notifier exploded")

        monkeypatch.setattr(email_mod.logger, "info", _boom)
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


class TestApproverGathering:
    """notify_report_ready logs which approvers WOULD be notified. Pin that the list is
    the repo's lead + deputy with Nones dropped."""

    def _notify_and_capture(self, caplog, *, lead, deputy):
        report = SimpleNamespace(
            id=7,
            repository=SimpleNamespace(lead_user_id=lead, deputy_user_id=deputy),
        )
        with caplog.at_level(logging.INFO, logger="app.services.email"):
            notify_report_ready(None, report)
        return caplog.text

    def test_lead_and_deputy(self, caplog):
        assert "[20, 25]" in self._notify_and_capture(caplog, lead=20, deputy=25)

    def test_lead_only(self, caplog):
        assert "[20]" in self._notify_and_capture(caplog, lead=20, deputy=None)

    def test_neither(self, caplog):
        assert "[]" in self._notify_and_capture(caplog, lead=None, deputy=None)
