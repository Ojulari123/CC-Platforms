from datetime import date, datetime, timezone
import pytest
from app.models import STATUS_APPROVED, STATUS_DRAFT, Commit, PullRequest, Report, Repository

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25
WEEK = date(2026, 7, 20)  # a Monday

ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
OUTSIDER = dict(user_id=40, memberships=[{"dept_id": 2, "team_id": None, "role": "engineer"}])
ADMIN = dict(user_id=99, is_platform_admin=True)

def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)

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
    # A couple of commits + a PR inside the WEEK window, so the activity table is non-zero.
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
        assert len(r.content) > 500  # a real, non-trivial document
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
