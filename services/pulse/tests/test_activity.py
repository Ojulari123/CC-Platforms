from datetime import datetime, timedelta, timezone
from app.models import Commit, Issue, PullRequest, Repository, Review

ENGINEER = dict(user_id=10, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
ENGINEER_2 = dict(user_id=11, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": 1, "team_id": None, "role": "admin"}])
OTHER_DEPT_ADMIN = dict(user_id=31, memberships=[{"dept_id": 2, "team_id": None, "role": "admin"}])
LEAD = dict(user_id=20, memberships=[{"dept_id": 1, "team_id": None, "role": "manager"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)

# Seeded activity is dated relative to now: viewing someone else's activity is bounded by
# the same rolling window as repo visibility, so fixed dates would age out of it.
def _dt(days_ago):
    return datetime.now(timezone.utc) - timedelta(days=days_ago, hours=12)

def _seed_repo(db, gh_id=1, name="alpha", lead=None, dept=1):
    repo = Repository(github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name, lead_user_id=lead, dept_id=dept)
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo

def _seed_activity(db, user_id=10, lead=None):
    repo = _seed_repo(db, lead=lead)
    db.add(Commit(repo_id=repo.id, sha="a1", author_user_id=user_id, message="newer", committed_at=_dt(2)))
    db.add(Commit(repo_id=repo.id, sha="a2", author_user_id=user_id, message="older", committed_at=_dt(12)))
    pr = PullRequest(repo_id=repo.id, github_pr_id=1, number=7, title="pr", state="open", merged=False,
                     author_user_id=user_id, gh_created_at=_dt(3))
    db.add(pr)
    db.commit()
    db.refresh(pr)
    db.add(Review(pull_request_id=pr.id, github_review_id=1, reviewer_user_id=user_id, state="approved", submitted_at=_dt(3)))
    db.add(Issue(repo_id=repo.id, github_issue_id=1, number=3, title="iss", state="open", author_user_id=user_id, gh_created_at=_dt(4)))
    db.commit()
    return repo.id

class TestOwnActivity:
    def test_counts_and_recent(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER)
        body = client.get("/activity/me").json()
        assert body["counts"] == {"commits": 2, "pull_requests": 1, "reviews": 1, "issues": 1}
        assert body["recent_commits"][0]["sha"] == "a1"

    def test_view_own_by_id(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER)
        assert client.get("/activity/10").status_code == 200

    def test_since_narrows(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER)
        since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        body = client.get(f"/activity/me?since={since}").json()
        assert body["counts"]["commits"] == 1

    def test_repo_filter(self, client, act_as, db):
        repo1 = _seed_activity(db)
        repo2 = _seed_repo(db, gh_id=2, name="beta")
        db.add(Commit(repo_id=repo2.id, sha="b1", author_user_id=10, message="beta", committed_at=_dt(1)))
        db.commit()
        act_as(**ENGINEER)
        assert client.get(f"/activity/me?repo_id={repo1}").json()["counts"]["commits"] == 2
        assert client.get(f"/activity/me?repo_id={repo2.id}").json()["counts"]["commits"] == 1

    def test_requires_a_token(self, client):
        assert client.get("/activity/me").status_code == 401

def _assert_empty(body):
    assert body["counts"] == {"commits": 0, "pull_requests": 0, "reviews": 0, "issues": 0}
    assert body["recent_commits"] == [] and body["recent_pull_requests"] == []
    assert body["recent_reviews"] == [] and body["recent_issues"] == []

class TestViewingOthers:
    def test_other_engineer_sees_an_empty_response(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER_2)
        r = client.get("/activity/10")
        assert r.status_code == 200
        _assert_empty(r.json())

    def test_a_user_who_does_not_exist_is_indistinguishable_from_one_out_of_scope(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER_2)
        real, unknown = client.get("/activity/10"), client.get("/activity/12345")
        assert real.status_code == unknown.status_code == 200
        _assert_empty(real.json())
        _assert_empty(unknown.json())

    def test_platform_admin_can_view(self, client, act_as, db):
        _seed_activity(db)
        act_as(**PLATFORM)
        assert client.get("/activity/10").status_code == 200

    def test_department_admin_can_view(self, client, act_as, db):
        _seed_activity(db)
        act_as(**DEPT_ADMIN)
        assert client.get("/activity/10").status_code == 200

    def test_department_admin_of_another_department_sees_nothing(self, client, act_as, db):
        _seed_activity(db)
        act_as(**OTHER_DEPT_ADMIN)
        r = client.get("/activity/10")
        assert r.status_code == 200
        _assert_empty(r.json())

    def test_department_admin_sees_nothing_once_the_targets_work_is_stale(self, client, act_as, db):
        """The overlap is computed from the target's activity, and that side is windowed
        too: an engineer who left the department months ago stops showing up under their
        old admin at the same moment the repo stops being readable to them."""
        repo = _seed_repo(db)
        db.add(Commit(repo_id=repo.id, sha="old", author_user_id=10, message="c", committed_at=_dt(400)))
        db.commit()
        act_as(**DEPT_ADMIN)
        r = client.get("/activity/10")
        assert r.status_code == 200
        _assert_empty(r.json())

    def test_department_admin_sees_no_activity_from_an_unfiled_repo(self, client, act_as, db):
        repo = _seed_repo(db, gh_id=5, name="unfiled", dept=None)
        db.add(Commit(repo_id=repo.id, sha="u1", author_user_id=10, message="c", committed_at=_dt(2)))
        db.commit()
        act_as(**DEPT_ADMIN)
        r = client.get("/activity/10")
        assert r.status_code == 200
        _assert_empty(r.json())

    def test_a_repo_lead_can_view(self, client, act_as, db):
        _seed_activity(db, lead=20)
        act_as(**LEAD)
        assert client.get("/activity/10").status_code == 200

    def test_a_lead_of_an_unrelated_repo_sees_nothing(self, client, act_as, db):
        _seed_activity(db)
        _seed_repo(db, gh_id=9, name="led-by-20", lead=20, dept=None)
        act_as(**LEAD)
        r = client.get("/activity/10")
        assert r.status_code == 200
        _assert_empty(r.json())

    def test_a_lead_only_sees_activity_from_the_repos_they_lead(self, client, act_as, db):
        _seed_activity(db)
        beta = _seed_repo(db, gh_id=2, name="beta", lead=20, dept=None)
        db.add(Commit(repo_id=beta.id, sha="b1", author_user_id=10, message="beta", committed_at=_dt(1)))
        db.commit()
        act_as(**LEAD)
        body = client.get("/activity/10").json()
        assert body["counts"] == {"commits": 1, "pull_requests": 0, "reviews": 0, "issues": 0}
        assert [c["sha"] for c in body["recent_commits"]] == ["b1"]

    def test_repo_filter_inside_the_callers_scope_is_allowed(self, client, act_as, db):
        _seed_activity(db)
        beta = _seed_repo(db, gh_id=2, name="beta", lead=20, dept=None)
        db.add(Commit(repo_id=beta.id, sha="b1", author_user_id=10, message="beta", committed_at=_dt(1)))
        db.commit()
        act_as(**LEAD)
        r = client.get(f"/activity/10?repo_id={beta.id}")
        assert r.status_code == 200 and r.json()["counts"]["commits"] == 1

    def test_repo_filter_outside_the_callers_scope_returns_nothing(self, client, act_as, db):
        alpha = _seed_activity(db)
        _seed_repo(db, gh_id=2, name="beta", lead=20, dept=None)
        db.add(Commit(repo_id=_seed_repo(db, gh_id=3, name="gamma", lead=20, dept=None).id, sha="g1",
                      author_user_id=10, message="g", committed_at=_dt(1)))
        db.commit()
        act_as(**LEAD)
        outside = client.get(f"/activity/10?repo_id={alpha}")
        assert outside.status_code == 200
        _assert_empty(outside.json())
        assert outside.json() == client.get("/activity/10?repo_id=9999").json()

    def test_viewing_others_requires_a_token(self, client, db):
        _seed_activity(db)
        assert client.get("/activity/10").status_code == 401
