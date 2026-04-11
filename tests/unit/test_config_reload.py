"""
Tests for PolymarketConfig.reload().

Covers:
- Numeric, boolean, and list fields are updated in-place from a new env dict
- Fields not present in the new env fall back to their defaults
- Reload does not affect fields that require a restart (they are not re-applied
  until the process restarts — this test just verifies reload doesn't clear them)
- reload() is idempotent when called twice with the same values
"""

import pytest
from unittest.mock import patch

from config.polymarket_config import PolymarketConfig


def _config():
    """Fresh PolymarketConfig with a known starting state."""
    with patch.dict("os.environ", {}, clear=True):
        cfg = PolymarketConfig()
    return cfg


def _reload(cfg, env: dict):
    """Call cfg.reload() with dotenv_values patched to return env.

    reload() does `from dotenv import dotenv_values` inside its body, so we
    must patch the name on the dotenv module itself, not on polymarket_config.
    """
    with patch("dotenv.dotenv_values", return_value=env):
        cfg.reload()


# ── numeric fields ─────────────────────────────────────────────────────────

class TestReloadNumericFields:
    def test_scan_interval_updated(self):
        cfg = _config()
        _reload(cfg, {"SCAN_INTERVAL_MS": "60000"})
        assert cfg.SCAN_INTERVAL_MS == 60000

    def test_max_positions_updated(self):
        cfg = _config()
        _reload(cfg, {"MAX_POSITIONS": "10"})
        assert cfg.MAX_POSITIONS == 10

    def test_capital_split_updated(self):
        cfg = _config()
        _reload(cfg, {"CAPITAL_SPLIT_PERCENT": "0.10"})
        assert cfg.CAPITAL_SPLIT_PERCENT == pytest.approx(0.10)

    def test_min_confidence_updated(self):
        cfg = _config()
        _reload(cfg, {"MIN_CONFIDENCE": "0.75"})
        assert cfg.MIN_CONFIDENCE == pytest.approx(0.75)

    def test_taker_fee_updated(self):
        cfg = _config()
        _reload(cfg, {"TAKER_FEE_PERCENT": "1.5"})
        assert cfg.TAKER_FEE_PERCENT == pytest.approx(1.5)

    def test_stop_loss_updated(self):
        cfg = _config()
        _reload(cfg, {"STOP_LOSS_PERCENT": "3.0"})
        assert cfg.STOP_LOSS_PERCENT == pytest.approx(3.0)


# ── boolean fields ─────────────────────────────────────────────────────────

class TestReloadBooleanFields:
    def test_paper_trading_only_toggled_false(self):
        cfg = _config()
        _reload(cfg, {"PAPER_TRADING_ONLY": "False"})
        assert cfg.PAPER_TRADING_ONLY is False

    def test_paper_trading_only_toggled_true(self):
        cfg = _config()
        cfg.PAPER_TRADING_ONLY = False
        _reload(cfg, {"PAPER_TRADING_ONLY": "True"})
        assert cfg.PAPER_TRADING_ONLY is True

    def test_dashboard_enabled_toggled(self):
        cfg = _config()
        _reload(cfg, {"DASHBOARD_ENABLED": "False"})
        assert cfg.DASHBOARD_ENABLED is False

    def test_log_to_file_toggled(self):
        cfg = _config()
        _reload(cfg, {"LOG_TO_FILE": "False"})
        assert cfg.LOG_TO_FILE is False


# ── string / list fields ───────────────────────────────────────────────────

class TestReloadStringFields:
    def test_trading_mode_updated(self):
        cfg = _config()
        _reload(cfg, {"TRADING_MODE": "simulation"})
        assert cfg.TRADING_MODE == "simulation"

    def test_strategy_updated(self):
        cfg = _config()
        _reload(cfg, {"STRATEGY": "enhanced_market_scanner"})
        assert cfg.STRATEGY == "enhanced_market_scanner"

    def test_log_level_updated(self):
        cfg = _config()
        _reload(cfg, {"LOG_LEVEL": "DEBUG"})
        assert cfg.LOG_LEVEL == "DEBUG"

    def test_scan_categories_parsed(self):
        cfg = _config()
        _reload(cfg, {"SCAN_CATEGORIES": "crypto,fed"})
        assert cfg.SCAN_CATEGORIES == ["crypto", "fed"]

    def test_scan_categories_trims_whitespace(self):
        cfg = _config()
        _reload(cfg, {"SCAN_CATEGORIES": " crypto , fed , other "})
        assert cfg.SCAN_CATEGORIES == ["crypto", "fed", "other"]


# ── defaults when key absent ───────────────────────────────────────────────

class TestReloadDefaults:
    def test_missing_key_uses_default_scan_interval(self):
        cfg = _config()
        _reload(cfg, {})   # empty env → all defaults
        assert cfg.SCAN_INTERVAL_MS == 30000

    def test_missing_key_uses_default_max_positions(self):
        cfg = _config()
        _reload(cfg, {})
        assert cfg.MAX_POSITIONS == 5

    def test_missing_key_uses_default_trading_mode(self):
        cfg = _config()
        _reload(cfg, {})
        assert cfg.TRADING_MODE == "paper"


# ── idempotency ────────────────────────────────────────────────────────────

class TestReloadIdempotent:
    def test_double_reload_same_values(self):
        cfg = _config()
        env = {"SCAN_INTERVAL_MS": "45000", "MAX_POSITIONS": "3"}
        _reload(cfg, env)
        _reload(cfg, env)
        assert cfg.SCAN_INTERVAL_MS == 45000
        assert cfg.MAX_POSITIONS == 3
