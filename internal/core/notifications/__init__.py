"""
Notifications module - Alert and notification management.
"""

from internal.core.notifications.domain import (
    Alert,
    AlertSeverity,
    AlertType,
    NotificationChannel,
    NotificationChannelError,
    RateLimitError,
    ValidationError,
)
from internal.core.notifications.service.notification_service import (
    DiscordChannel,
    EmailChannel,
    NotificationService,
)
from internal.core.notifications.mocks.mock_notification_channel import (
    MockNotificationChannel,
)
from internal.core.notifications.mocks.failing_notification_channel import (
    FailingNotificationChannel,
)

__all__ = [
    # Domain
    "Alert",
    "AlertSeverity",
    "AlertType",
    "NotificationChannel",
    "NotificationChannelError",
    "RateLimitError",
    "ValidationError",
    # Service
    "NotificationService",
    "DiscordChannel",
    "EmailChannel",
    # Mocks
    "MockNotificationChannel",
    "FailingNotificationChannel",
]
