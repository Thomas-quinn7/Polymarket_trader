"""
Domain interfaces and models for the notifications module.
Defines the protocol contracts and data structures.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pkg.errors import AppError


class AlertSeverity(Enum):
    """Severity levels for alerts."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertType(Enum):
    """Types of alerts that can be sent."""
    TRADE_EXECUTED = "trade_executed"
    POSITION_OPENED = "position_opened"
    POSITION_SETTLED = "position_settled"
    WIN = "win"
    LOSS = "loss"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    SYSTEM_ERROR = "system_error"
    RATE_LIMITED = "rate_limited"
    EXECUTION_ERROR = "execution_error"
    NO_OPPORTUNITY = "no_opportunity"


@dataclass
class Alert:
    """
    Represents a notification alert.
    Contains all information needed to format and send notifications.
    """
    type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    metadata: dict = None
    timestamp: Optional[str] = None

    def __post_init__(self):
        """Initialize timestamp if not provided."""
        if self.timestamp is None:
            from datetime import datetime
            self.timestamp = datetime.utcnow().isoformat()

        if self.metadata is None:
            self.metadata = {}

    @property
    def display_title(self) -> str:
        """Get a formatted title for display."""
        return f"{self.severity.value}: {self.title}"

    def to_dict(self) -> dict:
        """Convert alert to dictionary format."""
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class NotificationChannelError(AppError):
    """Error when a notification channel fails."""
    pass


class RateLimitError(NotificationChannelError):
    """Error when a notification channel is rate limited."""
    pass


class ValidationError(NotificationChannelError):
    """Error when notification data is invalid."""
    pass


class NotificationChannel(Protocol):
    """
    Protocol for notification channels.
    Each channel (Discord, Email, Slack) implements this protocol.
    """

    async def send(self, alert: Alert) -> bool:
        """
        Send an alert through this channel.

        Args:
            alert: The alert to send

        Returns:
            True if successful, False if failed

        Raises:
            NotificationChannelError: If sending fails
        """
        ...

    async def test_connection(self) -> bool:
        """
        Test the notification channel connection.

        Returns:
            True if connection is working
        """
        ...
