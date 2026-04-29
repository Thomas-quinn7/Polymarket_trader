"""Unit tests for ExternalDataBus — no actual network calls."""

import time
from unittest.mock import MagicMock, patch

from data.external.bus import ExternalDataBus
from data.external.snapshot import ExternalSnapshot


def _make_cfg(
    enabled=True,
    symbols="BTC",
    crypto_ttl=999,
    fng_ttl=999,
    macro_ttl=999,
    fred_key="",
):
    cfg = MagicMock()
    cfg.EXTERNAL_DATA_ENABLED = enabled
    cfg.EXTERNAL_CRYPTO_SYMBOLS = symbols
    cfg.EXTERNAL_CRYPTO_TTL_S = crypto_ttl
    cfg.EXTERNAL_FNG_TTL_S = fng_ttl
    cfg.EXTERNAL_MACRO_TTL_S = macro_ttl
    cfg.FRED_API_KEY = fred_key
    return cfg


class TestExternalDataBusDisabled:
    def test_returns_empty_snapshot_when_disabled(self):
        bus = ExternalDataBus(_make_cfg(enabled=False))
        snap = bus.get_snapshot()
        assert isinstance(snap, ExternalSnapshot)
        assert not snap.has_crypto_data()
        assert snap.fear_greed_index is None
        assert snap.fed_funds_rate is None

    def test_no_provider_calls_when_disabled(self):
        bus = ExternalDataBus(_make_cfg(enabled=False))
        with patch("data.external.binance.fetch_spot_prices") as mock_b:
            with patch("data.external.coingecko.fetch_prices") as mock_cg:
                with patch("data.external.fear_greed.fetch") as mock_fg:
                    bus.get_snapshot()
                    mock_b.assert_not_called()
                    mock_cg.assert_not_called()
                    mock_fg.assert_not_called()


class TestExternalDataBusCacheHit:
    def test_cache_hit_makes_no_provider_calls(self):
        bus = ExternalDataBus(_make_cfg(crypto_ttl=999, fng_ttl=999, macro_ttl=999))

        # Prime the cache with fake data and fresh timestamps
        bus._crypto_prices = {"BTC": 50000.0}
        now = time.monotonic()
        bus._crypto_ts = now
        bus._fg_ts = now
        bus._macro_ts = now

        with patch("data.external.binance.fetch_spot_prices") as mock_b:
            with patch("data.external.coingecko.fetch_prices") as mock_cg:
                with patch("data.external.fear_greed.fetch") as mock_fg:
                    snap = bus.get_snapshot()
                    mock_b.assert_not_called()
                    mock_cg.assert_not_called()
                    mock_fg.assert_not_called()

        assert snap.price("BTC") == 50000.0

    def test_cache_hit_is_fast(self):
        bus = ExternalDataBus(_make_cfg(crypto_ttl=999, fng_ttl=999, macro_ttl=999))
        bus._crypto_prices = {"BTC": 50000.0}
        now = time.monotonic()
        bus._crypto_ts = now
        bus._fg_ts = now
        bus._macro_ts = now

        with patch("data.external.binance.fetch_spot_prices"):
            start = time.monotonic()
            bus.get_snapshot()
            elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 100  # cache hit should be well under 100ms


class TestExternalDataBusFallback:
    def test_binance_failure_triggers_coingecko_fallback(self):
        bus = ExternalDataBus(_make_cfg(crypto_ttl=0, fng_ttl=999, macro_ttl=999))
        bus._fg_ts = time.monotonic()
        bus._macro_ts = time.monotonic()

        with patch("data.external.binance.fetch_spot_prices", return_value={}):
            with patch("data.external.coingecko.fetch_prices", return_value={"BTC": 90000.0}):
                with patch("data.external.binance.fetch_ticker_24h", return_value={}):
                    with patch("data.external.binance.fetch_closes", return_value=[]):
                        snap = bus.get_snapshot()

        assert snap.price("BTC") == 90000.0

    def test_binance_success_skips_coingecko(self):
        bus = ExternalDataBus(_make_cfg(crypto_ttl=0, fng_ttl=999, macro_ttl=999))
        bus._fg_ts = time.monotonic()
        bus._macro_ts = time.monotonic()

        with patch("data.external.binance.fetch_spot_prices", return_value={"BTC": 95000.0}):
            with patch("data.external.coingecko.fetch_prices") as mock_cg:
                with patch("data.external.binance.fetch_ticker_24h", return_value={}):
                    with patch("data.external.binance.fetch_closes", return_value=[]):
                        snap = bus.get_snapshot()
                        mock_cg.assert_not_called()

        assert snap.price("BTC") == 95000.0


class TestExternalDataBusInvalidate:
    def test_invalidate_forces_refresh(self):
        bus = ExternalDataBus(_make_cfg(crypto_ttl=999, fng_ttl=999, macro_ttl=999))
        now = time.monotonic()
        bus._crypto_ts = now
        bus._fg_ts = now
        bus._macro_ts = now

        bus.invalidate()

        assert bus._crypto_ts == 0.0
        assert bus._fg_ts == 0.0
        assert bus._macro_ts == 0.0
