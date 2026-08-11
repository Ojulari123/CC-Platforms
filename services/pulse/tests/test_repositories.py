from datetime import date, datetime, timezone
from app.models import Commit, PullRequest, Report, Repository, Review

DEPT = 1
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": DEPT, "team_id": None, "role": "admin"}])
ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
OTHER_ADMIN = dict(user_id=31, memberships=[{"dept_id": 2, "team_id": None, "role": "admin"}])
MULTI_ADMIN = dict(user_id=32, memberships=[
    {"dept_id": DEPT, "team_id": None, "role": "admin"},
    {"dept_id": 2, "team_id": None, "role": "admin"},
])


def _seed_repo(db, dept_id=None, lead=None, deputy=None, gh_id=1, name="alpha"):
    repo = Repository(
        github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name,
        dept_id=dept_id, lead_user_id=lead, deputy_user_id=deputy,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo.id


def _seed_report(db, repo_id, dept_id=None, author=10, week=date(2026, 7, 20)):
    report = Report(author_user_id=author, repo_id=repo_id, dept_id=dept_id,
                    week_start=week, status="draft", summary_manager="did the work")
    db.add(report)
    db.commit()
    db.refresh(report)
    return report.id


def _seed_commit(db, repo_id, user_id=10, sha="c1"):
    db.add(Commit(repo_id=repo_id, sha=sha, author_user_id=user_id, message="m",
                  committed_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)))
    db.commit()


