from datetime import date, datetime, timedelta, timezone
import pytest
from app.models import REPORT_KIND_ADHOC, Commit, Issue, PullRequest, Report, Repository

# Write access from activity is a rolling window off the clock, so the seed commit that
# makes these users contributors is relative: a fixed date ages out of the window.
RECENT = datetime.now(timezone.utc) - timedelta(days=1)
STALE = datetime.now(timezone.utc) - timedelta(days=400)

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25

ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
ENGINEER_2 = dict(user_id=11, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
LEAD = dict(user_id=LEAD_ID, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])
DEPUTY = dict(user_id=DEPUTY_ID, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])
MANAGER_NOLEAD = dict(user_id=21, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": DEPT, "team_id": None, "role": "admin"}])
OUTSIDER = dict(user_id=40, memberships=[{"dept_id": 2, "team_id": None, "role": "engineer"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)
UNPLACED = dict(user_id=42, memberships=[])
MEMBER_NO_ACTIVITY = dict(user_id=12, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])

def _this_monday() -> date:
    t = date.today()
    return t - timedelta(days=t.weekday())

def _seed_repo(db, gh_id, name, dept_id=DEPT, lead=LEAD_ID, deputy=DEPUTY_ID, contributors=(10, 11)):
    repo = Repository(
        github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name,
        dept_id=dept_id, lead_user_id=lead, deputy_user_id=deputy,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    for uid in contributors:
        db.add(Commit(repo_id=repo.id, sha=f"{name}-{uid}", author_user_id=uid,
                      committed_at=RECENT))
    db.commit()
    return repo.id

@pytest.fixture
def repo(db):
    return _seed_repo(db, gh_id=1, name="alpha")

def _create(client, repo_id, **body):
    body["repo_id"] = repo_id
    body.setdefault("summary_manager", "did the work")
    return client.post("/reports", json=body)

def _open_submitted(client, act_as, repo_id):
    act_as(**ENGINEER)
    rid = _create(client, repo_id).json()["id"]
    client.post(f"/reports/{rid}/submit")
    return rid

class TestCreate:
    def test_engineer_opens_a_draft(self, client, act_as, repo):
        act_as(**ENGINEER)
        r = _create(client, repo)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "draft"
        assert body["author_user_id"] == 10
        assert body["repo_id"] == repo
        assert body["dept_id"] == DEPT
        assert body["week_start"] == _this_monday().isoformat()

    def test_non_member_of_the_repos_department_cannot_create(self, client, act_as, repo):
        act_as(**OUTSIDER)
        assert _create(client, repo).status_code == 403

    def test_cannot_report_on_a_repo_you_havent_contributed_to(self, client, act_as, repo):
        act_as(**MEMBER_NO_ACTIVITY)
        assert _create(client, repo).status_code == 403

    def test_stale_contribution_no_longer_opens_a_report(self, client, act_as, db):
        """The same window that hid the repo now closes writing on it. Bounded on the read
        side alone let somebody who had moved department keep opening reports there."""
        rid = _seed_repo(db, gh_id=7, name="stale", lead=None, deputy=None, contributors=())
        db.add(Commit(repo_id=rid, sha="stale-10", author_user_id=10, committed_at=STALE))
        db.commit()
        act_as(**ENGINEER)
        r = _create(client, rid)
        assert r.status_code == 403, r.text
        assert "no synced activity" in r.json()["detail"]

    def test_a_stale_pull_request_or_issue_does_not_open_a_report_either(self, client, act_as, db):
        """All three sources _has_activity reads are dated by their own column, so none of
        them can be the one that stays open."""
        rid = _seed_repo(db, gh_id=8, name="stale2", lead=None, deputy=None, contributors=())
        db.add(PullRequest(repo_id=rid, github_pr_id=1, number=1, title="pr", state="open",
                           merged=False, author_user_id=10, gh_created_at=STALE))
        db.add(Issue(repo_id=rid, github_issue_id=1, number=2, title="iss", state="open",
                     author_user_id=10, gh_created_at=STALE))
        db.commit()
        act_as(**ENGINEER)
        assert _create(client, rid).status_code == 403

    def test_recent_work_still_opens_a_report(self, client, act_as, db):
        rid = _seed_repo(db, gh_id=9, name="fresh", lead=None, deputy=None, contributors=(10,))
        act_as(**ENGINEER)
        assert _create(client, rid).status_code == 201

    def test_one_report_per_author_per_repo_per_week(self, client, act_as, repo):
        act_as(**ENGINEER)
        assert _create(client, repo).status_code == 201
        assert _create(client, repo).status_code == 409

    def test_same_engineer_two_repos_same_week(self, client, act_as, db):
        repo_a = _seed_repo(db, gh_id=1, name="alpha")
        repo_b = _seed_repo(db, gh_id=2, name="beta")
        act_as(**ENGINEER)
        assert _create(client, repo_a, week_start="2026-07-20").status_code == 201
        assert _create(client, repo_b, week_start="2026-07-20").status_code == 201

    def test_week_start_is_normalised_to_its_monday(self, client, act_as, repo):
        act_as(**ENGINEER)
        r = _create(client, repo, week_start="2026-07-22")  # a Wednesday
        assert r.json()["week_start"] == "2026-07-20"

    def test_two_engineers_can_each_have_the_same_repo_week(self, client, act_as, repo):
        act_as(**ENGINEER)
        assert _create(client, repo, week_start="2026-07-20").status_code == 201
        act_as(**ENGINEER_2)
        assert _create(client, repo, week_start="2026-07-20").status_code == 201

    def test_requires_a_token(self, client, repo):
        assert _create(client, repo).status_code == 401

    def test_report_for_a_missing_repo_is_404(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client, 9999).status_code == 404

    def test_a_weekly_report_is_about_its_author(self, client, act_as, repo):
        act_as(**ENGINEER)
        body = _create(client, repo).json()
        assert body["kind"] == "weekly"
        assert body["subject_user_id"] == body["author_user_id"] == 10
        assert body["subject_github_login"] is None
        assert body["subjects"] == []

class TestVisibility:
    def _make_report(self, client, act_as, repo):
        act_as(**ENGINEER)
        return _create(client, repo).json()["id"]

    def test_author_reads_own(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**ENGINEER)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_other_engineer_is_forbidden(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**ENGINEER_2)
        assert client.get(f"/reports/{rid}").status_code == 403

    def test_repo_lead_can_read(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**LEAD)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_repo_deputy_can_read(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**DEPUTY)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_manager_who_is_not_lead_or_deputy_is_forbidden(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**MANAGER_NOLEAD)
        assert client.get(f"/reports/{rid}").status_code == 403

    def test_department_admin_can_read(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**DEPT_ADMIN)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_outsider_forbidden(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**OUTSIDER)
        assert client.get(f"/reports/{rid}").status_code == 403

    def test_platform_admin_can_read(self, client, act_as, repo):
        rid = self._make_report(client, act_as, repo)
        act_as(**PLATFORM)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_missing_report_is_404(self, client, act_as):
        act_as(**DEPT_ADMIN)
        assert client.get("/reports/9999").status_code == 404

class TestList:
    def _seed_two_authors(self, client, act_as, repo):
        act_as(**ENGINEER)
        _create(client, repo, week_start="2026-07-20")
        act_as(**ENGINEER_2)
        _create(client, repo, week_start="2026-07-20")

    def test_engineer_sees_only_their_own(self, client, act_as, repo):
        self._seed_two_authors(client, act_as, repo)
        act_as(**ENGINEER)
        body = client.get(f"/reports?repo_id={repo}").json()
        assert body["total"] == 1
        assert body["items"][0]["author_user_id"] == 10

    def test_repo_lead_sees_the_whole_repo(self, client, act_as, repo):
        self._seed_two_authors(client, act_as, repo)
        act_as(**LEAD)
        assert client.get(f"/reports?repo_id={repo}").json()["total"] == 2

    def test_department_admin_sees_the_department(self, client, act_as, repo):
        self._seed_two_authors(client, act_as, repo)
        act_as(**DEPT_ADMIN)
        assert client.get(f"/reports?dept_id={DEPT}").json()["total"] == 2

    def test_outsider_sees_nothing(self, client, act_as, repo):
        self._seed_two_authors(client, act_as, repo)
        act_as(**OUTSIDER)
        assert client.get(f"/reports?repo_id={repo}").json()["total"] == 0

    def test_filter_by_status(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(**ENGINEER_2)
        _create(client, repo, week_start="2026-07-20")
        act_as(**LEAD)
        submitted = client.get(f"/reports?repo_id={repo}&status=submitted").json()
        assert submitted["total"] == 1
        assert submitted["items"][0]["status"] == "submitted"

    def test_pagination_windows_results(self, client, act_as, repo):
        act_as(**ENGINEER)
        for wk in ("2026-07-06", "2026-07-13", "2026-07-20"):
            _create(client, repo, week_start=wk)
        page = client.get(f"/reports?repo_id={repo}&limit=2").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert page["limit"] == 2

class TestWorkflow:
    def test_author_submits_and_history_records_it(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        r = client.post(f"/reports/{rid}/submit")
        assert r.status_code == 200 and r.json()["status"] == "submitted"
        history = client.get(f"/reports/{rid}/approvals").json()["items"]
        assert [h["action"] for h in history] == ["submitted"]

    def test_cannot_submit_an_empty_report(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo, summary_manager="", summary_exec="", next_week_goals="").json()["id"]
        r = client.post(f"/reports/{rid}/submit")
        assert r.status_code == 422, r.text
        assert client.get(f"/reports/{rid}").json()["status"] == "draft"

    def test_whitespace_only_report_cannot_be_submitted(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo, summary_manager="   ", summary_exec="\n", next_week_goals="").json()["id"]
        assert client.post(f"/reports/{rid}/submit").status_code == 422

    def test_a_report_with_one_summary_submits(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo, summary_manager="shipped the auth work").json()["id"]
        r = client.post(f"/reports/{rid}/submit")
        assert r.status_code == 200 and r.json()["status"] == "submitted"

    def test_non_author_cannot_submit(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/submit").status_code == 403

    def test_repo_lead_approves(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**LEAD)
        r = client.post(f"/reports/{rid}/approve")
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert [h["action"] for h in client.get(f"/reports/{rid}/approvals").json()["items"]] == ["submitted", "approved"]

    def test_repo_deputy_also_approves(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**DEPUTY)
        assert client.post(f"/reports/{rid}/approve").status_code == 200

    def test_manager_who_is_not_lead_or_deputy_cannot_approve(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**MANAGER_NOLEAD)
        assert client.post(f"/reports/{rid}/approve").status_code == 403

    def test_department_admin_can_approve(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**DEPT_ADMIN)
        assert client.post(f"/reports/{rid}/approve").status_code == 200

    def test_cannot_approve_a_report_that_was_never_submitted(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/approve").status_code == 409

    def test_reject_records_a_note(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**LEAD)
        r = client.post(f"/reports/{rid}/reject", json={"note": "needs more detail"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        last = client.get(f"/reports/{rid}/approvals").json()["items"][-1]
        assert last["action"] == "rejected" and last["note"] == "needs more detail"

    def test_request_changes_then_edit_and_resubmit(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/request-changes").json()["status"] == "changes_requested"
        act_as(**ENGINEER)
        assert client.patch(f"/reports/{rid}", json={"summary_manager": "v2"}).status_code == 200
        assert client.post(f"/reports/{rid}/submit").json()["status"] == "submitted"
        actions = [h["action"] for h in client.get(f"/reports/{rid}/approvals").json()["items"]]
        assert actions == ["submitted", "changes_requested", "submitted"]

class TestNoSelfApproval:

    def _submit_as(self, client, act_as, who, repo_id):
        act_as(**who)
        rid = _create(client, repo_id).json()["id"]
        assert client.post(f"/reports/{rid}/submit").status_code == 200
        return rid

    def test_platform_admin_cannot_approve_their_own_report(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=3, name="own-pa", contributors=(PLATFORM["user_id"],))
        rid = self._submit_as(client, act_as, PLATFORM, repo_id)
        act_as(**PLATFORM)
        r = client.post(f"/reports/{rid}/approve")
        assert r.status_code == 403, r.text
        assert "your own report" in r.json()["detail"]
        assert client.get(f"/reports/{rid}").json()["status"] == "submitted"

    def test_repo_lead_cannot_approve_their_own_report(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=4, name="own-lead", contributors=(LEAD_ID,))
        rid = self._submit_as(client, act_as, LEAD, repo_id)
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/approve").status_code == 403

    def test_department_admin_cannot_approve_their_own_report(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=5, name="own-da", contributors=(DEPT_ADMIN["user_id"],))
        rid = self._submit_as(client, act_as, DEPT_ADMIN, repo_id)
        act_as(**DEPT_ADMIN)
        assert client.post(f"/reports/{rid}/approve").status_code == 403

    def test_the_author_cannot_reject_or_request_changes_either(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=6, name="own-verbs", contributors=(PLATFORM["user_id"],))
        rid = self._submit_as(client, act_as, PLATFORM, repo_id)
        act_as(**PLATFORM)
        assert client.post(f"/reports/{rid}/reject").status_code == 403
        assert client.post(f"/reports/{rid}/request-changes").status_code == 403

    def test_a_different_platform_admin_still_approves(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=7, name="other-pa", contributors=(PLATFORM["user_id"],))
        rid = self._submit_as(client, act_as, PLATFORM, repo_id)
        act_as(user_id=98, memberships=[], is_platform_admin=True)
        r = client.post(f"/reports/{rid}/approve")
        assert r.status_code == 200 and r.json()["status"] == "approved"

    def test_your_own_report_never_sits_in_your_review_queue(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=8, name="queue-pa", contributors=(PLATFORM["user_id"],))
        self._submit_as(client, act_as, PLATFORM, repo_id)
        act_as(**PLATFORM)
        assert client.get("/reports/review-queue").json()["total"] == 0


class TestEdit:
    def test_author_edits_a_draft(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        r = client.patch(f"/reports/{rid}", json={"summary_manager": "shipped the thing"})
        assert r.status_code == 200 and r.json()["summary_manager"] == "shipped the thing"

    def test_a_submitted_report_is_locked(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**ENGINEER)
        assert client.patch(f"/reports/{rid}", json={"summary_manager": "x"}).status_code == 409

    def test_only_the_author_may_edit(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        act_as(**LEAD)
        assert client.patch(f"/reports/{rid}", json={"summary_manager": "x"}).status_code == 403

class TestComments:
    def test_a_reader_can_comment(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/comments", json={"body": "nice work"}).status_code == 201
        comments = client.get(f"/reports/{rid}/comments").json()["items"]
        assert len(comments) == 1
        assert comments[0]["author_user_id"] == LEAD_ID and comments[0]["body"] == "nice work"

    def test_a_non_reader_cannot_comment(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        act_as(**OUTSIDER)
        assert client.post(f"/reports/{rid}/comments", json={"body": "hi"}).status_code == 403

    def test_empty_comment_is_rejected(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        assert client.post(f"/reports/{rid}/comments", json={"body": ""}).status_code == 422

class TestReportDelete:
    def test_author_deletes_own_draft(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        assert client.delete(f"/reports/{rid}").status_code == 204
        act_as(**ENGINEER)
        assert client.get(f"/reports/{rid}").status_code == 404

    def test_a_submitted_report_can_never_be_deleted_by_anyone(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        for who in (ENGINEER, LEAD, DEPT_ADMIN, PLATFORM):
            act_as(**who)
            assert client.delete(f"/reports/{rid}").status_code == 409, who

    def test_admins_cannot_delete_someone_elses_draft(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        for who in (DEPT_ADMIN, PLATFORM, ENGINEER_2):
            act_as(**who)
            assert client.delete(f"/reports/{rid}").status_code == 403, who

    def test_deleting_a_draft_takes_its_comments_with_it(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        client.post(f"/reports/{rid}/comments", json={"body": "wip note"})
        assert client.delete(f"/reports/{rid}").status_code == 204
        act_as(**ENGINEER)
        assert client.get(f"/reports/{rid}").status_code == 404
        assert client.get(f"/reports/{rid}/comments").status_code == 404

class TestCommentEditDelete:
    def _make_comment(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        cid = client.post(f"/reports/{rid}/comments", json={"body": "first"}).json()["id"]
        return rid, cid

    def test_author_edits_own_comment_and_edited_at_is_stamped(self, client, act_as, repo):
        rid, cid = self._make_comment(client, act_as, repo)
        act_as(**ENGINEER)
        r = client.patch(f"/reports/{rid}/comments/{cid}", json={"body": "revised"})
        assert r.status_code == 200
        assert r.json()["body"] == "revised"
        assert r.json()["edited_at"] is not None

    def test_non_author_cannot_edit(self, client, act_as, repo):
        rid, cid = self._make_comment(client, act_as, repo)
        act_as(**LEAD)
        assert client.patch(f"/reports/{rid}/comments/{cid}", json={"body": "x"}).status_code == 403

    def test_author_deletes_own_comment(self, client, act_as, repo):
        rid, cid = self._make_comment(client, act_as, repo)
        act_as(**ENGINEER)
        assert client.delete(f"/reports/{rid}/comments/{cid}").status_code == 204
        assert client.get(f"/reports/{rid}/comments").json()["total"] == 0

    def test_non_author_cannot_delete(self, client, act_as, repo):
        rid, cid = self._make_comment(client, act_as, repo)
        act_as(**LEAD)
        assert client.delete(f"/reports/{rid}/comments/{cid}").status_code == 403

    def test_comment_must_belong_to_the_report_in_the_path(self, client, act_as, repo):
        rid, cid = self._make_comment(client, act_as, repo)
        act_as(**ENGINEER)
        other = _create(client, repo, week_start="2026-06-01").json()["id"]
        assert client.patch(f"/reports/{other}/comments/{cid}", json={"body": "x"}).status_code == 404

class TestListsArePaginated:
    def test_comments_paginate(self, client, act_as, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]
        for i in range(3):
            client.post(f"/reports/{rid}/comments", json={"body": f"c{i}"})
        page = client.get(f"/reports/{rid}/comments?limit=2").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert page["limit"] == 2

    def test_approvals_paginate(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**LEAD)
        client.post(f"/reports/{rid}/request-changes")
        act_as(**ENGINEER)
        client.post(f"/reports/{rid}/submit")
        page = client.get(f"/reports/{rid}/approvals?limit=2").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2

class TestStatusFilterValidation:
    def test_unknown_status_value_is_rejected(self, client, act_as, repo):
        act_as(**ENGINEER)
        assert client.get(f"/reports?repo_id={repo}&status=aproved").status_code == 422

    def test_valid_status_value_is_accepted(self, client, act_as, repo):
        act_as(**ENGINEER)
        assert client.get(f"/reports?repo_id={repo}&status=draft").status_code == 200

class TestDepartmentBackfill:

    def test_assigning_a_department_backfills_existing_reports(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=7, name="unassigned", dept_id=None, lead=None, deputy=None)
        act_as(**ENGINEER)
        rid = _create(client, repo_id).json()["id"]
        assert client.get(f"/reports/{rid}").json()["dept_id"] is None

        act_as(**DEPT_ADMIN)
        assert client.get(f"/reports/{rid}").status_code == 403

        act_as(**PLATFORM)
        assert client.put(f"/github/repositories/{repo_id}/department/{DEPT}").status_code == 200

        act_as(**DEPT_ADMIN)
        got = client.get(f"/reports/{rid}")
        assert got.status_code == 200 and got.json()["dept_id"] == DEPT
        assert client.get(f"/reports?dept_id={DEPT}").json()["total"] == 1

    def test_filing_an_unfiled_repo_makes_its_report_approvable_by_the_dept_admin(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=9, name="from-sync", dept_id=None, lead=None, deputy=None)
        rid = _open_submitted(client, act_as, repo_id)

        act_as(**DEPT_ADMIN)
        assert client.post(f"/reports/{rid}/approve").status_code == 403

        act_as(**PLATFORM)
        backlog = client.get("/github/repositories/unfiled").json()
        assert [r["id"] for r in backlog["items"]] == [repo_id]
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [repo_id]}).status_code == 200

        act_as(**DEPT_ADMIN)
        approved = client.post(f"/reports/{rid}/approve")
        assert approved.status_code == 200 and approved.json()["status"] == "approved"

    def test_refiling_moves_reports_to_the_new_department(self, client, act_as, db):
        repo_id = _seed_repo(db, gh_id=8, name="movable", dept_id=DEPT)
        act_as(**ENGINEER)
        _create(client, repo_id)
        act_as(**PLATFORM)
        assert client.put(f"/github/repositories/{repo_id}/department/2").status_code == 200
        assert client.get("/reports?dept_id=2").json()["total"] == 1
        act_as(**DEPT_ADMIN)
        assert client.get(f"/reports?dept_id={DEPT}").json()["total"] == 0

class TestReviewQueue:

    def test_lead_sees_submitted_reports_across_all_their_repos(self, client, act_as, db):
        repo_a = _seed_repo(db, gh_id=1, name="alpha")
        repo_b = _seed_repo(db, gh_id=2, name="beta")
        _open_submitted(client, act_as, repo_a)
        _open_submitted(client, act_as, repo_b)
        act_as(**ENGINEER_2)
        _create(client, repo_a, week_start="2026-06-01")
        act_as(**LEAD)
        body = client.get("/reports/review-queue").json()
        assert body["total"] == 2
        assert {i["repo_id"] for i in body["items"]} == {repo_a, repo_b}
        assert all(i["status"] == "submitted" for i in body["items"])

    def test_deputy_sees_the_queue_too(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(**DEPUTY)
        assert client.get("/reports/review-queue").json()["total"] == 1

    def test_author_engineer_queue_is_empty(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(**ENGINEER)
        assert client.get("/reports/review-queue").json()["total"] == 0

    def test_manager_who_leads_nothing_sees_empty_queue(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(**MANAGER_NOLEAD)
        assert client.get("/reports/review-queue").json()["total"] == 0

    def test_department_admin_sees_their_departments_queue(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(**DEPT_ADMIN)
        assert client.get("/reports/review-queue").json()["total"] == 1

    def test_admin_of_another_department_sees_nothing(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(user_id=41, memberships=[{"dept_id": 2, "team_id": None, "role": "admin"}])
        assert client.get("/reports/review-queue").json()["total"] == 0

    def test_platform_admin_sees_every_submitted_report(self, client, act_as, repo):
        _open_submitted(client, act_as, repo)
        act_as(**PLATFORM)
        assert client.get("/reports/review-queue").json()["total"] == 1

    def test_a_decided_report_leaves_the_queue(self, client, act_as, repo):
        rid = _open_submitted(client, act_as, repo)
        act_as(**LEAD)
        client.post(f"/reports/{rid}/approve")
        assert client.get("/reports/review-queue").json()["total"] == 0

    def test_a_user_with_no_memberships_gets_an_empty_queue(self, client, act_as, repo):
        # Nothing to review is not a broken session: a 401 here would send shared API
        # clients off to refresh a token that was fine.
        _open_submitted(client, act_as, repo)
        act_as(**UNPLACED)
        response = client.get("/reports/review-queue")
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    def test_requires_a_token(self, client, repo):
        assert client.get("/reports/review-queue").status_code == 401

class TestNewReportColumns:
    """0010 backfilled repo_full_name/range_start/range_end onto existing rows; the
    create path has to fill them too or every new report is the shape the backfill was
    written to repair."""

    def test_a_created_report_carries_the_repo_name_and_range(self, client, act_as, db, repo):
        act_as(**ENGINEER)
        rid = _create(client, repo).json()["id"]

        row = db.get(Report, rid)
        monday = _this_monday()
        assert row.repo_full_name == "org/alpha"
        assert row.range_start == monday
        assert row.range_end == monday + timedelta(days=6)
        # The backfill's shape: range_start is week_start and the range is a full week.
        assert row.range_start == row.week_start
        assert (row.range_end - row.range_start).days == 6

class TestWeeklyUniqueIndexIsPartial:
    """The unique index is restricted to kind = 'weekly'. SQLite drops an unqualified
    postgresql_where, so without sqlite_where the suite enforced a stricter rule than
    Postgres and passed for the wrong reason."""

    def test_the_sqlite_ddl_carries_the_predicate(self):
        from sqlalchemy.dialects import sqlite
        from sqlalchemy.schema import CreateIndex

        index = next(i for i in Report.__table__.indexes if i.name == "uq_report_author_repo_week")
        ddl = str(CreateIndex(index).compile(dialect=sqlite.dialect()))
        assert "CREATE UNIQUE INDEX" in ddl
        assert "WHERE kind = 'weekly'" in ddl

    def test_an_adhoc_row_may_duplicate_a_weekly_rows_repo_and_week(self, client, act_as, db, repo):
        act_as(**ENGINEER)
        assert _create(client, repo).status_code == 201
        week = _this_monday()

        db.add(Report(
            author_user_id=10,
            subject_user_id=10,
            repo_id=repo,
            repo_full_name="org/alpha",
            dept_id=DEPT,
            kind=REPORT_KIND_ADHOC,
            week_start=week,
            range_start=week,
            range_end=week + timedelta(days=6),
        ))
        db.commit()

        rows = db.query(Report).filter(Report.repo_id == repo, Report.week_start == week).all()
        assert sorted(r.kind for r in rows) == ["adhoc", "weekly"]

    def test_a_second_weekly_row_is_still_refused(self, client, act_as, repo):
        act_as(**ENGINEER)
        assert _create(client, repo).status_code == 201
        assert _create(client, repo).status_code == 409


class TestProviderBusyIsNotProviderBroken:
    def test_a_weekly_report_rate_limit_is_503_with_a_retry_after(self, client, act_as, db, monkeypatch):
        from app.services import generation as generation_service
        from app.services.provider_limits import ProviderRateLimited

        monkeypatch.setattr(
            generation_service, "generate_report",
            lambda *a, **k: (_ for _ in ()).throw(ProviderRateLimited(7.0, "OpenAI")),
        )
        act_as(**LEAD)

        r = client.post("/reports/generate", json={"repo_id": 1, "week_start": "2026-07-06"})

        assert r.status_code == 503
        assert r.headers["Retry-After"] == "7"
        assert "busy right now" in r.json()["detail"]

    def test_an_adhoc_report_rate_limit_is_503_with_a_retry_after(self, client, act_as, db, monkeypatch):
        from app.services import adhoc as adhoc_service
        from app.services.provider_limits import ProviderRateLimited

        monkeypatch.setattr(
            adhoc_service, "generate_adhoc_report",
            lambda *a, **k: (_ for _ in ()).throw(ProviderRateLimited(3.0, "OpenAI")),
        )
        act_as(**LEAD)

        r = client.post("/reports/adhoc", json={
            "repo_full_name": "org/alpha", "subjects": [{"github_login": "dev"}],
            "range_start": "2026-07-01", "range_end": "2026-07-07",
        })

        assert r.status_code == 503
        assert r.headers["Retry-After"] == "3"
        assert "busy right now" in r.json()["detail"]
