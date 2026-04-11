"""
Unit tests for AlertManager (utils/alerts.py).

Covers:
- alert_history is a bounded deque
- Rate-limiting (_should_send_alert)
- Thread-pool dispatch for ERROR/CRITICAL alerts
- INFO/WARNING alerts do NOT trigger email/webhook
- _send_email_safe / _send_webhook_safe swallow exceptions
"""

import threading
from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from utils.alerts import AlertManager, AlertSeverity, AlertType


@pytest.fixture
def manager():
    """AlertManager with senders and executor mocked out."""
    with patch("utils.alerts.config") as cfg:
        cfg.ENABLE_EMAIL_ALERTS = False
        cfg.ENABLE_DISCORD_ALERTS = False
        cfg.DISCORD_WEBHOOK_URL = None
        cfg.DISCORD_MENTION_USER = None
        m = AlertManager()
    return m


# ── alert_history structure ────────────────────────────────────────────────


class TestAlertHistoryIsDeque:
    def test_history_type(self, manager):
        assert isinstance(manager.alert_history, deque)

    def test_history_maxlen(self, manager):
        assert manager.alert_history.maxlen == 1000

    def test_history_bounded(self, manager):
        """Appending beyond maxlen does not grow the deque."""
        for i in range(1100):
            manager._track_alert(AlertType.GENERAL_INFO, f"msg-{i}")
        assert len(manager.alert_history) == 1000

    def test_track_alert_appends(self, manager):
        manager._track_alert(AlertType.GENERAL_INFO, "hello")
        assert len(manager.alert_history) == 1


# ── rate limiting ──────────────────────────────────────────────────────────


class TestShouldSendAlert:
    def test_first_alert_always_allowed(self, manager):
        assert manager._should_send_alert(AlertType.GENERAL_INFO, "first") is True

    def test_duplicate_within_cooldown_blocked(self, manager):
        manager._track_alert(AlertType.GENERAL_INFO, "same-msg")
        result = manager._should_send_alert(AlertType.GENERAL_INFO, "same-msg")
        assert result is False

    def test_different_message_allowed(self, manager):
        manager._track_alert(AlertType.GENERAL_INFO, "msg-a")
        assert manager._should_send_alert(AlertType.GENERAL_INFO, "msg-b") is True

    def test_different_type_allowed(self, manager):
        manager._track_alert(AlertType.GENERAL_INFO, "msg")
        assert manager._should_send_alert(AlertType.SYSTEM_ERROR, "msg") is True

    def test_expired_cooldown_allows_resend(self, manager):
        """An entry older than cooldown_period is treated as expired → alert allowed."""
        old_ts = datetime.now() - timedelta(seconds=manager.cooldown_period + 1)
        with manager._history_lock:
            manager.alert_history.append(
                {"type": AlertType.GENERAL_INFO, "message": "msg", "timestamp": old_ts}
            )
        assert manager._should_send_alert(AlertType.GENERAL_INFO, "msg") is True


# ── thread-pool dispatch ───────────────────────────────────────────────────


class TestDispatch:
    def _manager_with_senders(self):
        """Return a manager with mock email + webhook senders and a real executor."""
        with patch("utils.alerts.config") as cfg:
            cfg.ENABLE_EMAIL_ALERTS = False
            cfg.ENABLE_DISCORD_ALERTS = False
            cfg.DISCORD_WEBHOOK_URL = None
            cfg.DISCORD_MENTION_USER = None
            m = AlertManager()

        m.email_sender = MagicMock()
        m.email_sender.send_alert.return_value = True
        m.webhook_sender = MagicMock()
        m.webhook_sender.send_alert.return_value = True
        return m

    def test_error_alert_submits_to_executor(self):
        m = self._manager_with_senders()
        mock_executor = MagicMock()
        m._executor = mock_executor

        with patch("utils.alerts.config") as cfg:
            cfg.ENABLE_EMAIL_ALERTS = True
            cfg.ENABLE_DISCORD_ALERTS = True
            m.email_enabled = True
            m.webhook_enabled = True
            m.create_alert(AlertType.SYSTEM_ERROR, "title", "msg", AlertSeverity.ERROR)

        # Both email and webhook submitted to thread pool — not called directly.
        assert mock_executor.submit.call_count == 2

    def test_critical_alert_submits_to_executor(self):
        m = self._manager_with_senders()
        mock_executor = MagicMock()
        m._executor = mock_executor
        m.email_enabled = True
        m.webhook_enabled = True

        with patch("utils.alerts.config"):
            m.create_alert(AlertType.CIRCUIT_BREAKER, "title", "msg", AlertSeverity.CRITICAL)

        assert mock_executor.submit.call_count == 2

    def test_info_alert_does_not_dispatch(self):
        m = self._manager_with_senders()
        mock_executor = MagicMock()
        m._executor = mock_executor
        m.email_enabled = True
        m.webhook_enabled = True

        with patch("utils.alerts.config"):
            m.create_alert(AlertType.GENERAL_INFO, "title", "msg", AlertSeverity.INFO)

        mock_executor.submit.assert_not_called()

    def test_warning_alert_does_not_dispatch(self):
        m = self._manager_with_senders()
        mock_executor = MagicMock()
        m._executor = mock_executor
        m.email_enabled = True
        m.webhook_enabled = True

        with patch("utils.alerts.config"):
            m.create_alert(AlertType.POSITION_LOSS, "title", "msg", AlertSeverity.WARNING)

        mock_executor.submit.assert_not_called()


# ── _send_*_safe exception handling ───────────────────────────────────────


class TestSendSafe:
    def test_send_email_safe_swallows_exception(self, manager):
        manager.email_sender = MagicMock()
        manager.email_sender.send_alert.side_effect = RuntimeError("SMTP down")
        # Must not raise
        manager._send_email_safe({"alert_type": "test", "severity": "ERROR"})

    def test_send_webhook_safe_swallows_exception(self, manager):
        manager.webhook_sender = MagicMock()
        manager.webhook_sender.send_alert.side_effect = ConnectionError("Discord unreachable")
        # Must not raise
        manager._send_webhook_safe({"alert_type": "test", "severity": "ERROR"})

    def test_send_email_safe_logs_on_failure(self, manager, caplog):
        import logging

        manager.email_sender = MagicMock()
        manager.email_sender.send_alert.side_effect = RuntimeError("boom")
        with caplog.at_level(logging.ERROR):
            manager._send_email_safe({})
        assert any("Email alert thread error" in r.message for r in caplog.records)

    def test_send_webhook_safe_logs_on_failure(self, manager, caplog):
        import logging

        manager.webhook_sender = MagicMock()
        manager.webhook_sender.send_alert.side_effect = RuntimeError("boom")
        with caplog.at_level(logging.ERROR):
            manager._send_webhook_safe({})
        assert any("Webhook alert thread error" in r.message for r in caplog.records)


# ── thread safety ──────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_track_alert_no_crash(self, manager):
        """Multiple threads tracking alerts simultaneously must not raise."""
        errors = []

        def track(n):
            try:
                for i in range(50):
                    manager._track_alert(AlertType.GENERAL_INFO, f"msg-{n}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=track, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent tracking: {errors}"
        assert len(manager.alert_history) <= 1000
