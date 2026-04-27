"""
Unit tests for tools/tick_recorder.py.

Skipped on the public repo (where tools/ is gitignored). On the private repo
the full module is present and the tests run normally.
"""

import os
import queue
import tempfile
import threading
from unittest.mock import MagicMock

import pytest

tick_recorder = pytest.importorskip("tools.tick_recorder")

from tools.tick_recorder import (  # noqa: E402
    MarketPoller,
    MarketWatch,
    MinimumsDB,
    MinimumRow,
    PollerConfig,
    QualityThresholds,
    _aggregated_depth,
    _ask1,
    _bid1,
    _compute_quality,
    _label_duration_seconds,
    _mid,
)
from data.market_schema import _orient_yes_no  # noqa: E402

# ── Label parsing ─────────────────────────────────────────────────────────────


class TestLabelDurationSeconds:
    def test_5min_market(self):
        assert _label_duration_seconds("Bitcoin Up or Down - April 23, 10:30AM-10:35AM ET") == 300

    def test_15min_market(self):
        assert _label_duration_seconds("Ethereum Up or Down - April 23, 10:00AM-10:15AM ET") == 900

    def test_midnight_crossing(self):
        # 11:55PM-12:05AM next day = 10 minutes = 600s
        assert _label_duration_seconds("Bitcoin Up or Down - April 23, 11:55PM-12:05AM ET") == 600

    def test_noon_pm_handled_correctly(self):
        # 12:00PM should be treated as 12:00, not 24:00
        assert _label_duration_seconds("Bitcoin Up or Down - April 23, 12:00PM-12:05PM ET") == 300

    def test_midnight_am_handled_correctly(self):
        # 12:00AM should be treated as 00:00
        assert _label_duration_seconds("Bitcoin Up or Down - April 23, 12:00AM-12:05AM ET") == 300

    def test_unparseable_returns_none(self):
        assert _label_duration_seconds("Not a recognised label format") is None


# ── Orderbook helpers ─────────────────────────────────────────────────────────


class TestOrderbookHelpers:
    def test_mid_uses_book_mid_price_when_positive(self):
        book = {"mid_price": 0.42, "bids": [], "asks": []}
        assert _mid(book) == 0.42

    def test_mid_falls_through_when_book_mid_is_zero(self):
        book = {
            "mid_price": 0.0,
            "bids": [{"price": 0.40, "size": 1}],
            "asks": [{"price": 0.42, "size": 1}],
        }
        assert _mid(book) == pytest.approx(0.41)

    def test_mid_handles_zero_bid_correctly_no_falsy_zero_bug(self):
        # Regression test for B2: a $0.00 bid must not be silently discarded
        # by Python's falsy-zero rule. Old code returned ask only here.
        book = {
            "mid_price": None,
            "bids": [{"price": 0.0, "size": 1}],
            "asks": [{"price": 0.04, "size": 1}],
        }
        assert _mid(book) == pytest.approx(0.02)

    def test_mid_returns_only_side_when_one_side_empty(self):
        book = {"mid_price": None, "bids": [], "asks": [{"price": 0.5, "size": 1}]}
        assert _mid(book) == 0.5

    def test_mid_returns_none_for_empty_book(self):
        book = {"mid_price": None, "bids": [], "asks": []}
        assert _mid(book) is None

    def test_aggregated_depth_sums_all_levels(self):
        # Q3 fix: depth is across all visible levels, not just top of book.
        book = {
            "bids": [{"price": 0.40, "size": 50}, {"price": 0.39, "size": 30}],
            "asks": [{"price": 0.42, "size": 40}, {"price": 0.43, "size": 20}],
        }
        assert _aggregated_depth(book) == 140.0

    def test_aggregated_depth_returns_none_when_empty(self):
        assert _aggregated_depth({"bids": [], "asks": []}) is None

    def test_bid1_ask1_basic(self):
        book = {"bids": [{"price": 0.40, "size": 1}], "asks": [{"price": 0.42, "size": 1}]}
        assert _bid1(book) == 0.40
        assert _ask1(book) == 0.42


