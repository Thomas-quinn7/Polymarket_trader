"""
Notification Service - Main business logic for alert management.
"""

from internal.core.notifications.service.notification_service import (
    DiscordChannel,
    EmailChannel,
    NotificationService,
)

__all__ = [
    "NotificationService",
    "DiscordChannel",
    "EmailChannel",
]