class TestListAndGet:
    def test_list_requires_auth(self, client):
        assert client.get("/github/repositories").status_code == 401

    def test_list_returns_repos(self, client, act_as, db):
        _seed_repo(db, dept_id=DEPT, gh_id=1, name="alpha")
        _seed_repo(db, dept_id=DEPT, gh_id=2, name="beta")
        act_as(**ENGINEER)
        assert client.get("/github/repositories").json()["total"] == 2

    def test_get_one(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").json()["id"] == rid

    def test_get_missing_is_404(self, client, act_as):
        act_as(**PLATFORM)
        assert client.get("/github/repositories/9999").status_code == 404

    def test_list_hides_repos_outside_the_callers_scope(self, client, act_as, db):
        _seed_repo(db, dept_id=DEPT, gh_id=1, name="alpha")
        _seed_repo(db, dept_id=2, gh_id=2, name="other-dept")
        _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        act_as(**ENGINEER)
        body = client.get("/github/repositories").json()
        assert body["total"] == 1
        assert [r["name"] for r in body["items"]] == ["alpha"]

    def test_get_a_repo_outside_the_callers_scope_is_404_not_403(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=2)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 404

    def test_a_lead_sees_their_repo_outside_their_department(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=2, lead=10)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        assert client.get("/github/repositories").json()["total"] == 1

    def test_a_deputy_sees_their_repo_outside_their_department(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=2, deputy=10)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200

    def test_a_contributor_sees_an_unfiled_repo_they_worked_in(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        _seed_commit(db, rid, user_id=10)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        body = client.get("/github/repositories").json()
        assert body["total"] == 1 and [r["name"] for r in body["items"]] == ["unfiled"]

    def test_a_pr_reviewer_sees_the_unfiled_repo_they_reviewed_in(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        pr = PullRequest(repo_id=rid, github_pr_id=1, number=7, title="pr", state="open", merged=False,
                         author_user_id=11, gh_created_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
        db.add(pr)
        db.commit()
        db.refresh(pr)
        db.add(Review(pull_request_id=pr.id, github_review_id=1, reviewer_user_id=10, state="approved",
                      submitted_at=datetime(2026, 7, 19, 13, 0, tzinfo=timezone.utc)))
        db.commit()
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        assert client.get("/github/repositories").json()["total"] == 1

    def test_someone_elses_work_does_not_reveal_an_unfiled_repo(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        _seed_commit(db, rid, user_id=11)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 404
        assert client.get("/github/repositories").json()["total"] == 0

    def test_working_in_a_repo_does_not_let_you_administer_it(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        _seed_commit(db, rid, user_id=10)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        assert client.put(f"/github/repositories/{rid}/lead/20").status_code == 403
        assert client.put(f"/github/repositories/{rid}/department/{DEPT}").status_code == 403

    def test_platform_admin_sees_every_repo(self, client, act_as, db):
        _seed_repo(db, dept_id=2, gh_id=1, name="alpha")
        rid = _seed_repo(db, dept_id=None, gh_id=2, name="unfiled")
        act_as(**PLATFORM)
        assert client.get("/github/repositories").json()["total"] == 2
        assert client.get(f"/github/repositories/{rid}").status_code == 200

    def test_list_pages_in_sql(self, client, act_as, db):
        for i, name in enumerate(("alpha", "beta", "gamma"), start=1):
            _seed_repo(db, dept_id=DEPT, gh_id=i, name=name)
        act_as(**ENGINEER)
        body = client.get("/github/repositories?limit=2&offset=1").json()
        assert body["total"] == 3
        assert [r["name"] for r in body["items"]] == ["beta", "gamma"]

    def test_tracked_only_still_narrows(self, client, act_as, db):
        _seed_repo(db, dept_id=DEPT, gh_id=1, name="alpha")
        rid = _seed_repo(db, dept_id=DEPT, gh_id=2, name="beta")
        db.get(Repository, rid).is_tracked = False
        db.commit()
        act_as(**ENGINEER)
        assert client.get("/github/repositories?tracked_only=true").json()["total"] == 1


class TestAssignDepartment:
    def test_platform_admin_can_file_under_any_department(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**PLATFORM)
        r = client.put(f"/github/repositories/{rid}/department/{DEPT}")
        assert r.status_code == 200 and r.json()["dept_id"] == DEPT

    def test_admin_can_move_repo_between_departments_they_both_admin(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**MULTI_ADMIN)
        assert client.put(f"/github/repositories/{rid}/department/2").status_code == 200

    def test_admin_cannot_capture_repo_from_a_department_they_dont_admin(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=2)
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/{rid}/department/{DEPT}").status_code == 403

    def test_dept_admin_can_file_an_unfiled_repo(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/{rid}/department/{DEPT}").status_code == 200

    def test_admin_of_another_department_cannot(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**OTHER_ADMIN)
        assert client.put(f"/github/repositories/{rid}/department/{DEPT}").status_code == 403

    def test_engineer_cannot(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**ENGINEER)
        assert client.put(f"/github/repositories/{rid}/department/{DEPT}").status_code == 403


class TestUnfiledBacklog:

    def test_requires_auth(self, client):
        assert client.get("/github/repositories/unfiled").status_code == 401

    def test_platform_admin_sees_only_the_unfiled_ones(self, client, act_as, db):
        _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        _seed_repo(db, dept_id=None, gh_id=2, name="beta")
        _seed_repo(db, dept_id=DEPT, gh_id=3, name="filed")
        act_as(**PLATFORM)
        body = client.get("/github/repositories/unfiled").json()
        assert body["total"] == 2
        assert [r["name"] for r in body["items"]] == ["alpha", "beta"]

    def test_a_dept_admin_sees_a_repo_they_never_worked_in(self, client, act_as, db):
        _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        act_as(**DEPT_ADMIN)
        assert client.get("/github/repositories").json()["total"] == 0
        assert client.get("/github/repositories/unfiled").json()["total"] == 1

    def test_an_admin_of_any_department_may_look(self, client, act_as, db):
        _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        act_as(**OTHER_ADMIN)
        assert client.get("/github/repositories/unfiled").json()["total"] == 1

    def test_engineer_cannot(self, client, act_as, db):
        _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        act_as(**ENGINEER)
        assert client.get("/github/repositories/unfiled").status_code == 403

    def test_filing_clears_it_from_the_backlog(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        act_as(**PLATFORM)
        assert client.get("/github/repositories/unfiled").json()["total"] == 1
        client.put(f"/github/repositories/{rid}/department/{DEPT}")
        assert client.get("/github/repositories/unfiled").json()["total"] == 0

    def test_pages_in_sql(self, client, act_as, db):
        for i, name in enumerate(("alpha", "beta", "gamma"), start=1):
            _seed_repo(db, dept_id=None, gh_id=i, name=name)
        act_as(**PLATFORM)
        body = client.get("/github/repositories/unfiled?limit=2&offset=1").json()
        assert body["total"] == 3
        assert [r["name"] for r in body["items"]] == ["beta", "gamma"]


class TestBulkAssignDepartment:

    def test_requires_auth(self, client, db):
        rid = _seed_repo(db, dept_id=None)
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [rid]}).status_code == 401

    def test_platform_admin_files_several_at_once(self, client, act_as, db):
        a = _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        b = _seed_repo(db, dept_id=None, gh_id=2, name="beta")
        act_as(**PLATFORM)
        r = client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [a, b]})
        assert r.status_code == 200
        assert [row["dept_id"] for row in r.json()] == [DEPT, DEPT]

    def test_it_restamps_existing_reports(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        report_id = _seed_report(db, rid)
        act_as(**PLATFORM)
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [rid]}).status_code == 200
        db.expire_all()
        assert db.get(Report, report_id).dept_id == DEPT

    def test_dept_admin_files_unfiled_repos_into_their_own_department(self, client, act_as, db):
        a = _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        b = _seed_repo(db, dept_id=None, gh_id=2, name="beta")
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [a, b]}).status_code == 200

    def test_one_repo_they_cannot_file_rolls_back_the_whole_batch(self, client, act_as, db):
        ok = _seed_repo(db, dept_id=None, gh_id=1, name="alpha")
        owned_elsewhere = _seed_repo(db, dept_id=2, gh_id=2, name="beta")
        act_as(**DEPT_ADMIN)
        r = client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [ok, owned_elsewhere]})
        assert r.status_code == 403
        db.expire_all()
        assert db.get(Repository, ok).dept_id is None
        assert db.get(Repository, owned_elsewhere).dept_id == 2

    def test_a_missing_repo_id_is_404_and_nothing_changes(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**PLATFORM)
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [rid, 9999]}).status_code == 404
        db.expire_all()
        assert db.get(Repository, rid).dept_id is None

    def test_engineer_cannot(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**ENGINEER)
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [rid]}).status_code == 403

    def test_an_empty_batch_is_rejected(self, client, act_as):
        act_as(**PLATFORM)
        assert client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": []}).status_code == 422

    def test_repeated_ids_are_filed_once(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**PLATFORM)
        r = client.put(f"/github/repositories/department/{DEPT}", json={"repo_ids": [rid, rid]})
        assert r.status_code == 200 and len(r.json()) == 1


