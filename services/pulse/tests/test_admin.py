from datetime import datetime, timezone
from app import crypto
from app.models import LLM_KIND_JOURNAL_ROLLUP, LLM_KIND_REPORT, PROVIDER_OPENAI, SCOPE_DEPARTMENT, SCOPE_USER, ApiCredential, LlmUsage

DEPT = 1
ADMIN = dict(user_id=99, is_platform_admin=True)
ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": DEPT, "team_id": None, "role": "admin"}])

def _seed_usage(db):
    db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, tokens=100))
    db.add(LlmUsage(report_id=2, kind=LLM_KIND_REPORT, user_id=10, tokens=250))
    db.commit()

def _seed_key(db, *, scope, owner=None, dept=None, key="sk-own-1111", created_by=99):
    db.add(ApiCredential(
        scope=scope, owner_user_id=owner, dept_id=dept, provider=PROVIDER_OPENAI,
        key_encrypted=crypto.encrypt(key), last_four=key[-4:], model=None,
        bypass_token_cap=False, created_by_user_id=owner or created_by,
    ))
    db.commit()

class TestLlmUsage:
    def test_admin_sees_rollup(self, client, act_as, db):
        _seed_usage(db)
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "scope": "platform",
            "total_tokens": 350,
            "generation_count": 2,
            "by_kind": [{"kind": "report", "total_tokens": 350, "generation_count": 2}],
        }

    def test_spend_is_broken_down_per_surface(self, client, act_as, db):
        _seed_usage(db)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_JOURNAL_ROLLUP, user_id=11, tokens=400))
        db.commit()
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "scope": "platform",
            "total_tokens": 750,
            "generation_count": 3,
            "by_kind": [
                {"kind": "journal_rollup", "total_tokens": 400, "generation_count": 1},
                {"kind": "report", "total_tokens": 350, "generation_count": 2},
            ],
        }

    def test_a_row_written_without_a_kind_counts_as_a_report(self, client, act_as, db):
        """kind defaults to "report" at both the ORM and the column level, which is what
        every row in the ledger was before journal rollups existed."""
        db.add(LlmUsage(report_id=7, user_id=10, tokens=60))
        db.commit()
        act_as(**ADMIN)
        assert client.get("/admin/llm-usage").json()["by_kind"] == [
            {"kind": "report", "total_tokens": 60, "generation_count": 1}
        ]

    def test_empty_ledger_is_zeroes(self, client, act_as, db):
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 200, r.text
        assert r.json() == {"scope": "platform", "total_tokens": 0, "generation_count": 0, "by_kind": []}

    def test_since_excludes_older_spend_from_the_totals_and_the_breakdown(self, client, act_as, db):
        old = LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, tokens=100)
        old.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.add(old)
        recent = LlmUsage(report_id=None, kind=LLM_KIND_JOURNAL_ROLLUP, user_id=10, tokens=40)
        recent.created_at = datetime(2026, 8, 20, tzinfo=timezone.utc)
        db.add(recent)
        db.commit()
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage", params={"since": "2026-08-01"})
        assert r.status_code == 200, r.text
        assert r.json() == {
            "scope": "platform",
            "total_tokens": 40,
            "generation_count": 1,
            "by_kind": [{"kind": "journal_rollup", "total_tokens": 40, "generation_count": 1}],
        }

    def test_someone_on_the_platform_key_is_403(self, client, act_as, db):
        """The rule is may_see_figures: the platform's spend is not theirs to read, and
        that is the whole organisation's spend on this endpoint."""
        _seed_usage(db)
        act_as(**ENGINEER)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 403
        assert "whoever is paying" in r.json()["detail"]

    def test_a_dept_admin_on_the_platform_key_is_403_too(self, client, act_as, db):
        """Being an admin of a department is not the same as funding one."""
        _seed_usage(db)
        act_as(**DEPT_ADMIN)
        assert client.get("/admin/llm-usage").status_code == 403

    def test_requires_a_token(self, client, db):
        assert client.get("/admin/llm-usage").status_code == 401

class TestScoping:
    """One ledger, three answers. Before this it was one answer — the organisation's —
    behind a platform-admin-only gate, so the people funding calls could see none of
    their own figures and the one person funding none of them saw all of them."""

    def test_a_user_on_their_own_key_sees_only_their_own_spend(self, client, act_as, db):
        _seed_usage(db)
        db.add(LlmUsage(report_id=3, kind=LLM_KIND_REPORT, user_id=11, tokens=999))
        db.commit()
        _seed_key(db, scope=SCOPE_USER, owner=10)
        act_as(**ENGINEER)
        body = client.get("/admin/llm-usage").json()
        assert body["scope"] == "self"
        assert body["total_tokens"] == 350
        assert body["generation_count"] == 2

    def test_a_dept_admin_sees_what_their_departments_key_paid_for(self, client, act_as, db):
        db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, dept_id=DEPT, tokens=100))
        db.add(LlmUsage(report_id=2, kind=LLM_KIND_REPORT, user_id=11, dept_id=2, tokens=500))
        db.add(LlmUsage(report_id=3, kind=LLM_KIND_REPORT, user_id=12, dept_id=None, tokens=70))
        db.commit()
        _seed_key(db, scope=SCOPE_DEPARTMENT, dept=DEPT, key="sk-dept-2222")
        act_as(**DEPT_ADMIN)
        body = client.get("/admin/llm-usage").json()
        assert body["scope"] == "department"
        assert body["total_tokens"] == 100
        assert body["generation_count"] == 1

    def test_a_dept_admin_still_sees_their_own_spend(self, client, act_as, db):
        db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=30, dept_id=None, tokens=25))
        db.commit()
        _seed_key(db, scope=SCOPE_DEPARTMENT, dept=DEPT, key="sk-dept-2222")
        act_as(**DEPT_ADMIN)
        assert client.get("/admin/llm-usage").json()["total_tokens"] == 25

    def test_a_member_under_the_department_key_still_sees_only_their_own(self, client, act_as, db):
        """Paying with the department's money is what makes the figures visible; being
        able to read the department's total is what being its admin adds."""
        db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, dept_id=DEPT, tokens=100))
        db.add(LlmUsage(report_id=2, kind=LLM_KIND_REPORT, user_id=11, dept_id=DEPT, tokens=500))
        db.commit()
        _seed_key(db, scope=SCOPE_DEPARTMENT, dept=DEPT, key="sk-dept-2222")
        act_as(**ENGINEER)
        body = client.get("/admin/llm-usage").json()
        assert body["scope"] == "self"
        assert body["total_tokens"] == 100

    def test_a_platform_admin_still_sees_everything(self, client, act_as, db):
        db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, dept_id=DEPT, tokens=100))
        db.add(LlmUsage(report_id=2, kind=LLM_KIND_REPORT, user_id=11, dept_id=2, tokens=500))
        db.commit()
        act_as(**ADMIN)
        body = client.get("/admin/llm-usage").json()
        assert body["scope"] == "platform"
        assert body["total_tokens"] == 600

    def test_a_personal_keys_spend_stays_off_the_departments_bill(self, client, act_as, db):
        """dept_id is stamped from the key that paid, so a member's own key never lands
        on their department admin's figures."""
        db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, dept_id=None, tokens=100))
        db.commit()
        _seed_key(db, scope=SCOPE_DEPARTMENT, dept=DEPT, key="sk-dept-2222")
        act_as(**DEPT_ADMIN)
        assert client.get("/admin/llm-usage").json()["total_tokens"] == 0
