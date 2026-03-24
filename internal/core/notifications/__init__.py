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
]
