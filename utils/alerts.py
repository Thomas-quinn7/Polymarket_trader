"""
Alert Notification System
Manages alert creation and dispatch via email and webhooks
"""

import atexit
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
import json

from utils.logger import logger
from config.polymarket_config import config


class AlertType(str, Enum):
    """Alert types"""

    TRADE_EXECUTED = "trade_executed"
    ORDER_FAILED = "order_failed"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    CIRCUIT_BREAKER = "circuit_breaker"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    CONNECTION_ERROR = "connection_error"
    API_ERROR = "api_error"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_LOSS = "position_loss"
    OPPORTUNITY_DETECTED = "opportunity_detected"
    GENERAL_INFO = "general_info"
    SYSTEM_ERROR = "system_error"


class AlertSeverity(str, Enum):
    """Alert severity levels"""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertManager:
    """
    Manages alert creation and notification dispatch

    Features:
    - Create alerts for various events
    - Dispatch alerts via email and webhook
    - Rate limiting for alerts
    - Alert history tracking
    """

    def __init__(self):
        self.email_enabled = config.ENABLE_EMAIL_ALERTS
        self.webhook_enabled = config.ENABLE_DISCORD_ALERTS

        # Rate limiting — bounded deque so memory never grows unbounded
        self.alert_history: deque = deque(maxlen=1000)
        self.cooldown_period = 300  # 5 minutes between similar alerts
        self._history_lock = threading.Lock()

        # Thread pool for offloading blocking I/O (email + webhook) off the trading thread.
        # max_workers=2: one worker per transport (email, Discord) so they run in parallel.
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alert")
        # Ensure the executor is shut down cleanly when the process exits so that
        # in-flight alert tasks are not abandoned mid-send.
        atexit.register(self._executor.shutdown, wait=False)

        # Import senders if needed
        self.email_sender = None
        self.webhook_sender = None

        if self.email_enabled or self.webhook_enabled:
            self._initialize_senders()

    def _initialize_senders(self):
        """Initialize notification senders"""
        if self.email_enabled:
            try:
                from utils.email_sender import EmailSender

                self.email_sender = EmailSender()
                logger.info("Email alerts initialized")
            except Exception as e:
                logger.error(f"Failed to initialize email sender: {e}")

        if self.webhook_enabled:
            try:
                from utils.webhook_sender import WebhookSender

                if config.DISCORD_WEBHOOK_URL:
                    self.webhook_sender = WebhookSender(
                        config.DISCORD_WEBHOOK_URL,
                        discord_username=config.DISCORD_MENTION_USER,
                    )
                    self.webhook_enabled = True
                    logger.info(
                        f"Webhook alerts initialized (mentions: @{config.DISCORD_MENTION_USER or 'none'})"
                    )
                else:
                    logger.warning("Discord webhook URL not configured")
                    self.webhook_enabled = False
            except Exception as e:
                logger.error(f"Failed to initialize webhook sender: {e}")

    def create_alert(
        self,
        alert_type: AlertType,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
        data: Optional[Dict] = None,
    ) -> bool:
        """
        Create and dispatch an alert

        Args:
            alert_type: Type of alert
            title: Alert title
            message: Alert message
            severity: Alert severity
            data: Additional data (will be JSON serialized)

        Returns:
            True if alert was created successfully
        """

        # Check rate limiting
        if not self._should_send_alert(alert_type, message):
            logger.debug(f"Alert rate limited: {alert_type}")
            return True

        # Prepare alert data
        alert_data = {
            "alert_type": alert_type.value,
            "severity": severity.value,
            "title": title,
            "message": message,
            "data": json.dumps(data) if data else None,
        }

        # Dispatch notifications off the trading thread so blocking I/O (SMTP, Discord HTTP)
        # never stalls the main loop.  Fire-and-forget: failures are logged inside each sender.
        if severity in [AlertSeverity.ERROR, AlertSeverity.CRITICAL]:
            if self.email_sender:
                self._executor.submit(self._send_email_safe, alert_data)

            if self.webhook_sender:
                self._executor.submit(self._send_webhook_safe, alert_data)

        # Track alert history
        self._track_alert(alert_type, message)

        # Log alert
        if severity == AlertSeverity.CRITICAL:
            logger.critical(f"[{alert_type.value}] {title}: {message}")
        elif severity == AlertSeverity.ERROR:
            logger.error(f"[{alert_type.value}] {title}: {message}")
        elif severity == AlertSeverity.WARNING:
            logger.warning(f"[{alert_type.value}] {title}: {message}")
        else:
            logger.info(f"[{alert_type.value}] {title}: {message}")

        return True

    def _send_email_safe(self, alert_data: Dict):
        """Send email alert; called from the thread pool — never raises."""
        try:
            if not self.email_sender.send_alert(alert_data):
                logger.error("Failed to send email alert")
        except Exception as exc:
            logger.error(f"Email alert thread error: {exc}")

    def _send_webhook_safe(self, alert_data: Dict):
        """Send webhook alert; called from the thread pool — never raises."""
        try:
            if not self.webhook_sender.send_alert(alert_data):
                logger.error("Failed to send webhook alert")
        except Exception as exc:
            logger.error(f"Webhook alert thread error: {exc}")

    def _should_send_alert(self, alert_type: AlertType, message: str) -> bool:
        """Check if alert should be sent based on rate limiting.

        Uses the bounded deque directly — no list rebuild required.  Entries
        older than cooldown_period are simply ignored during the scan rather
        than being purged eagerly; the deque's maxlen of 1000 bounds worst-case
        iteration to O(1000) which is negligible.
        """
        now = datetime.now()
        with self._history_lock:
            for entry in self.alert_history:
                if (now - entry["timestamp"]).total_seconds() >= self.cooldown_period:
                    continue
                if entry["type"] == alert_type and entry["message"] == message:
                    return False
        return True

    def _track_alert(self, alert_type: AlertType, message: str):
        """Track alert for rate limiting"""
        with self._history_lock:
            self.alert_history.append(
                {"type": alert_type, "message": message, "timestamp": datetime.now()}
            )

    def send_trade_alert(
        self,
        action: str,
        symbol: str,
        quantity: float,
        price: float,
        total: float,
        reason: str = "",
    ):
        """Send trade execution alert"""
        title = f"Trade Executed: {action} {symbol}"
        message = f"""
Action: {action}
Symbol: {symbol}
Quantity: {quantity}
Price: ${price:.4f}
Total: ${total:.2f}
"""
        if reason:
            message += f"Reason: {reason}\n"

        data = {
            "action": action,
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "total": total,
            "reason": reason,
        }

        self.create_alert(
            AlertType.TRADE_EXECUTED, title, message.strip(), AlertSeverity.INFO, data
        )

    def send_position_opened_alert(
        self, position_id: str, market_id: str, quantity: float, price: float
    ):
        """Send position opened alert"""
        title = f"Position Opened: {position_id}"
        message = f"""
Position ID: {position_id}
Market: {market_id}
Quantity: {quantity}
Entry Price: ${price:.4f}
"""

        data = {
            "position_id": position_id,
            "market_id": market_id,
            "quantity": quantity,
            "price": price,
        }

        self.create_alert(
            AlertType.POSITION_OPENED, title, message.strip(), AlertSeverity.INFO, data
        )

    def send_position_closed_alert(
        self, position_id: str, market_id: str, exit_price: float, pnl: float
    ):
        """Send position closed alert"""
        if pnl >= 0:
            title = f"Position Settled (WIN): {position_id}"
            severity = AlertSeverity.INFO
        else:
            title = f"Position Settled (LOSS): {position_id}"
            severity = AlertSeverity.WARNING

        message = f"""
Position ID: {position_id}
Market: {market_id}
Exit Price: ${exit_price:.4f}
P&L: ${pnl:.2f}
"""

        data = {
            "position_id": position_id,
            "market_id": market_id,
            "exit_price": exit_price,
            "pnl": pnl,
        }

        self.create_alert(AlertType.POSITION_CLOSED, title, message.strip(), severity, data)

    def send_position_loss_alert(self, position_id: str, market_id: str, loss: float):
        """Send position loss alert"""
        title = f"Position Loss Detected: {position_id}"
        message = f"""
Position {position_id} has resulted in a loss!
Market: {market_id}
Loss: ${abs(loss):.2f}
"""

        data = {"position_id": position_id, "market_id": market_id, "loss": loss}

        self.create_alert(
            AlertType.POSITION_LOSS, title, message.strip(), AlertSeverity.WARNING, data
        )

    def send_opportunity_detected_alert(self, market_id: str, price: float, edge: float):
        """Send opportunity detected alert"""
        title = f"Arbitrage Opportunity: {market_id}"
        message = f"""
Market: {market_id}
Price: ${price:.4f}
Edge: {edge:.2f}%
"""

        data = {"market_id": market_id, "price": price, "edge": edge}

        self.create_alert(
            AlertType.OPPORTUNITY_DETECTED,
            title,
            message.strip(),
            AlertSeverity.INFO,
            data,
        )

    def send_system_start_alert(self):
        """Send system start alert"""
        self.create_alert(
            AlertType.SYSTEM_START,
            "System Started",
            "Polymarket Arbitrage Bot has started",
            AlertSeverity.INFO,
        )

    def send_system_stop_alert(self, reason: str = ""):
        """Send system stop alert"""
        message = "Polymarket Arbitrage Bot has stopped"
        if reason:
            message += f"\nReason: {reason}"

        self.create_alert(
            AlertType.SYSTEM_STOP,
            "System Stopped",
            message,
            AlertSeverity.INFO,
        )

    def send_error_alert(self, error: str, context: str = ""):
        """Send error alert"""
        title = "System Error"
        message = f"Error: {error}"
        if context:
            message += f"\nContext: {context}"

        self.create_alert(
            AlertType.SYSTEM_ERROR,
            title,
            message,
            AlertSeverity.ERROR,
        )


# Global alert manager instance
alert_manager = AlertManager()
