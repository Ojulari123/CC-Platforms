from app.models import LlmUsage

ADMIN = dict(user_id=99, is_platform_admin=True)
ENGINEER = dict(user_id=10, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])

def _seed_usage(db):
    db.add(LlmUsage(report_id=1, user_id=10, tokens=100))
    db.add(LlmUsage(report_id=2, user_id=10, tokens=250))
    db.commit()

class TestLlmUsage:
    def test_admin_sees_rollup(self, client, act_as, db):
        _seed_usage(db)
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 200, r.text
        assert r.json() == {"total_tokens": 350, "generation_count": 2}

    def test_empty_ledger_is_zeroes(self, client, act_as, db):
        act_as(**ADMIN)
        r = client.get("/admin/llm-usage")
        assert r.status_code == 200, r.text
        assert r.json() == {"total_tokens": 0, "generation_count": 0}

    def test_non_admin_is_403(self, client, act_as, db):
        _seed_usage(db)
        act_as(**ENGINEER)
        assert client.get("/admin/llm-usage").status_code == 403

    def test_requires_a_token(self, client, db):
        assert client.get("/admin/llm-usage").status_code == 401
