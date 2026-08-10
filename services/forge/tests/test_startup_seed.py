import app.main
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app.models import Dataset

def _sample_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Dataset).where(Dataset.is_sample.is_(True)))

def test_boot_seeds_two_samples(monkeypatch, test_sessionmaker, db, act_as):
    monkeypatch.setattr(app.main, "SessionLocal", test_sessionmaker)
    with TestClient(app.main.app) as boot_client:
        assert _sample_count(db) == 2
        act_as(4242)  # a user who has uploaded nothing
        r = boot_client.get("/datasets")
        assert r.status_code == 200
        assert r.json()["total"] == 2

def test_boot_is_idempotent(monkeypatch, test_sessionmaker, db):
    monkeypatch.setattr(app.main, "SessionLocal", test_sessionmaker)
    with TestClient(app.main.app):
        pass
    with TestClient(app.main.app):  # second boot must not duplicate
        pass
    assert _sample_count(db) == 2
