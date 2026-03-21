"""
Domain interfaces and models for the notifications module.
"""

from internal.core.notifications.domain.interfaces import (
    Alert,
    AlertSeverity,
    AlertType,
    NotificationChannel,
    NotificationChannelError,
    RateLimitError,
    ValidationError,
)

__all__ = [
    "Alert",
    "AlertSeverity",
    "AlertType",
    "NotificationChannel",
    "NotificationChannelError",
    "RateLimitError",
    "ValidationError",
]
