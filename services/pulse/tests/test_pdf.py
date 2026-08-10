import base64
import re
import zlib
from datetime import date, datetime, timezone
import pytest
from app.config import settings
from app.models import STATUS_APPROVED, STATUS_DRAFT, Commit, PullRequest, Report, Repository
from app.services import identity_client
from tests.test_names import FakeIdentity

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25
WEEK = date(2026, 7, 20)  # a Monday

ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
OUTSIDER = dict(user_id=40, memberships=[{"dept_id": 2, "team_id": None, "role": "engineer"}])
ADMIN = dict(user_id=99, is_platform_admin=True)

def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)

def _pdf_text(pdf: bytes) -> str:
    shown = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            data = zlib.decompress(base64.a85decode(stream.strip(), adobe=True))
        except Exception:
            continue
        shown += [m.decode("latin-1") for m in re.findall(rb"\((.*?)\)\s*Tj", data, re.S)]
    return "\n".join(shown)

def _pdf_flat(pdf: bytes) -> str:
    return "".join(_pdf_text(pdf).split("\n"))

@pytest.fixture
def wired_to_identity(monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_API_URL", "http://identity:8000")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_ID", "pulse")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "shh")
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    yield
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0

def _seed_repo(db, gh_id=1, name="alpha"):
    repo = Repository(
        github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name,
        dept_id=DEPT, lead_user_id=LEAD_ID, deputy_user_id=DEPUTY_ID,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo

def _seed_report(db, repo, status=STATUS_APPROVED, author=10, with_generation=True):
    report = Report(
        author_user_id=author, repo_id=repo.id, dept_id=repo.dept_id, week_start=WEEK,
        status=status,
        summary_manager="Shipped the auth refactor and reviewed two PRs.",
        summary_exec="Steady progress on auth.",
        next_week_goals="Finish the token rotation work.",
    )
    if with_generation:
        report.generated_at = _dt(2026, 7, 27)
    db.add(report)
    for i in range(2):
        db.add(Commit(repo_id=repo.id, sha=f"w{i}", author_user_id=author,
                      message=f"commit {i}", committed_at=_dt(2026, 7, 21 + i)))
    db.add(PullRequest(repo_id=repo.id, github_pr_id=100, number=7, title="pr",
                       state="open", merged=False, author_user_id=author, gh_created_at=_dt(2026, 7, 22)))
    db.commit()
    db.refresh(report)
    return report

class TestReportPdf:
    def test_author_gets_a_pdf(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        act_as(**ENGINEER)
        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 500
        assert "inline" in r.headers["content-disposition"]
        assert f"report-{report.id}-week-2026-07-20.pdf" in r.headers["content-disposition"]

    def test_platform_admin_gets_a_pdf(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        act_as(**ADMIN)
        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"

    def test_draft_report_still_exports(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo, status=STATUS_DRAFT, with_generation=False)
        act_as(**ENGINEER)
        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 500

    def test_no_read_access_is_403(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        act_as(**OUTSIDER)
        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 403, r.text

    def test_missing_report_is_404(self, client, act_as, db):
        act_as(**ENGINEER)
        assert client.get("/reports/9999/pdf").status_code == 404

    def test_requires_a_token(self, client, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        assert client.get(f"/reports/{report.id}/pdf").status_code == 401


class TestPdfContent:

    def test_the_author_is_a_name_not_an_id(self, client, act_as, db, monkeypatch, wired_to_identity):
        fake = FakeIdentity(monkeypatch)
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        act_as(**ENGINEER)

        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        text = _pdf_text(r.content)
        assert "Weekly Report" in text
        assert "Ada Lovelace" in text
        assert "Engineer #10" not in text
        assert fake.calls["profiles"] == 1

    def test_identity_unreachable_still_produces_a_pdf_with_the_id(self, client, act_as, db, monkeypatch, wired_to_identity):
        FakeIdentity(monkeypatch, transport_error=True)
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        act_as(**ENGINEER)

        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF" and len(r.content) > 500
        assert "Engineer #10" in _pdf_text(r.content)

    def test_unknown_author_falls_back_to_the_id(self, client, act_as, db, monkeypatch, wired_to_identity):
        FakeIdentity(monkeypatch, known={})
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        act_as(**ENGINEER)

        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        assert "Engineer #10" in _pdf_text(r.content)

    def test_markup_characters_in_summaries_survive(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        report.summary_manager = "Cut R&D latency to <100ms; CI/CD & deploys stayed green."
        report.summary_exec = 'Q&A signed off. 5 > 3 goals landed, marked "done".'
        report.next_week_goals = "Ship <alpha> to staging\nClose the </release> checklist"
        db.commit()
        act_as(**ENGINEER)

        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        text = _pdf_flat(r.content)
        assert "Cut R&D latency to <100ms; CI/CD & deploys stayed green." in text
        assert "R&D;" not in text
        assert 'Q&A signed off. 5 > 3 goals landed, marked "done".' in text
        assert "<alpha>" in text
        assert "</release>" in text

    def test_a_stray_closing_tag_does_not_500_the_export(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        report.summary_manager = "Dropped the </b> tag from the report template."
        db.commit()
        act_as(**ENGINEER)

        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        assert "Dropped the </b> tag from the report template." in _pdf_flat(r.content)

    def test_newlines_in_goals_still_break_lines(self, client, act_as, db):
        repo = _seed_repo(db)
        report = _seed_report(db, repo)
        report.next_week_goals = "First goal\nSecond goal"
        db.commit()
        act_as(**ENGINEER)

        r = client.get(f"/reports/{report.id}/pdf")
        assert r.status_code == 200, r.text
        text = _pdf_text(r.content)
        assert "<br/>" not in text
        assert "First goal" in text and "Second goal" in text
