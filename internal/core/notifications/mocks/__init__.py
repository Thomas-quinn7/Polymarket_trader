"""
Mock notification channels for testing.
"""

from internal.core.notifications.mocks.failing_notification_channel import (
    FailingNotificationChannel,
)
from internal.core.notifications.mocks.mock_notification_channel import (
    MockNotificationChannel,
)

__all__ = [
    "MockNotificationChannel",
    "FailingNotificationChannel",
]
