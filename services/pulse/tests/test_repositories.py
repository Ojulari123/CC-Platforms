"""filing a repo under a department and naming its lead +
deputy. Assignment is done by a department admin (of the repo's dept) or a
platform admin; a repo's lead and deputy must differ."""

from app.models import Repository

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
