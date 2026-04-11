"""
Pytest configuration and fixtures.
"""

import pytest


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""

    class MockSettings:
        min_price_threshold = 0.985
        max_price_threshold = 1.0
        max_positions = 5
        scan_interval_ms = 500
        execute_before_close_seconds = 2
        paper_trading_enabled = True
        paper_trading_only = True
        dashboard_enabled = True
        enable_email_alerts = True
        enable_discord_alerts = True
        fake_currency_balance = 10000.0
        crypto_keywords = "bitcoin,ethereum"
        fed_keywords = "federal,reserve"
        regulatory_keywords = "sec,regulation"
        other_keywords = "politics"
        priority_crypto = 1
        priority_fed = 2
        priority_regulatory = 3
        priority_other = 4
        order_type = "FOK"
        slippage_tolerance_percent = 5.0
        max_retries = 3
        capital_split_percent = 0.2

        @property
        def crypto_keywords_list(self):
            return ["bitcoin", "ethereum"]

        @property
        def fed_keywords_list(self):
            return ["federal", "reserve"]

        @property
        def regulatory_keywords_list(self):
            return ["sec", "regulation"]

        @property
        def other_keywords_list(self):
            return ["politics"]

    return MockSettings()


@pytest.fixture
def logger_capture():
    """Capture log output for testing."""
    import logging
    from io import StringIO

    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    yield log_buffer

    root_logger.removeHandler(handler)


@pytest.fixture
def sample_markets():
    """Create sample markets for testing."""
    return [
        {
            "id": "market_001",
            "title": "Will Bitcoin exceed $100k?",
            "closeTime": "2026-12-31T23:59:59Z",
        },
        {
            "id": "market_002",
            "title": "Will Ethereum reach $5000?",
            "closeTime": "2026-06-30T23:59:59Z",
        },
    ]