# ── Quality thresholds ────────────────────────────────────────────────────────


class TestComputeQuality:
    def _row(self, **overrides):
        base = {
            "first_seen_ms": 1_000_000,
            "last_yes_poll_ms": 1_300_000,  # 300s observation
            "poll_count": 100,
            "no_poll_success_count": 100,
            "no_token_id": "no",
            "min_yes_mid": 0.40,
            "min_yes_bid1": 0.39,
            "min_yes_ask1": 0.41,
            "min_no_mid": 0.55,
            "min_no_bid1": 0.54,
            "min_no_ask1": 0.56,
            "min_yes_depth": 500,
            "min_no_depth": 500,
        }
        base.update(overrides)
        return base

    def test_clean_row_has_no_flags(self):
        q = _compute_quality(self._row())
        assert q["quality_flags"] == ""

    def test_short_window_by_poll_count(self):
        q = _compute_quality(self._row(poll_count=2))
        assert "short_window" in q["quality_flags"]

    def test_short_window_by_observation_seconds(self):
        q = _compute_quality(
            self._row(first_seen_ms=1_000_000, last_yes_poll_ms=1_010_000, poll_count=20)
        )
        assert "short_window" in q["quality_flags"]

    def test_thin_yes_book_flag(self):
        q = _compute_quality(self._row(min_yes_depth=10))
        assert "thin_yes_book" in q["quality_flags"]

    def test_wide_yes_spread_flag(self):
        q = _compute_quality(self._row(min_yes_bid1=0.10, min_yes_ask1=0.30))
        assert "wide_yes_spread" in q["quality_flags"]

    def test_crossed_yes_book_flag(self):
        q = _compute_quality(self._row(min_yes_bid1=0.50, min_yes_ask1=0.40))
        assert "crossed_yes_book" in q["quality_flags"]

    def test_stale_no_side_when_zero_no_polls(self):
        q = _compute_quality(self._row(no_poll_success_count=0))
        assert "stale_no_side" in q["quality_flags"]

    def test_stale_no_side_below_coverage_floor(self):
        q = _compute_quality(self._row(poll_count=100, no_poll_success_count=10))
        assert "stale_no_side" in q["quality_flags"]

    def test_thresholds_are_configurable(self):
        # Tighter spread threshold turns a previously-clean spread into a flag
        tight = QualityThresholds(wide_spread=0.001)
        q = _compute_quality(self._row(min_yes_bid1=0.39, min_yes_ask1=0.41), tight)
        assert "wide_yes_spread" in q["quality_flags"]

    def test_observation_seconds_reported(self):
        q = _compute_quality(self._row(first_seen_ms=1_000_000, last_yes_poll_ms=1_300_000))
        assert q["observation_seconds"] == 300.0


# ── DB layer ──────────────────────────────────────────────────────────────────


