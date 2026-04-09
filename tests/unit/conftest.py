"""
Isolated conftest for unit tests — prevents the top-level conftest from loading
internal.core packages that require optional dependencies (pydantic_settings).

Auto-mocks the alert_manager so that tests exercising error paths (rollback,
invalid prices, slippage abort, etc.) do not fire real email/webhook alerts.
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _suppress_alerts():
    """
    Silently suppress all alert_manager calls for every unit test.

    Without this, tests that deliberately trigger error paths (e.g.
    rollback on position-creation failure, insufficient funds, slippage
    abort) invoke the real alert_manager, which sends live emails and
    Discord webhooks — producing noise and exhausting rate limits.
    """
    mock_am = MagicMock()
    with patch("execution.order_executor.alert_manager", mock_am):
        yield mock_am
