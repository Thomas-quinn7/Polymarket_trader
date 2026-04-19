"""
Unit tests for BacktestDB (backtesting/db.py).

Covers:
- upsert_market / get_markets_in_range round-trip
- upsert_market is idempotent (INSERT OR IGNORE)
- get_markets_in_range filters: category, max_duration_s, min_volume
- count_markets_in_range
- insert_price_history / get_price_history round-trip
- has_price_history returns True for >= 3 ticks, False for < 3 and unknown
- create_run / get_run round-trip
- update_run_status sets status and finished_at
- save_run_results flattens scalar metrics and completes the run
- insert_run_trades / get_run_trades round-trip
- get_runs returns rows ordered newest-first and filters by strategy_name
"""

import pytest
from backtesting.db import BacktestDB

# ── Helpers ────────────────────────────────────────────────────────────────────


def _db() -> BacktestDB:
    return BacktestDB(":memory:")


def _seed_market(db: BacktestDB, condition_id: str = "cid-1"):
    """Insert a minimal market row so FK constraints on bt_price_history are satisfied."""
    db.upsert_market(_market(condition_id))


def _market(condition_id: str = "cid-1", **overrides) -> dict:
    base = {
        "condition_id": condition_id,
        "slug": "test-market",
        "question": "Will X happen?",
        "category": "crypto",
        "volume": 1000.0,
        "end_time": "2025-03-01T12:00:00+00:00",
        "created_at": "2025-01-01T00:00:00+00:00",
        "resolution": 1.0,
        "token_id_yes": "tok_yes",
        "token_id_no": "tok_no",
        "duration_seconds": 3600,
    }
    base.update(overrides)
    return base


def _run_id() -> str:
    return "run-abc123"


# ── upsert_market / get_markets_in_range ──────────────────────────────────────


class TestUpsertAndGetMarkets:
    def test_inserted_market_is_returned(self):
        db = _db()
        db.upsert_market(_market("cid-1"))
        rows = db.get_markets_in_range("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00")
        assert len(rows) == 1
        assert rows[0]["condition_id"] == "cid-1"

    def test_upsert_is_idempotent(self):
        db = _db()
        db.upsert_market(_market("cid-1"))
        db.upsert_market(_market("cid-1"))  # second call — should not raise or duplicate
        rows = db.get_markets_in_range("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00")
        assert len(rows) == 1

    def test_filters_by_category(self):
        db = _db()
        db.upsert_market(_market("cid-1", category="crypto"))
        db.upsert_market(_market("cid-2", category="fed"))
        rows = db.get_markets_in_range(
            "2025-01-01T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
            category="crypto",
        )
        assert len(rows) == 1
        assert rows[0]["condition_id"] == "cid-1"

    def test_filters_by_max_duration(self):
        db = _db()
        db.upsert_market(_market("cid-short", duration_seconds=1800))
        db.upsert_market(_market("cid-long", duration_seconds=86400))
        rows = db.get_markets_in_range(
            "2025-01-01T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
            max_duration_s=3600,
        )
        cids = [r["condition_id"] for r in rows]
        assert "cid-short" in cids
        assert "cid-long" not in cids

    def test_filters_by_min_volume(self):
        db = _db()
        db.upsert_market(_market("cid-low", volume=100.0))
        db.upsert_market(_market("cid-high", volume=2000.0))
        rows = db.get_markets_in_range(
            "2025-01-01T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
            min_volume=500.0,
        )
        cids = [r["condition_id"] for r in rows]
        assert "cid-high" in cids
        assert "cid-low" not in cids

    def test_outside_date_range_excluded(self):
        db = _db()
        db.upsert_market(_market("cid-1", end_time="2024-01-01T12:00:00+00:00"))
        rows = db.get_markets_in_range("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00")
        assert rows == []

    def test_results_ordered_by_end_time_asc(self):
        db = _db()
        db.upsert_market(_market("cid-later", end_time="2025-06-01T12:00:00+00:00"))
        db.upsert_market(_market("cid-earlier", end_time="2025-02-01T12:00:00+00:00"))
        rows = db.get_markets_in_range("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00")
        assert rows[0]["condition_id"] == "cid-earlier"
        assert rows[1]["condition_id"] == "cid-later"


# ── count_markets_in_range ────────────────────────────────────────────────────


class TestCountMarkets:
    def test_count_returns_zero_when_empty(self):
        db = _db()
        assert (
            db.count_markets_in_range("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00") == 0
        )

    def test_count_matches_inserted(self):
        db = _db()
        db.upsert_market(_market("cid-1"))
        db.upsert_market(_market("cid-2"))
        assert (
            db.count_markets_in_range("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00") == 2
        )

    def test_count_filters_by_category(self):
        db = _db()
        db.upsert_market(_market("cid-1", category="crypto"))
        db.upsert_market(_market("cid-2", category="fed"))
        assert (
            db.count_markets_in_range(
                "2025-01-01T00:00:00+00:00",
                "2025-12-31T23:59:59+00:00",
                category="fed",
            )
            == 1
        )


# ── Price history ─────────────────────────────────────────────────────────────


