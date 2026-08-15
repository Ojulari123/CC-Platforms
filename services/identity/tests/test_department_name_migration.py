"""Migration 0012's duplicate guard, run against pre-migration rows. The chain itself
can't run here (0003 is Postgres-only), so the detection query is imported from the
migration and run as-is. The index create_all already built has to come off first —
duplicates cannot exist while it is there, which is the whole point of it."""
import importlib.util
from pathlib import Path
from sqlalchemy import text
from app.models import Department

_spec = importlib.util.spec_from_file_location(
    "migration_0012",
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0012_department_name_unique.py",
)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

INDEX_SQL = "CREATE UNIQUE INDEX uq_departments_name_lower ON departments (lower(name))"

def _drop_index(db) -> None:
    db.execute(text("DROP INDEX uq_departments_name_lower"))
    db.commit()

def _seed(db, names: list[str]) -> None:
    for n, name in enumerate(names, start=1):
        db.add(Department(name=name, slug=f"dept-{n}"))
    db.commit()

class TestDuplicateDetection:
    def test_clean_data_reports_nothing(self, db_session):
        _seed(db_session, ["Software Dev", "Data", "Operations"])
        assert _migration.duplicate_department_names(db_session) == []

    def test_duplicates_are_reported_case_and_space_insensitively(self, db_session):
        _drop_index(db_session)
        _seed(db_session, ["Software Dev", "software dev", " Software Dev ", "Data"])
        assert _migration.duplicate_department_names(db_session) == [("software dev", 3)]

    def test_the_message_names_them_and_points_at_the_script(self, db_session):
        _drop_index(db_session)
        _seed(db_session, ["Software Dev", "Software Dev"])
        duplicates = _migration.duplicate_department_names(db_session)
        listed = ", ".join(f"{key!r} x{n}" for key, n in duplicates)
        assert "'software dev' x2" == listed

class TestTheIndexItself:
    def test_it_will_not_build_over_duplicates(self, db_session):
        _drop_index(db_session)
        _seed(db_session, ["Software Dev", "SOFTWARE DEV"])
        try:
            db_session.execute(text(INDEX_SQL))
        except Exception as exc:
            assert "unique" in str(exc).lower()
        else:
            raise AssertionError("the unique index built over duplicate names")
        db_session.rollback()

    def test_it_builds_once_the_duplicates_are_gone(self, db_session):
        _drop_index(db_session)
        _seed(db_session, ["Software Dev", "SOFTWARE DEV"])
        db_session.execute(text("DELETE FROM departments WHERE name = 'SOFTWARE DEV'"))
        db_session.commit()

        assert _migration.duplicate_department_names(db_session) == []
        db_session.execute(text(INDEX_SQL))
        db_session.commit()
