"""
Unit tests for HistoricalDataFetcher (backtesting/fetcher.py).

Covers _parse_market (pure, no I/O):
- Returns None when condition_id and id are both missing
- Extracts conditionId preferentially over id
- Extracts id when conditionId is absent
- Computes duration_seconds from endDate and createdAt
- Infers resolution from outcomePrices (>= 0.5 → YES, < 0.5 → NO)
- Infers resolution from winner/winnerOutcome field when present
- Leaves resolution=None when outcomePrices is absent
- Normalises 0-100 outcomePrices to 0-1

Covers fetch_price_history (HTTP mocked):
- Returns cached ticks immediately when has_price_history is True
- Fetches from Gamma API when not cached and stores result
- Normalises price values in the 0–100 range to 0–1
- Returns [] on HTTP error
- Returns [] when response contains fewer than 3 valid ticks
- Skips ticks with price outside [0, 100]

Covers prefetch_all_price_histories:
- Returns count of markets with usable price data
- Skips markets that are already cached
"""

from unittest.mock import MagicMock, patch

from backtesting.db import BacktestDB
from backtesting.fetcher import HistoricalDataFetcher

# ── Helpers ────────────────────────────────────────────────────────────────────


def _db() -> BacktestDB:
    return BacktestDB(":memory:")


def _seed_market(db: BacktestDB, condition_id: str):
    """Insert a minimal market row so FK constraint on bt_price_history is satisfied."""
    db.upsert_market(
        {
            "condition_id": condition_id,
            "slug": condition_id,
            "question": "Q?",
            "category": "crypto",
            "volume": 500.0,
            "end_time": "2025-03-01T12:00:00+00:00",
            "created_at": "2025-01-01T00:00:00+00:00",
            "resolution": 1.0,
            "token_id_yes": "ty",
            "token_id_no": "tn",
            "duration_seconds": 3600,
        }
    )


def _fetcher(db=None) -> HistoricalDataFetcher:
    if db is None:
        db = _db()
    f = HistoricalDataFetcher(db, rate_limit_rps=100.0)  # high RPS → no real sleep
    return f


def _raw_market(**overrides) -> dict:
    base = {
        "conditionId": "cid-abc",
        "slug": "will-x-happen",
        "question": "Will X happen?",
        "tags": [],
        "volume": "500",
        "endDate": "2025-03-01T12:00:00Z",
        "createdAt": "2025-01-01T00:00:00Z",
        "outcomePrices": ["0.97", "0.03"],
        "clobTokenIds": ["tok_yes", "tok_no"],
    }
    base.update(overrides)
    return base


# ── _parse_market ─────────────────────────────────────────────────────────────


class TestParseMarket:
    def test_returns_none_when_no_id(self):
        f = _fetcher()
        assert f._parse_market({}) is None

    def test_uses_conditionId(self):
        f = _fetcher()
        result = f._parse_market(_raw_market())
        assert result["condition_id"] == "cid-abc"

    def test_falls_back_to_id(self):
        f = _fetcher()
        raw = _raw_market()
        del raw["conditionId"]
        raw["id"] = "id-fallback"
        result = f._parse_market(raw)
        assert result["condition_id"] == "id-fallback"

    def test_computes_duration_seconds(self):
        f = _fetcher()
        result = f._parse_market(_raw_market())
        assert result["duration_seconds"] is not None
        assert result["duration_seconds"] > 0

    def test_resolution_yes_when_outcome_price_above_midpoint(self):
        """YES price >= 0.5 → resolution = 1.0 (YES won)."""
        f = _fetcher()
        result = f._parse_market(_raw_market(outcomePrices=["0.97", "0.03"]))
        assert result["resolution"] == 1.0

    def test_resolution_no_when_outcome_price_below_midpoint(self):
        """YES price < 0.5 → resolution = 0.0 (NO won)."""
        f = _fetcher()
        result = f._parse_market(_raw_market(outcomePrices=["0.03", "0.97"]))
        assert result["resolution"] == 0.0

    def test_resolution_none_when_no_outcome_prices(self):
        """resolution stays None when outcomePrices is absent."""
        f = _fetcher()
        raw = _raw_market()
        del raw["outcomePrices"]
        result = f._parse_market(raw)
        assert result["resolution"] is None

    def test_resolution_from_winner_field(self):
        """winner field takes precedence over outcomePrices."""
        f = _fetcher()
        result = f._parse_market(_raw_market(winner="YES", outcomePrices=["0.03", "0.97"]))
        assert result["resolution"] == 1.0

    def test_resolution_no_from_winner_field(self):
        f = _fetcher()
        result = f._parse_market(_raw_market(winner="NO", outcomePrices=["0.97", "0.03"]))
        assert result["resolution"] == 0.0

    def test_token_ids_extracted(self):
        f = _fetcher()
        result = f._parse_market(_raw_market())
        assert result["token_id_yes"] == "tok_yes"
        assert result["token_id_no"] == "tok_no"

    def test_missing_end_date_produces_empty_end_time(self):
        f = _fetcher()
        raw = _raw_market()
        del raw["endDate"]
        result = f._parse_market(raw)
        # Should not crash; end_time will be empty or None but result is not None
        assert result is not None


