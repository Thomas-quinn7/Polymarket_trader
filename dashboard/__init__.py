"""Dashboard package"""

from .api import app, start_dashboard, set_bot_instance, is_bot_available

__all__ = [
    "app",
    "start_dashboard",
    "set_bot_instance",
    "is_bot_available",
]
