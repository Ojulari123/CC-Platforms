"""filing a repo under a department and naming its lead +
deputy. Assignment is done by a department admin (of the repo's dept) or a
platform admin; a repo's lead and deputy must differ."""

from datetime import datetime, timezone
from app.models import Commit, PullRequest, Repository, Review

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
        # 404 on purpose: a 403 would confirm that a private repo by that id exists.
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
        # A freshly synced repo has no department yet; without this the sync looks
        # like it did nothing until an admin files it.
        rid = _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        _seed_commit(db, rid, user_id=10)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        body = client.get("/github/repositories").json()
        assert body["total"] == 1 and [r["name"] for r in body["items"]] == ["unfiled"]

    def test_a_pr_reviewer_sees_the_unfiled_repo_they_reviewed_in(self, client, act_as, db):
        # "Worked in" is activity's definition, so reviewing counts, not just committing.
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
        # 404, not 403 — the existence of an unfiled private repo stays hidden.
        rid = _seed_repo(db, dept_id=None, gh_id=3, name="unfiled")
        _seed_commit(db, rid, user_id=11)
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 404
        assert client.get("/github/repositories").json()["total"] == 0

    def test_working_in_a_repo_does_not_let_you_administer_it(self, client, act_as, db):
        # Visibility only: seeing the repo must not come with lead/department rights.
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
        # Admin of the target dept (1) but not the repo's current dept (2): rejected.
        rid = _seed_repo(db, dept_id=2)
        act_as(**DEPT_ADMIN)
        assert client.put(f"/github/repositories/{rid}/department/{DEPT}").status_code == 403

    def test_dept_admin_can_file_an_unfiled_repo(self, client, act_as, db):
        # No current owner to take it from, so an admin of the target dept may file it.
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


class TestTracking:
    """Switching a repo's sync off and on. Same admin rule as lead/deputy."""

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
        """is_tracked is a sync switch, not a visibility rule — the history and the
        reports on an untracked repo stay readable, and it's still listable so an
        admin can turn it back on."""
        rid = _seed_repo(db, dept_id=DEPT)
        act_as(**DEPT_ADMIN)
        client.delete(f"/github/repositories/{rid}/tracked")
        act_as(**ENGINEER)
        assert client.get(f"/github/repositories/{rid}").status_code == 200
        assert client.get("/github/repositories").json()["total"] == 1
        assert client.get("/github/repositories?tracked_only=true").json()["total"] == 0
