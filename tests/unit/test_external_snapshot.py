"""Unit tests for ExternalSnapshot — no network calls, no external deps."""

from data.external.snapshot import ExternalSnapshot


class TestExternalSnapshot:
    def test_empty_snapshot_safe_to_use(self):
        # All convenience methods return False/None on an empty snapshot
        s = ExternalSnapshot()
        assert s.price("BTC") is None
        assert s.rsi("BTC") is None
        assert s.change_24h("BTC") is None
        assert s.is_fear_regime() is False
        assert s.is_greed_regime() is False
        assert s.is_overbought("BTC") is False
        assert s.is_oversold("BTC") is False
        assert s.has_crypto_data() is False

    def test_price_lookup_case_insensitive(self):
        s = ExternalSnapshot(crypto_prices={"BTC": 94500.0})
        assert s.price("btc") == 94500.0
        assert s.price("BTC") == 94500.0
        assert s.price("Btc") == 94500.0

    def test_is_fear_regime_threshold(self):
        s = ExternalSnapshot(fear_greed_index=25)
        assert s.is_fear_regime(threshold=30) is True  # 25 < 30
        assert s.is_fear_regime(threshold=20) is False  # 25 >= 20

    def test_is_overbought_threshold(self):
        s = ExternalSnapshot(crypto_rsi_1h={"BTC": 75.0})
        assert s.is_overbought("BTC", threshold=70.0) is True
        assert s.is_overbought("BTC", threshold=80.0) is False

    def test_age_seconds_increases(self):
        import time

        s = ExternalSnapshot()
        time.sleep(0.01)
        assert s.age_seconds() > 0.0

    def test_repr_does_not_raise(self):
        s = ExternalSnapshot(
            crypto_prices={"BTC": 94500.0},
            fear_greed_index=42,
            fed_funds_rate=5.33,
        )
        r = repr(s)
        assert "BTC" in r
        assert "42" in r
