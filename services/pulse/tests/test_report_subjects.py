from datetime import date, datetime, timezone
import pytest
from app.models import REPORT_KIND_ADHOC, REPORT_KIND_WEEKLY, Commit, Report, ReportSubject, Repository
from app.services import people
from app.services.reports import report_subject_ids

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25
ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
LEAD = dict(user_id=LEAD_ID, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])

@pytest.fixture
def repo(db):
    repo = Repository(
        github_repo_id=1, full_name="org/alpha", owner="org", name="alpha",
        dept_id=DEPT, lead_user_id=LEAD_ID, deputy_user_id=DEPUTY_ID,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    db.add(Commit(repo_id=repo.id, sha="alpha-10", author_user_id=10,
                  committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db.commit()
    return repo.id

def _create(client, repo_id, **body):
    body["repo_id"] = repo_id
    body.setdefault("summary_manager", "did the work")
    return client.post("/reports", json=body)

def _add_subjects(db, report_id, rows):
    for user_id, login, section, position in rows:
        db.add(ReportSubject(report_id=report_id, subject_user_id=user_id,
                             subject_github_login=login, section=section, position=position))
    db.commit()

class TestSubjectsOnAReport:
    def test_subjects_come_back_in_position_order(self, client, act_as, db, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        _add_subjects(db, rid, [
            (12, "carol", "Carol's week", 2),
            (10, "ada", "Ada's week", 0),
            (None, "external-dev", "An outside contributor's week", 1),
        ])
        body = client.get(f"/reports/{rid}").json()
        assert [s["position"] for s in body["subjects"]] == [0, 1, 2]
        assert [s["subject_user_id"] for s in body["subjects"]] == [10, None, 12]
        assert [s["subject_github_login"] for s in body["subjects"]] == ["ada", "external-dev", "carol"]
        assert body["subjects"][0]["section"] == "Ada's week"

    def test_deleting_a_report_deletes_its_subjects(self, client, act_as, db, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        _add_subjects(db, rid, [(10, "ada", "Ada's week", 0), (12, "carol", "Carol's week", 1)])
        assert client.delete(f"/reports/{rid}").status_code == 204
        assert db.query(ReportSubject).filter_by(report_id=rid).count() == 0

    def test_subject_names_are_decorated(self, client, act_as, db, repo, monkeypatch):
        profiles = {
            10: {"user_id": 10, "first_name": "Ada", "last_name": "Lovelace", "avatar_url": None, "is_active": True},
            12: {"user_id": 12, "first_name": "Carol", "last_name": "Shaw", "avatar_url": None, "is_active": True},
        }
        monkeypatch.setattr(people, "resolve_profiles_safe", lambda ids: {i: profiles[i] for i in ids if i in profiles})
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        _add_subjects(db, rid, [(10, "ada", "Ada's week", 0), (12, "carol", "Carol's week", 1)])
        body = client.get(f"/reports/{rid}").json()
        assert body["author"]["first_name"] == "Ada"
        assert body["subject"]["first_name"] == "Ada"
        assert [s["subject"]["last_name"] for s in body["subjects"]] == ["Lovelace", "Shaw"]

    def test_a_subject_identity_does_not_know_is_left_unnamed(self, client, act_as, db, repo, monkeypatch):
        monkeypatch.setattr(people, "resolve_profiles_safe", lambda ids: {})
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        _add_subjects(db, rid, [(10, "ada", "Ada's week", 0)])
        body = client.get(f"/reports/{rid}").json()
        assert body["subject"] is None
        assert body["subjects"][0]["subject"] is None

    def test_listing_reports_decorates_nested_subjects(self, client, act_as, db, repo, monkeypatch):
        profiles = {12: {"user_id": 12, "first_name": "Carol", "last_name": "Shaw", "avatar_url": None, "is_active": True}}
        monkeypatch.setattr(people, "resolve_profiles_safe", lambda ids: {i: profiles[i] for i in ids if i in profiles})
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        _add_subjects(db, rid, [(12, "carol", "Carol's week", 0)])
        items = client.get(f"/reports?repo_id={repo}").json()["items"]
        assert items[0]["subjects"][0]["subject"]["first_name"] == "Carol"

class TestSubjectIds:
    def test_falls_back_to_the_reports_own_subject(self, db, repo):
        report = Report(author_user_id=10, subject_user_id=10, repo_id=repo, dept_id=DEPT,
                        kind=REPORT_KIND_WEEKLY, week_start=date(2026, 7, 20))
        db.add(report)
        db.commit()
        assert report_subject_ids(report) == [10]

    def test_child_rows_win_and_keep_their_order(self, db, repo):
        report = Report(author_user_id=10, subject_user_id=10, repo_id=repo, dept_id=DEPT,
                        kind=REPORT_KIND_WEEKLY, week_start=date(2026, 7, 20))
        db.add(report)
        db.commit()
        _add_subjects(db, report.id, [(12, "carol", None, 1), (11, "grace", None, 0)])
        db.refresh(report)
        assert report_subject_ids(report) == [11, 12]

    def test_external_contributors_with_no_pulse_account_are_skipped(self, db, repo):
        report = Report(author_user_id=10, subject_user_id=None, repo_id=repo, dept_id=DEPT,
                        kind=REPORT_KIND_ADHOC, subject_github_login="external-dev")
        db.add(report)
        db.commit()
        assert report_subject_ids(report) == []
        _add_subjects(db, report.id, [(None, "external-dev", None, 0), (11, "grace", None, 1)])
        db.refresh(report)
        assert report_subject_ids(report) == [11]

class TestNullableTargets:
    def test_an_adhoc_report_needs_no_repo_or_week(self, db):
        report = Report(author_user_id=10, subject_github_login="external-dev",
                        kind=REPORT_KIND_ADHOC, repo_full_name="someone/untracked",
                        range_start=date(2026, 7, 1), range_end=date(2026, 7, 31))
        db.add(report)
        db.commit()
        db.refresh(report)
        assert report.repo_id is None and report.week_start is None
        assert report.kind == REPORT_KIND_ADHOC

    def test_two_adhoc_reports_for_one_author_do_not_collide(self, db):
        # NULL never equals NULL in a unique index, on Postgres or SQLite, so the weekly
        # guard cannot catch ad-hoc rows by accident.
        for name in ("someone/one", "someone/two"):
            db.add(Report(author_user_id=10, subject_user_id=11, kind=REPORT_KIND_ADHOC,
                          repo_full_name=name, range_start=date(2026, 7, 1), range_end=date(2026, 7, 7)))
        db.commit()
        assert db.query(Report).filter_by(kind=REPORT_KIND_ADHOC).count() == 2

    def test_the_weekly_guard_still_rejects_a_duplicate(self, client, act_as, repo):
        act_as(**ENGINEER)
        assert _create(client, repo, week_start="2026-07-20").status_code == 201
        assert _create(client, repo, week_start="2026-07-20").status_code == 409
