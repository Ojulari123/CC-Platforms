from sqlalchemy.exc import OperationalError
from app.db import get_db
from app.main import app

def test_root_identifies_the_service(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "pulse", "status": "ok"}

def test_health_checks_the_db(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "reachable"}

def test_health_reports_the_db_as_unreachable_when_the_check_fails(client):
    dsn = "postgresql://pulse:hunter2@db.internal:5432/pulse"

    class _DownSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception(f"could not connect to server: {dsn}"))

    def _down():
        yield _DownSession()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = _down
    try:
        r = client.get("/health")
    finally:
        app.dependency_overrides[get_db] = previous

    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "unreachable"}
    # The endpoint that diagnoses the database must not hand the caller the DSN with it.
    assert dsn not in r.text
    assert "could not connect" not in r.text