class TestMinimumsDB:
    @pytest.fixture
    def db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            d = MinimumsDB(path)
            assert d.connect()
            yield d
            d.close()

    def _row(self, market_id="m1", min_yes_mid=0.40, min_no_mid=0.55, ts_ms=1_000_000):
        return MinimumRow(
            market_id=market_id,
            category="crypto",
            label="Bitcoin Up or Down - April 23, 10:30AM-10:35AM ET",
            yes_token_id=f"{market_id}_yes",
            no_token_id=f"{market_id}_no",
            min_yes_mid=min_yes_mid,
            min_yes_bid1=min_yes_mid - 0.01,
            min_yes_ask1=min_yes_mid + 0.01,
            min_no_mid=min_no_mid,
            min_no_bid1=min_no_mid - 0.01,
            min_no_ask1=min_no_mid + 0.01,
            min_yes_at_ms=ts_ms,
            min_no_at_ms=ts_ms,
            first_seen_ms=ts_ms,
            min_yes_depth=500,
            min_no_depth=500,
        )

    def test_upsert_then_read(self, db):
        assert db.upsert_minimum(self._row())
        rows = db.get_all_minimums()
        assert len(rows) == 1
        assert rows[0]["min_yes_mid"] == 0.40

    def test_upsert_keeps_lower_min(self, db):
        db.upsert_minimum(self._row(min_yes_mid=0.40))
        db.upsert_minimum(self._row(min_yes_mid=0.50))  # higher → ignored
        assert db.get_existing_floors("m1") == (0.40, 0.55)

    def test_upsert_replaces_when_lower(self, db):
        db.upsert_minimum(self._row(min_yes_mid=0.40))
        db.upsert_minimum(self._row(min_yes_mid=0.30))
        assert db.get_existing_floors("m1") == (0.30, 0.55)

    def test_get_existing_floors_unknown_market(self, db):
        assert db.get_existing_floors("never-inserted") == (None, None)

    def test_mark_resolved(self, db):
        db.upsert_minimum(self._row())
        assert db.mark_resolved("m1", 2_000_000)
        rows = db.get_all_minimums()
        assert rows[0]["resolved_at_ms"] == 2_000_000

    # Bug 4 regression: mark_resolved must not overwrite an existing timestamp.
    def test_mark_resolved_does_not_overwrite_existing(self, db):
        db.upsert_minimum(self._row())
        db.mark_resolved("m1", 2_000_000)
        db.mark_resolved("m1", 9_999_999)  # second call (e.g. stop-event exit) ignored
        rows = db.get_all_minimums()
        assert rows[0]["resolved_at_ms"] == 2_000_000

    # Bug 2 regression: poll_count must accumulate across sessions, not overwrite.
    def test_poll_stats_accumulate_across_sessions(self, db):
        db.upsert_minimum(self._row())
        db.update_poll_stats("m1", 10, 8, 1_100_000, 1_050_000)
        db.update_poll_stats("m1", 5, 4, 1_200_000, 1_180_000)
        rows = db.get_all_minimums()
        assert rows[0]["poll_count"] == 15
        assert rows[0]["no_poll_success_count"] == 12
        # last_yes_poll_ms and last_no_poll_ms should be the MAX of the two calls
        assert rows[0]["last_yes_poll_ms"] == 1_200_000
        assert rows[0]["last_no_poll_ms"] == 1_180_000

    def test_poll_stats_timestamp_keeps_max(self, db):
        db.upsert_minimum(self._row())
        db.update_poll_stats("m1", 5, 5, 1_200_000, 1_200_000)
        # Later call with lower timestamps (e.g. a previous session's flush arriving
        # out of order) must not clobber the higher stored timestamps.
        db.update_poll_stats("m1", 3, 3, 1_100_000, 1_100_000)
        rows = db.get_all_minimums()
        assert rows[0]["last_yes_poll_ms"] == 1_200_000
        assert rows[0]["last_no_poll_ms"] == 1_200_000

    def test_migrations_idempotent(self):
        # Running connect twice on the same DB file must not raise.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            d1 = MinimumsDB(path)
            assert d1.connect()
            d1.close()
            d2 = MinimumsDB(path)
            assert d2.connect()
            d2.close()


# ── MarketPoller floor rollback (Bug 1) ───────────────────────────────────────


def _make_poller(db_upsert_ok: bool = True) -> MarketPoller:
    """Return a MarketPoller with a mock DB seeded with yes_floor=0.50."""
    market = MarketWatch(
        label="Bitcoin Up or Down - April 23, 10:30AM-10:35AM ET",
        market_id="m_test",
        yes_token_id="yes_tok",
        no_token_id=None,
        category="crypto",
    )
    mock_db = MagicMock()
    mock_db.get_existing_floors.return_value = (0.50, None)
    mock_db.upsert_minimum.return_value = db_upsert_ok
    poller = MarketPoller(
        market=market,
        client=MagicMock(),
        db=mock_db,
        stop_event=threading.Event(),
        ob_levels=3,
        min_poll_interval_s=0.0,
        done_queue=queue.Queue(),
        api_semaphore=threading.Semaphore(1),
        poller_cfg=PollerConfig(),
    )
    poller._first_seen_ms = 1_000_000
    return poller