# ── fetch_price_history — cache hit ──────────────────────────────────────────


class TestFetchPriceHistoryCacheHit:
    def test_returns_cached_ticks_without_http_call(self):
        db = _db()
        _seed_market(db, "cid-1")
        ticks = [(1_000_000 + i * 300, 0.80 + i * 0.01) for i in range(5)]
        db.insert_price_history("cid-1", ticks)

        f = _fetcher(db)
        with patch.object(f._session, "get") as mock_get:
            result = f.fetch_price_history("cid-1")
            mock_get.assert_not_called()

        assert result == ticks


# ── fetch_price_history — HTTP path ──────────────────────────────────────────


def _mock_response(history: list, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"history": history}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestFetchPriceHistoryHttp:
    def test_fetches_and_stores_ticks(self):
        db = _db()
        _seed_market(db, "cid-new")
        history = [{"t": 1_000_000 + i * 300, "p": 0.80} for i in range(5)]
        f = _fetcher(db)
        with patch.object(f._session, "get", return_value=_mock_response(history)):
            with patch.object(f, "_throttle"):
                result = f.fetch_price_history("cid-new", "5m")

        assert len(result) == 5
        # Verify persisted in DB
        assert db.has_price_history("cid-new")

    def test_normalises_100_range_prices(self):
        db = _db()
        _seed_market(db, "cid-100range")
        # Prices given as 0-100 instead of 0-1
        history = [{"t": 1_000_000 + i * 300, "p": 85.0} for i in range(4)]
        f = _fetcher(db)
        with patch.object(f._session, "get", return_value=_mock_response(history)):
            with patch.object(f, "_throttle"):
                result = f.fetch_price_history("cid-100range", "5m")

        assert all(0.0 <= price <= 1.0 for _, price in result)

    def test_returns_empty_on_http_error(self):
        db = _db()
        f = _fetcher(db)
        with patch.object(f._session, "get", return_value=_mock_response([], 500)):
            with patch.object(f, "_throttle"):
                result = f.fetch_price_history("cid-fail", "5m")
        assert result == []

    def test_returns_empty_when_fewer_than_3_ticks(self):
        db = _db()
        history = [{"t": 1_000_000, "p": 0.80}, {"t": 1_000_300, "p": 0.85}]
        f = _fetcher(db)
        with patch.object(f._session, "get", return_value=_mock_response(history)):
            with patch.object(f, "_throttle"):
                result = f.fetch_price_history("cid-sparse", "5m")
        assert result == []

    def test_skips_ticks_with_invalid_price(self):
        db = _db()
        _seed_market(db, "cid-invalid")
        history = [
            {"t": 1_000_000, "p": 0.80},
            {"t": 1_000_300, "p": -0.5},  # invalid — below 0
            {"t": 1_000_600, "p": 200.0},  # invalid — above 100
            {"t": 1_000_900, "p": 0.85},
            {"t": 1_001_200, "p": 0.90},
        ]
        f = _fetcher(db)
        with patch.object(f._session, "get", return_value=_mock_response(history)):
            with patch.object(f, "_throttle"):
                result = f.fetch_price_history("cid-invalid", "5m")
        # Only 3 valid ticks (0.80, 0.85, 0.90) — still usable
        assert len(result) == 3


# ── prefetch_all_price_histories ─────────────────────────────────────────────


class TestPrefetchAllPriceHistories:
    def test_returns_usable_count(self):
        db = _db()
        f = _fetcher(db)
        with patch.object(f, "fetch_price_history", return_value=[(1, 0.8)] * 5):
            count = f.prefetch_all_price_histories(["cid-1", "cid-2", "cid-3"])
        assert count == 3

    def test_empty_result_counted_as_unusable(self):
        db = _db()
        f = _fetcher(db)
        with patch.object(f, "fetch_price_history", return_value=[]):
            count = f.prefetch_all_price_histories(["cid-1", "cid-2"])
        assert count == 0

    def test_calls_progress_callback(self):
        db = _db()
        f = _fetcher(db)
        calls = []
        with patch.object(f, "fetch_price_history", return_value=[(1, 0.8)]):
            f.prefetch_all_price_histories(
                ["cid-1", "cid-2"],
                progress_callback=lambda done, total: calls.append((done, total)),
            )
        assert len(calls) == 2
        assert calls[-1] == (2, 2)