class TestAssignLeadDeputy:
    def test_dept_admin_sets_lead_and_deputy(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/{rid}/lead/20").json()["lead_user_id"] == 20
        assert client.put(f"/github/repositories/{rid}/deputy/25").json()["deputy_user_id"] == 25

    def test_lead_and_deputy_must_differ(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT, lead=20)
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/{rid}/deputy/20").status_code == 400

    def test_platform_admin_can_assign_on_a_repo_with_no_department(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**PLATFORM)
        assert client.put(f"/github/repositories/{rid}/lead/20").status_code == 200

    def test_dept_admin_cannot_assign_on_an_unfiled_repo(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/{rid}/lead/20").status_code == 403

    def test_engineer_cannot_assign(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**ENGINEER)
        assert client.put(f"/github/repositories/{rid}/lead/20").status_code == 403

    def test_clear_lead_and_deputy(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT, lead=20, deputy=25)
        act_as(**DEPT_ADMIN)
        assert client.delete(f"/github/repositories/{rid}/lead").json()["lead_user_id"] is None
        assert client.delete(f"/github/repositories/{rid}/deputy").json()["deputy_user_id"] is None

    def test_assignment_requires_auth(self, client, db):
        rid = _seed_repo(db, dept_id=DEPT)
        assert client.put(f"/github/repositories/{rid}/lead/20").status_code == 401


class TestApproverCandidates:
    def _ids(self, client, rid):
        return [c["user_id"] for c in client.get(f"/github/repositories/{rid}/approver-candidates").json()["items"]]

    def test_contributors_are_offered(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        _seed_commit(db, rid, user_id=10)
        _seed_commit(db, rid, user_id=11, sha="c2")
        act_as(**DEPT_ADMIN)
        assert self._ids(client, rid) == [10, 11]

    def test_a_reviewer_counts_as_a_contributor(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        pr = PullRequest(repo_id=rid, github_pr_id=1, number=7, title="pr", state="open", merged=False,
                         author_user_id=11, gh_created_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
        db.add(pr)
        db.commit()
        db.refresh(pr)
        db.add(Review(pull_request_id=pr.id, github_review_id=1, reviewer_user_id=10, state="approved",
                      submitted_at=datetime(2026, 7, 19, 13, 0, tzinfo=timezone.utc)))
        db.commit()
        act_as(**DEPT_ADMIN)
        assert self._ids(client, rid) == [10, 11]

    def test_the_sitting_lead_is_offered_even_with_no_activity(self, client, act_as, db):
        """Otherwise a lead assigned by id through the API drops out of the picker and
        reads as unset."""
        rid = _seed_repo(db, dept_id=DEPT, lead=20, deputy=25)
        act_as(**DEPT_ADMIN)
        body = client.get(f"/github/repositories/{rid}/approver-candidates").json()["items"]
        by_id = {c["user_id"]: c for c in body}
        assert by_id[20]["is_lead"] is True and by_id[20]["has_activity"] is False
        assert by_id[25]["is_deputy"] is True

    def test_activity_and_post_are_reported_separately(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT, lead=10)
        _seed_commit(db, rid, user_id=10)
        act_as(**DEPT_ADMIN)
        entry = client.get(f"/github/repositories/{rid}/approver-candidates").json()["items"][0]
        assert entry["has_activity"] is True and entry["is_lead"] is True

    def test_unattributed_activity_is_left_out(self, client, act_as, db):
        """Sync leaves author_user_id null for a GitHub login it can't match to an
        identity user, and a null is not a person we can name."""
        rid = _seed_repo(db, dept_id=DEPT)
        _seed_commit(db, rid, user_id=None)
        act_as(**DEPT_ADMIN)
        assert self._ids(client, rid) == []

    def test_engineer_cannot_enumerate_contributors(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        _seed_commit(db, rid, user_id=10)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}/approver-candidates").status_code == 403

    def test_admin_of_another_department_cannot(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**OTHER_ADMIN)
        assert client.get(f"/github/repositories/{rid}/approver-candidates").status_code == 403

    def test_missing_repo_is_404(self, client, act_as):
        act_as(**PLATFORM)
        assert client.get("/github/repositories/9999/approver-candidates").status_code == 404

    def test_requires_auth(self, client, db):
        rid = _seed_repo(db, dept_id=DEPT)
        assert client.get(f"/github/repositories/{rid}/approver-candidates").status_code == 401


class TestTracking:

    def test_dept_admin_can_untrack_and_retrack(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**DEPT_ADMIN)
        assert client.delete(f"/github/repositories/{rid}/tracked").json()["is_tracked"] is False
        assert client.put(f"/github/repositories/{rid}/tracked").json()["is_tracked"] is True

    def test_platform_admin_can_untrack_an_unfiled_repo(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=None)
        act_as(**PLATFORM)
        assert client.delete(f"/github/repositories/{rid}/tracked").status_code == 200

    def test_engineer_cannot_untrack(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**ENGINEER)
        assert client.delete(f"/github/repositories/{rid}/tracked").status_code == 403
        assert db.get(Repository, rid).is_tracked is True

    def test_admin_of_another_department_cannot_untrack(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**OTHER_ADMIN)
        assert client.delete(f"/github/repositories/{rid}/tracked").status_code == 403

    def test_untracking_requires_auth(self, client, db):
        rid = _seed_repo(db, dept_id=DEPT)
        assert client.delete(f"/github/repositories/{rid}/tracked").status_code == 401

    def test_untracking_does_not_hide_the_repo(self, client, act_as, db):
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**DEPT_ADMIN)
        client.delete(f"/github/repositories/{rid}/tracked")
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        assert client.get("/github/repositories").json()["total"] == 1
        assert client.get("/github/repositories?tracked_only=true").json()["total"] == 0
