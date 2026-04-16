"""
Unit tests for data/database.py — TradeDatabase.

Focuses on the update_position_status() method added in Session 6 and the
general read helpers, all exercised against a real in-memory SQLite connection.
"""

import pytest
from data.database import TradeDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    """Fresh TradeDatabase backed by a temp file; closed after each test."""
    d = TradeDatabase(str(tmp_path / "test.db"))
    assert d.connect() is True
    yield d
    d.close()


def _insert_position(db: TradeDatabase, position_id: str, status: str = "OPEN"):
    """Insert a minimal positions row directly so tests don't depend on Position dataclass."""
    with db._lock:
        db._conn.execute(
            """
            INSERT INTO positions (
                position_id, market_id, market_slug, status
            ) VALUES (?, ?, ?, ?)
            """,
            (position_id, "mkt-1", "slug-1", status),
        )
        db._conn.commit()


def _get_status(db: TradeDatabase, position_id: str) -> str | None:
    row = db._conn.execute(
        "SELECT status FROM positions WHERE position_id = ?", (position_id,)
    ).fetchone()
    return row["status"] if row else None


# ---------------------------------------------------------------------------
# update_position_status
# ---------------------------------------------------------------------------


class TestUpdatePositionStatus:
    def test_updates_existing_row(self, db):
        _insert_position(db, "p1", "OPEN")
        result = db.update_position_status("p1", "FAILED")
        assert result is True
        assert _get_status(db, "p1") == "FAILED"

    def test_returns_true_for_missing_id(self, db):
        # SQLite UPDATE on a non-existent row is a no-op, not an error.
        # The method should still return True (non-fatal by design).
        result = db.update_position_status("no-such-id", "FAILED")
        assert result is True

    def test_missing_id_leaves_db_unchanged(self, db):
        _insert_position(db, "p2", "OPEN")
        db.update_position_status("other-id", "FAILED")
        assert _get_status(db, "p2") == "OPEN"

    def test_returns_false_when_no_connection(self):
        db = TradeDatabase(":memory:")
        # Never called connect() — _conn is None
        assert db.update_position_status("p1", "FAILED") is False

    def test_multiple_statuses(self, db):
        for pid in ("a", "b", "c"):
            _insert_position(db, pid, "OPEN")
        db.update_position_status("b", "FAILED")
        assert _get_status(db, "a") == "OPEN"
        assert _get_status(db, "b") == "FAILED"
        assert _get_status(db, "c") == "OPEN"


# ---------------------------------------------------------------------------
# get_positions — regression for status filtering used by _restore_open_positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    def test_returns_only_open_by_default(self, db):
        _insert_position(db, "open1", "OPEN")
        _insert_position(db, "failed1", "FAILED")
        rows = db.get_positions(status="OPEN")
        ids = {r["position_id"] for r in rows}
        assert "open1" in ids
        assert "failed1" not in ids

    def test_returns_empty_when_no_connection(self):
        db = TradeDatabase(":memory:")
        assert db.get_positions() == []

    def test_failed_positions_excluded_from_open_query(self, db):
        for i in range(3):
            _insert_position(db, f"p{i}", "OPEN")
        db.update_position_status("p1", "FAILED")
        rows = db.get_positions(status="OPEN")
        ids = {r["position_id"] for r in rows}
        assert "p1" not in ids
        assert len(ids) == 2
