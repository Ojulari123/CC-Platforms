from datetime import datetime, timezone
from app.models import LLM_KIND_JOURNAL_ROLLUP, LLM_KIND_REPORT, LlmUsage

ADMIN = dict(user_id=99, is_platform_admin=True)
ENGINEER = dict(user_id=10, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])

def _seed_usage(db):
    db.add(LlmUsage(report_id=1, kind=LLM_KIND_REPORT, user_id=10, tokens=100))
    db.add(LlmUsage(report_id=2, kind=LLM_KIND_REPORT, user_id=10, tokens=250))
    db.commit()

class TestLlmUsage:
    def test_admin_sees_rollup(self, client, act_as, db):
        _seed_usage(db)
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 200, r.text
        assert r.json() == {
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
        assert r.json() == {"total_tokens": 0, "generation_count": 0, "by_kind": []}

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
            "total_tokens": 40,
            "generation_count": 1,
            "by_kind": [{"kind": "journal_rollup", "total_tokens": 40, "generation_count": 1}],
        }

    def test_non_admin_is_403(self, client, act_as, db):
        _seed_usage(db)
        act_as(**ENGINEER)
        assert client.get("/admin/llm-usage").status_code == 403

    def test_requires_a_token(self, client, db):
        assert client.get("/admin/llm-usage").status_code == 401