class TestPriceHistory:
    def test_roundtrip(self):
        db = _db()
        _seed_market(db, "cid-1")
        ticks = [(1_000_000 + i * 300, 0.80 + i * 0.01) for i in range(5)]
        db.insert_price_history("cid-1", ticks)
        result = db.get_price_history("cid-1")
        assert result == ticks

    def test_insert_is_idempotent(self):
        db = _db()
        _seed_market(db, "cid-1")
        ticks = [(1_000_000, 0.85), (1_000_300, 0.87), (1_000_600, 0.89)]
        db.insert_price_history("cid-1", ticks)
        db.insert_price_history("cid-1", ticks)  # second call — no error, no duplicates
        assert len(db.get_price_history("cid-1")) == 3

    def test_results_ordered_by_ts(self):
        db = _db()
        _seed_market(db, "cid-1")
        db.insert_price_history("cid-1", [(300, 0.9), (100, 0.7), (200, 0.8)])
        result = db.get_price_history("cid-1")
        assert [ts for ts, _ in result] == [100, 200, 300]

    def test_has_price_history_true_after_3_ticks(self):
        db = _db()
        _seed_market(db, "cid-1")
        db.insert_price_history("cid-1", [(1, 0.8), (2, 0.85), (3, 0.9)])
        assert db.has_price_history("cid-1") is True

    def test_has_price_history_false_for_fewer_than_3(self):
        db = _db()
        _seed_market(db, "cid-1")
        db.insert_price_history("cid-1", [(1, 0.8), (2, 0.85)])
        assert db.has_price_history("cid-1") is False

    def test_has_price_history_false_for_unknown(self):
        db = _db()
        assert db.has_price_history("unknown-cid") is False


# ── Run lifecycle ─────────────────────────────────────────────────────────────


class TestRunLifecycle:
    def test_create_and_get_run(self):
        db = _db()
        db.create_run("run-1", "my_strategy", '{"key": "val"}')
        row = db.get_run("run-1")
        assert row is not None
        assert row["run_id"] == "run-1"
        assert row["strategy_name"] == "my_strategy"
        assert row["status"] == "pending"

    def test_update_status_to_running(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.update_run_status("run-1", "running")
        assert db.get_run("run-1")["status"] == "running"

    def test_update_status_to_complete_sets_finished_at(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.update_run_status("run-1", "complete")
        row = db.get_run("run-1")
        assert row["status"] == "complete"
        assert row["finished_at"] is not None

    def test_update_status_to_error_stores_message(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.update_run_status("run-1", "error", error_message="boom")
        row = db.get_run("run-1")
        assert row["status"] == "error"
        assert row["error_message"] == "boom"

    def test_get_run_returns_none_for_unknown(self):
        db = _db()
        assert db.get_run("does-not-exist") is None


# ── save_run_results ──────────────────────────────────────────────────────────


class TestSaveRunResults:
    def _metrics(self) -> dict:
        return {
            "total_net_pnl": 50.0,
            "total_return_pct": 5.0,
            "annualized_return": 20.0,
            "max_drawdown": 2.5,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.5,
            "calmar_ratio": 8.0,
            "win_rate": 0.6,
            "profit_factor": 2.0,
            "avg_hold_seconds": 600.0,
            "fee_drag_pct": 10.0,
            "consec_wins_max": 3,
            "consec_losses_max": 2,
        }

    def test_scalars_persisted(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.save_run_results("run-1", 10, 5, self._metrics(), [(0, 1000.0)])
        row = db.get_run("run-1")
        assert row["market_count"] == 10
        assert row["trade_count"] == 5
        assert row["total_net_pnl"] == pytest.approx(50.0)
        assert row["win_rate"] == pytest.approx(0.6)

    def test_status_set_to_complete(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.save_run_results("run-1", 0, 0, {}, [])
        assert db.get_run("run-1")["status"] == "complete"


# ── insert_run_trades / get_run_trades ────────────────────────────────────────


class TestRunTrades:
    def _trade(self, condition_id: str = "cid-1") -> dict:
        return {
            "strategy_name": "my_strat",
            "condition_id": condition_id,
            "question": "Will X?",
            "entry_ts": 1_000_000,
            "exit_ts": 1_003_600,
            "entry_price": 0.80,
            "exit_price": 1.0,
            "shares": 125.0,
            "allocated_capital": 100.0,
            "side": "YES",
            "gross_pnl": 25.0,
            "net_pnl": 22.0,
            "entry_fee": 2.0,
            "exit_fee": 1.0,
            "outcome": "WIN",
            "exit_reason": "settlement",
        }

    def test_inserted_trades_are_returned(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.insert_run_trades("run-1", [self._trade("cid-1"), self._trade("cid-2")])
        rows = db.get_run_trades("run-1")
        assert len(rows) == 2

    def test_trade_fields_preserved(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.insert_run_trades("run-1", [self._trade()])
        row = db.get_run_trades("run-1")[0]
        assert row["condition_id"] == "cid-1"
        assert row["outcome"] == "WIN"
        assert row["net_pnl"] == pytest.approx(22.0)

    def test_empty_trade_list_is_safe(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.insert_run_trades("run-1", [])
        assert db.get_run_trades("run-1") == []

    def test_pagination_offset_and_limit(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        trades = [self._trade(f"cid-{i}") for i in range(5)]
        db.insert_run_trades("run-1", trades)
        page = db.get_run_trades("run-1", offset=2, limit=2)
        assert len(page) == 2


# ── get_runs ──────────────────────────────────────────────────────────────────


class TestGetRuns:
    def test_returns_all_runs(self):
        db = _db()
        db.create_run("run-1", "s", "{}")
        db.create_run("run-2", "s", "{}")
        assert len(db.get_runs()) == 2

    def test_ordered_newest_first(self):
        import time

        db = _db()
        db.create_run("run-1", "s", "{}")
        time.sleep(0.01)
        db.create_run("run-2", "s", "{}")
        rows = db.get_runs()
        assert rows[0]["run_id"] == "run-2"

    def test_filters_by_strategy_name(self):
        db = _db()
        db.create_run("run-1", "strat_a", "{}")
        db.create_run("run-2", "strat_b", "{}")
        rows = db.get_runs(strategy_name="strat_a")
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run-1"

    def test_limit_respected(self):
        db = _db()
        for i in range(5):
            db.create_run(f"run-{i}", "s", "{}")
        assert len(db.get_runs(limit=3)) == 3
