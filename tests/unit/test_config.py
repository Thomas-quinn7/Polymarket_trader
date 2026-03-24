"""
Unit tests for configuration module.
"""

import pytest

from pkg.config import get_settings


class TestSettings:
    """Test cases for Settings class."""

    def test_default_settings(self):
        """Test that default settings are loaded correctly."""
        settings = get_settings()

        assert settings.min_price_threshold == 0.985
        assert settings.max_price_threshold == 1.0
        assert settings.max_positions == 5
        assert settings.scan_interval_ms == 500
        assert settings.execute_before_close_seconds > 0

    def test_default_enable_flags(self):
        """Test default values for feature flags."""
        settings = get_settings()

        assert settings.paper_trading_enabled is True
        assert settings.paper_trading_only is True
        assert settings.dashboard_enabled is True
        assert settings.enable_email_alerts is True
        assert settings.enable_discord_alerts is True

    def test_default_keywords(self):
        """Test default keyword configurations."""
        settings = get_settings()

        assert "bitcoin" in settings.crypto_keywords_list
        assert "ethereum" in settings.crypto_keywords_list
        assert "federal" in settings.fed_keywords_list
        assert "politics" in settings.other_keywords_list

    def test_category_priority_defaults(self):
        """Test default category priority values."""
        settings = get_settings()

        assert settings.priority_crypto == 1
        assert settings.priority_fed == 2
        assert settings.priority_regulatory == 3
        assert settings.priority_other == 4

    def test_min_max_filters(self):
        """Test min/max price and time filters."""
        settings = get_settings()

        assert settings.min_price_threshold <= settings.max_price_threshold
        assert settings.min_time_to_close <= settings.max_time_to_close

    def test_strategy_defaults(self):
        """Test default trading strategy parameters."""
        settings = get_settings()

        assert settings.order_type == "FOK"
        assert settings.slippage_tolerance_percent >= 0
        assert settings.max_retries >= 0

    def test_capital_split(self):
        """Test capital split percentage."""
        settings = get_settings()

        assert 0 < settings.capital_split_percent <= 1