class TestMarketPollerFloorRollback:
    def test_floor_advanced_on_successful_write(self):
        p = _make_poller(db_upsert_ok=True)
        p._update_minimums(0.40, 0.39, 0.41, 200.0, None, None, None, None, 1_001_000)
        assert p._yes_floor == pytest.approx(0.40)

    def test_floor_reverted_on_failed_write(self):
        p = _make_poller(db_upsert_ok=False)
        p._update_minimums(0.40, 0.39, 0.41, 200.0, None, None, None, None, 1_001_000)
        # The write failed — floor must revert so the minimum is retried.
        assert p._yes_floor == pytest.approx(0.50)

    def test_no_floor_reverted_independently(self):
        market = MarketWatch(
            label="Bitcoin Up or Down - April 23, 10:30AM-10:35AM ET",
            market_id="m2",
            yes_token_id="yes2",
            no_token_id="no2",
            category="crypto",
        )
        mock_db = MagicMock()
        mock_db.get_existing_floors.return_value = (0.50, 0.55)
        mock_db.upsert_minimum.return_value = False
        poller = MarketPoller(
            market=market,
            client=MagicMock(),
            db=mock_db,
            stop_event=threading.Event(),
            ob_levels=3,
            min_poll_interval_s=0.0,
            done_queue=queue.Queue(),
            api_semaphore=threading.Semaphore(1),
        )
        poller._first_seen_ms = 1_000_000
        # YES stays above floor, NO goes below — only NO floor should revert.
        poller._update_minimums(0.50, 0.49, 0.51, 200.0, 0.40, 0.39, 0.41, 200.0, 1_001_000)
        assert poller._yes_floor == pytest.approx(0.50)  # unchanged (not a new min)
        assert poller._no_floor == pytest.approx(0.55)  # reverted


# ── YES/NO orientation ────────────────────────────────────────────────────────


class TestYesNoOrientation:
    def test_outcomes_yes_no_no_change(self):
        toks, prices = _orient_yes_no(["Yes", "No"], ["t_yes", "t_no"], [0.6, 0.4])
        assert toks == ["t_yes", "t_no"]
        assert prices == [0.6, 0.4]

    def test_outcomes_no_yes_flipped(self):
        toks, prices = _orient_yes_no(["No", "Yes"], ["t_no", "t_yes"], [0.4, 0.6])
        assert toks == ["t_yes", "t_no"]
        assert prices == [0.6, 0.4]

    def test_case_insensitive(self):
        toks, prices = _orient_yes_no(["NO", "YES"], ["t_no", "t_yes"], [0.4, 0.6])
        assert toks == ["t_yes", "t_no"]

    def test_unrecognised_outcomes_no_change(self):
        # Don't guess — preserve API order when labels aren't in the YES/NO sets.
        toks, prices = _orient_yes_no(["Maybe", "Probably"], ["a", "b"], [0.3, 0.7])
        assert toks == ["a", "b"]
        assert prices == [0.3, 0.7]

    def test_missing_outcomes_no_change(self):
        toks, prices = _orient_yes_no(None, ["a", "b"], [0.3, 0.7])
        assert toks == ["a", "b"]

    def test_json_string_outcomes(self):
        toks, prices = _orient_yes_no('["No", "Yes"]', ["t_no", "t_yes"], [0.4, 0.6])
        assert toks == ["t_yes", "t_no"]
        assert prices == [0.6, 0.4]
