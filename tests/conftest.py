"""
Pytest configuration and fixtures.
"""

import pytest
from datetime import datetime
from internal.core.scanner.domain import MarketOpportunity
from internal.core.execution.domain import ExecutionResult
from internal.core.notifications.domain import Alert


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
def mock_market_opportunity():
    """Create a mock market opportunity."""
    close_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return MarketOpportunity(
        market_id="market_001",
        outcome="YES",
        price=0.98,
        close_time=close_time,
        title="Test Market",
    )


@pytest.fixture
def mock_execution_result():
    """Create a mock execution result."""
    from internal.core.execution.domain import OrderStatus, OrderSide, OrderType

    return ExecutionResult(
        order_id="order_001",
        status=OrderStatus.FILLED,
        side=OrderSide.BUY,
        price=0.98,
        amount=100.0,
        market_id="market_001",
        filled_amount=100.0,
        timestamp=datetime.utcnow(),
    )


@pytest.fixture
def logger_capture():
    """Capture log output for testing."""
    import logging
    from io import StringIO

    # Create a string buffer to capture log output
    log_buffer = StringIO()

    # Set up logging to capture output
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)

    # Add to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    yield log_buffer

    # Cleanup
    root_logger.removeHandler(handler)


@pytest.fixture
def sample_positions():
    """Create sample positions for testing."""
    from internal.core.portfolio.domain import Position

    return [
        Position(
            position_id="pos_001",
            market_id="market_001",
            outcome="YES",
            side="BUY",
            quantity=100.0,
            entry_price=0.98,
            current_price=0.99,
            timestamp=datetime.utcnow(),
        )
    ]


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


@pytest.fixture
def sample_alerts():
    """Create sample alerts for testing."""
    from internal.core.notifications.domain import AlertSeverity, AlertType

    return [
        Alert(
            type=AlertType.WIN,
            severity=AlertSeverity.INFO,
            title="Position Won",
            message="Market resolved in favor of YES",
        ),
        Alert(
            type=AlertType.LOSS,
            severity=AlertSeverity.WARNING,
            title="Position Lost",
            message="Market resolved in favor of NO",
        ),
    ]
