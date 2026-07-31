"""The engineer activity view (slice 5): counts + recent items, filters, and who
may see whose activity."""
from datetime import datetime, timezone

from app.models import Commit, Issue, PullRequest, Repository, Review

ENGINEER = dict(user_id=10, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
ENGINEER_2 = dict(user_id=11, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": 1, "team_id": None, "role": "admin"}])
LEAD = dict(user_id=20, memberships=[{"dept_id": 1, "team_id": None, "role": "manager"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)


def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


def _seed_repo(db, gh_id=1, name="alpha", lead=None):
    repo = Repository(github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name, lead_user_id=lead)
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def _seed_activity(db, user_id=10):
    """For user 10 in repo alpha: 2 commits (7-20, 7-10), 1 PR, 1 review, 1 issue."""
    repo = _seed_repo(db)
    db.add(Commit(repo_id=repo.id, sha="a1", author_user_id=user_id, message="newer", committed_at=_dt(2026, 7, 20)))
    db.add(Commit(repo_id=repo.id, sha="a2", author_user_id=user_id, message="older", committed_at=_dt(2026, 7, 10)))
    pr = PullRequest(repo_id=repo.id, github_pr_id=1, number=7, title="pr", state="open", merged=False,
                     author_user_id=user_id, gh_created_at=_dt(2026, 7, 19))
    db.add(pr)
    db.commit()
    db.refresh(pr)
    db.add(Review(pull_request_id=pr.id, github_review_id=1, reviewer_user_id=user_id, state="approved", submitted_at=_dt(2026, 7, 19)))
    db.add(Issue(repo_id=repo.id, github_issue_id=1, number=3, title="iss", state="open", author_user_id=user_id, gh_created_at=_dt(2026, 7, 18)))
    db.commit()
    return repo.id


class TestOwnActivity:
    def test_counts_and_recent(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER)
        body = client.get("/activity/me").json()
        assert body["counts"] == {"commits": 2, "pull_requests": 1, "reviews": 1, "issues": 1}
        assert body["recent_commits"][0]["sha"] == "a1"  # most recent first

    def test_view_own_by_id(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER)
        assert client.get("/activity/10").status_code == 200

    def test_since_narrows(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER)
        body = client.get("/activity/me?since=2026-07-15").json()
        assert body["counts"]["commits"] == 1  # only the 7-20 commit

    def test_repo_filter(self, client, act_as, db):
        repo1 = _seed_activity(db)
        repo2 = _seed_repo(db, gh_id=2, name="beta")
        db.add(Commit(repo_id=repo2.id, sha="b1", author_user_id=10, message="beta", committed_at=_dt(2026, 7, 21)))
        db.commit()
        act_as(**ENGINEER)
        assert client.get(f"/activity/me?repo_id={repo1}").json()["counts"]["commits"] == 2
        assert client.get(f"/activity/me?repo_id={repo2.id}").json()["counts"]["commits"] == 1

    def test_requires_a_token(self, client):
        assert client.get("/activity/me").status_code == 401


class TestViewingOthers:
    def test_other_engineer_forbidden(self, client, act_as, db):
        _seed_activity(db)
        act_as(**ENGINEER_2)
        assert client.get("/activity/10").status_code == 403

    def test_platform_admin_can_view(self, client, act_as, db):
        _seed_activity(db)
        act_as(**PLATFORM)
        assert client.get("/activity/10").status_code == 200

    def test_department_admin_can_view(self, client, act_as, db):
        _seed_activity(db)
        act_as(**DEPT_ADMIN)
        assert client.get("/activity/10").status_code == 200

    def test_a_repo_lead_can_view(self, client, act_as, db):
        _seed_activity(db)
        _seed_repo(db, gh_id=9, name="led-by-20", lead=20)  # user 20 leads a repo
        act_as(**LEAD)
        assert client.get("/activity/10").status_code == 200

    def test_viewing_others_requires_a_token(self, client, db):
        _seed_activity(db)
        assert client.get("/activity/10").status_code == 401
