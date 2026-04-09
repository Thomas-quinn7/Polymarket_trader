"""
Custom exception hierarchy for the Polymarket Trading Bot.
Follows clean architecture patterns with specific error types.
"""


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, *args):
        self.message = message
        super().__init__(message, *args)

    def __str__(self) -> str:
        return self.message


# Polymarket API Errors
class MarketClientError(AppError):
    """Polymarket API call failed."""

    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        self.status_code = status_code
        self.response_data = response_data or {}
        super().__init__(message)


class ConfigurationError(AppError):
    """Missing or invalid configuration."""

    def __init__(self, message: str, config_key: str = None):
        self.config_key = config_key
        super().__init__(message)


class AuthenticationError(MarketClientError):
    """API authentication failed."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class RateLimitError(MarketClientError):
    """API rate limit hit - retry later."""

    def __init__(self, retry_after: float = 60.0):
        self.retry_after = retry_after
        message = f"Rate limited. Retry after {retry_after:.1f}s"
        super().__init__(message, status_code=429)


# Trading Execution Errors
class OrderError(AppError):
    """Order placement/settlement failed."""

    def __init__(self, message: str, order_id: str = None):
        self.order_id = order_id
        super().__init__(message)


class InsufficientBalanceError(OrderError):
    """Not enough balance to place order."""

    def __init__(self, message: str = "Insufficient balance"):
        super().__init__(message)


class InvalidOrderError(OrderError):
    """Order validation failed."""

    def __init__(self, message: str = "Invalid order parameters"):
        super().__init__(message)


class OrderExecutionError(OrderError):
    """Order execution failed."""

    def __init__(self, message: str, order_id: str = None):
        super().__init__(message, order_id)


class SettlementError(AppError):
    """Market settlement failed or unexpected outcome."""

    def __init__(self, message: str, market_id: str = None):
        self.market_id = market_id
        super().__init__(message)


# Portfolio Errors
class PortfolioError(AppError):
    """Portfolio management error."""

    def __init__(self, message: str, position_id: str = None):
        self.position_id = position_id
        super().__init__(message)


class BalanceError(PortfolioError):
    """Balance tracking error."""

    def __init__(self, message: str):
        super().__init__(message)


class PositionError(PortfolioError):
    """Position tracking error."""

    def __init__(self, message: str, position_id: str = None):
        super().__init__(message, position_id)


# Notification Errors
class NotificationError(AppError):
    """Alert delivery failed (non-fatal)."""

    def __init__(self, message: str, channel: str = None):
        self.channel = channel
        super().__init__(message)


class DiscordError(NotificationError):
    """Discord webhook delivery failed."""

    def __init__(self, message: str = "Discord notification failed"):
        super().__init__(message, channel="Discord")


class EmailError(NotificationError):
    """Email delivery failed."""

    def __init__(self, message: str = "Email notification failed"):
        super().__init__(message, channel="Email")


class NotificationRateLimitError(NotificationError):
    """Notification rate limit reached."""

    def __init__(self, retry_after: float = 60.0):
        self.retry_after = retry_after
        message = f"Notification rate limited. Retry after {retry_after:.1f}s"
        super().__init__(message, channel="RateLimiter")


# Strategy Errors
class StrategyError(AppError):
    """Trading strategy error."""

    def __init__(self, message: str, strategy: str = None):
        self.strategy = strategy
        super().__init__(message)


class NoOpportunityError(StrategyError):
    """No valid trading opportunities found."""

    def __init__(self, message: str = "No trading opportunities found"):
        super().__init__(message)


class MarketFilterError(StrategyError):
    """Market filtering error."""

    def __init__(self, message: str, market_id: str = None):
        self.market_id = market_id
        super().__init__(message)


# Dashboard Errors
class DashboardError(AppError):
    """Dashboard/API error."""

    def __init__(self, message: str):
        super().__init__(message)


class DashboardRouteError(DashboardError):
    """Invalid API route or endpoint."""

    def __init__(self, message: str):
        super().__init__(message)


class DashboardConfigError(DashboardError):
    """Dashboard configuration error."""

    def __init__(self, message: str):
        super().__init__(message)


# General System Errors
class SystemError(AppError):
    """System-level error."""

    def __init__(self, message: str, component: str = None):
        self.component = component
        super().__init__(message)


class DatabaseError(SystemError):
    """Database operation failed."""

    def __init__(self, message: str):
        super().__init__(message)


class InitializationError(SystemError):
    """System initialization failed."""

    def __init__(self, message: str):
        super().__init__(message)


# Error helpers
def get_error_message(exception: Exception) -> str:
    """
    Extract error message from exception.
    Supports custom exception types with message attributes.
    """
    if hasattr(exception, "message"):
        return exception.message
    return str(exception)


def get_error_details(exception: Exception) -> dict:
    """
    Extract structured error details from exception.
    Useful for logging and API responses.
    """
    details = {
        "type": type(exception).__name__,
        "message": get_error_message(exception),
    }

    # Add common exception attributes
    for attr in ["status_code", "retry_after", "order_id", "position_id", "market_id"]:
        if hasattr(exception, attr):
            details[attr] = getattr(exception, attr)

    # Add custom attributes
    for attr in ["config_key", "channel", "strategy", "component"]:
        if hasattr(exception, attr):
            details[attr] = getattr(exception, attr)

    return details
