"""
Unit tests for error handling module.
"""

import pytest

from pkg.errors import (
    AppError,
    MarketClientError,
    ConfigurationError,
    AuthenticationError,
    RateLimitError,
    OrderError,
    InsufficientBalanceError,
    InvalidOrderError,
    SettlementError,
    NotificationError,
    DiscordError,
    EmailError,
    StrategyError,
    DashboardError,
    SystemError,
)


class TestAppError:
    """Test cases for AppError base class."""

    def test_app_error_creation(self):
        """Test creating a basic AppError."""
        error = AppError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_app_error_with_args(self):
        """Test AppError with additional arguments."""
        error = AppError("Test error with args", "arg1", "arg2")
        assert str(error) == "Test error with args"


class TestMarketClientError:
    """Test cases for market client errors."""

    def test_market_client_error_creation(self):
        """Test creating a MarketClientError."""
        error = MarketClientError("API failed")
        assert str(error) == "API failed"
        assert isinstance(error, AppError)

    def test_market_client_error_with_status(self):
        """Test MarketClientError with status code."""
        error = MarketClientError("API failed", status_code=404)
        assert error.status_code == 404


class TestAuthenticationError:
    """Test cases for authentication errors."""

    def test_authentication_error(self):
        """Test AuthenticationError."""
        error = AuthenticationError()
        assert str(error) == "Authentication failed"
        assert error.status_code == 401

    def test_custom_auth_error(self):
        """Test custom AuthenticationError message."""
        error = AuthenticationError("Custom auth failure")
        assert str(error) == "Custom auth failure"


class TestRateLimitError:
    """Test cases for rate limit errors."""

    def test_rate_limit_error_default(self):
        """Test default RateLimitError."""
        error = RateLimitError()
        assert "Rate limited" in str(error)
        assert error.retry_after == 60.0

    def test_rate_limit_error_custom(self):
        """Test custom RateLimitError."""
        error = RateLimitError(retry_after=120.0)
        assert error.retry_after == 120.0


class TestOrderError:
    """Test cases for order errors."""

    def test_order_error(self):
        """Test OrderError."""
        error = OrderError("Order failed")
        assert str(error) == "Order failed"

    def test_order_error_with_id(self):
        """Test OrderError with order ID."""
        error = OrderError("Order failed", order_id="order_123")
        assert error.order_id == "order_123"


class TestInsufficientBalanceError:
    """Test cases for balance errors."""

    def test_insufficient_balance_error(self):
        """Test InsufficientBalanceError."""
        error = InsufficientBalanceError()
        assert str(error) == "Insufficient balance"

    def test_custom_balance_error(self):
        """Test custom InsufficientBalanceError."""
        error = InsufficientBalanceError("Not enough funds")
        assert str(error) == "Not enough funds"


class TestSettlementError:
    """Test cases for settlement errors."""

    def test_settlement_error(self):
        """Test SettlementError."""
        error = SettlementError("Settlement failed")
        assert str(error) == "Settlement failed"

    def test_settlement_error_with_market(self):
        """Test SettlementError with market ID."""
        error = SettlementError("Settlement failed", market_id="market_123")
        assert error.market_id == "market_123"


class TestNotificationError:
    """Test cases for notification errors."""

    def test_notification_error(self):
        """Test NotificationError."""
        error = NotificationError("Notification failed")
        assert str(error) == "Notification failed"

    def test_notification_error_with_channel(self):
        """Test NotificationError with channel."""
        error = NotificationError("Failed", channel="Discord")
        assert error.channel == "Discord"


class TestStrategyError:
    """Test cases for strategy errors."""

    def test_strategy_error(self):
        """Test StrategyError."""
        error = StrategyError("Strategy failed")
        assert str(error) == "Strategy failed"

    def test_strategy_error_with_strategy(self):
        """Test StrategyError with strategy name."""
        error = StrategyError("Failed", strategy="scanner")
        assert error.strategy == "scanner"


class TestDashboardError:
    """Test cases for dashboard errors."""

    def test_dashboard_error(self):
        """Test DashboardError."""
        error = DashboardError("Dashboard failed")
        assert str(error) == "Dashboard failed"


class TestSystemError:
    """Test cases for system errors."""

    def test_system_error(self):
        """Test SystemError."""
        error = SystemError("System failure")
        assert str(error) == "System failure"

    def test_system_error_with_component(self):
        """Test SystemError with component name."""
        error = SystemError("Failed", component="scanner")
        assert error.component == "scanner"
