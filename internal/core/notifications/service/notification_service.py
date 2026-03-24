"""
Notification Service - Main business logic for alert management.
Routes alerts to appropriate channels with rate limiting.
"""

import time
from typing import List, Optional

from internal.core.notifications.domain import Alert, AlertSeverity, AlertType, NotificationChannel, NotificationChannelError, RateLimitError


class NotificationService:
    """
    Service for managing notifications across multiple channels.
    Handles routing, rate limiting, and error handling.
    """

    def __init__(self, channels: List[NotificationChannel], cooldown_seconds: int = 300):
        """
        Initialize notification service.

        Args:
            channels: List of notification channel instances
            cooldown_seconds: Minimum time between same-type notifications (default: 5 minutes)
        """
        self.channels = channels
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[AlertType, float] = {}
        self._channel_errors: dict[str, int] = {}

    async def notify(self, alert: Alert) -> dict[str, bool]:
        """
        Send alert through all configured channels.

        Args:
            alert: The alert to send

        Returns:
            Dictionary mapping channel class names to send success status

        Raises:
            NotificationChannelError: If all channels fail to send
        """
        # Check rate limiting
        if self._check_rate_limit(alert.type):
            raise RateLimitError(retry_after=self.cooldown_seconds)

        results = {}

        for channel in self.channels:
            try:
                success = await channel.send(alert)
                results[channel.__class__.__name__] = success

                if success:
                    self._last_sent[alert.type] = time.time()
                else:
                    results[channel.__class__.__name__] = False

            except Exception as e:
                # Log the error but continue with other channels
                logger = __import__("pkg.logger").pkg.logger
                logger.warning(
                    f"notification_failed",
                    channel=channel.__class__.__name__,
                    alert_type=alert.type.value,
                    error=str(e),
                )
                results[channel.__class__.__name__] = False

        return results

    def _check_rate_limit(self, alert_type: AlertType) -> bool:
        """
        Check if notification type has been sent recently.

        Args:
            alert_type: Type of notification to check

        Returns:
            True if rate limited, False if allowed
        """
        if alert_type not in self._last_sent:
            return False

        last_sent = self._last_sent[alert_type]
        elapsed = (time.time() - last_sent) if last_sent > 0 else float('inf')

        return elapsed < self.cooldown_seconds

    async def test_all_channels(self) -> dict[str, bool]:
        """
        Test all configured notification channels.

        Returns:
            Dictionary mapping channel names to connection status
        """
        results = {}

        for channel in self.channels:
            try:
                is_connected = await channel.test_connection()
                results[channel.__class__.__name__] = is_connected
            except Exception as e:
                logger = __import__("pkg.logger").pkg.logger
                logger.warning(
                    f"channel_test_failed",
                    channel=channel.__class__.__name__,
                    error=str(e),
                )
                results[channel.__class__.__name__] = False

        return results

    def add_channel(self, channel: NotificationChannel) -> None:
        """
        Add a new notification channel.

        Args:
            channel: Channel instance to add
        """
        self.channels.append(channel)

    def remove_channel(self, channel_class: type) -> None:
        """
        Remove a notification channel by its class.

        Args:
            channel_class: Class of channel to remove
        """
        self.channels = [c for c in self.channels if not isinstance(c, channel_class)]

    @staticmethod
    def create_discord_channel(webhook_url: str, mention_user_id: str = "") -> "DiscordChannel":
        """
        Create a Discord notification channel.

        Args:
            webhook_url: Discord webhook URL
            mention_user_id: Optional user ID to mention

        Returns:
            DiscordChannel instance
        """
        return DiscordChannel(webhook_url=webhook_url, mention_user_id=mention_user_id)

    @staticmethod
    def create_email_channel(smtp_server: str, smtp_port: int, username: str, password: str, from_email: str, to_email: str) -> "EmailChannel":
        """
        Create an email notification channel.

        Args:
            smtp_server: SMTP server address
            smtp_port: SMTP port
            username: SMTP username
            password: SMTP password
            from_email: From email address
            to_email: To email address

        Returns:
            EmailChannel instance
        """
        return EmailChannel(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            username=username,
            password=password,
            from_email=from_email,
            to_email=to_email,
        )


from pkg.logger import get_logger

logger = get_logger(__name__)


class DiscordChannel(NotificationChannel):
    """Discord webhook notification channel."""

    def __init__(self, webhook_url: str, mention_user_id: str = ""):
        """
        Initialize Discord channel.

        Args:
            webhook_url: Discord webhook URL
            mention_user_id: User ID to mention in messages (numeric)
        """
        self.webhook_url = webhook_url
        self.mention_user_id = mention_user_id
        self._cooldown_seconds = 60  # 1 minute cooldown between Discord sends

    async def send(self, alert: Alert) -> bool:
        """
        Send alert via Discord webhook.

        Args:
            alert: Alert to send

        Returns:
            True if successful, False if failed
        """
        try:
            import aiohttp

            # Build Discord embed
            embed = {
                "title": alert.display_title,
                "description": alert.message,
                "color": self._severity_to_color(alert.severity),
                "timestamp": alert.timestamp,
            }

            # Add metadata if available
            if alert.metadata:
                fields = []
                for key, value in alert.metadata.items():
                    if isinstance(value, (str, int, float)):
                        fields.append({"name": key, "value": str(value), "inline": True})
                if fields:
                    embed["fields"] = fields

            # Build payload
            payload = {
                "embeds": [embed],
            }

            # Add mention if configured
            if self.mention_user_id:
                payload["allowed_mentions"] = {
                    "users": [int(self.mention_user_id)],
                }

            # Send to Discord webhook
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status in (200, 204):
                        return True
                    error_text = await response.text()
                    raise NotificationChannelError(
                        f"Discord webhook failed with status {response.status}: {error_text}"
                    )

        except NotificationChannelError:
            raise
        except Exception as e:
            raise NotificationChannelError(f"Failed to send Discord notification: {str(e)}")

    async def test_connection(self) -> bool:
        """Test Discord webhook connection."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(self.webhook_url) as response:
                    return response.status in (200, 204)
        except Exception as e:
            raise NotificationChannelError(f"Discord webhook test failed: {str(e)}")

    @staticmethod
    def _severity_to_color(severity: AlertSeverity) -> int:
        """Convert severity to Discord color code."""
        colors = {
            AlertSeverity.INFO: 3447003,      # Blue
            AlertSeverity.WARNING: 15844367,  # Yellow
            AlertSeverity.ERROR: 15158332,    # Red
            AlertSeverity.CRITICAL: 13900000, # Dark Red
        }
        return colors.get(severity, 3447003)


class EmailChannel(NotificationChannel):
    """Email notification channel using SMTP."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        to_email: str,
    ):
        """
        Initialize email channel.

        Args:
            smtp_server: SMTP server address
            smtp_port: SMTP port
            username: SMTP username
            password: SMTP password
            from_email: From email address
            to_email: To email address
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_email = to_email
        self._cooldown_seconds = 300  # 5 minute cooldown between emails

    async def send(self, alert: Alert) -> bool:
        """
        Send alert via email.

        Args:
            alert: Alert to send

        Returns:
            True if successful, False if failed
        """
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            # Build email content
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"{alert.severity.value}: {alert.title}"
            msg["From"] = self.from_email
            msg["To"] = self.to_email

            # Create plain text version
            text_content = f"{alert.display_title}\n\n{alert.message}"
            if alert.metadata:
                text_content += "\n\nDetails:"
                for key, value in alert.metadata.items():
                    text_content += f"\n{key}: {value}"

            # Create HTML version
            html_content = f"""
            <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; padding: 20px; }}
                        .severity {{
                            padding: 10px;
                            border-radius: 5px;
                            color: white;
                            font-weight: bold;
                        }}
                        .info {{ background-color: #3498db; }}
                        .warning {{ background-color: #f1c40f; color: #333; }}
                        .error {{ background-color: #e74c3c; }}
                        .critical {{ background-color: #c0392b; }}
                    </style>
                </head>
                <body>
                    <div class="severity {alert.severity.value.lower()}">
                        {alert.display_title}
                    </div>
                    <div style="margin-top: 10px;">
                        {alert.message}
                    </div>
                    {alert.metadata and '<hr style="margin-top: 10px;"><h3>Details:</h3>' or ''}
                    {alert.metadata and ''.join([
                        f'<p><strong>{key}:</strong> {value}</p>'
                        for key, value in alert.metadata.items()
                    ]) or ''}
                </body>
            </html>
            """

            # Attach both versions
            part1 = MIMEText(text_content, "plain")
            part2 = MIMEText(html_content, "html")
            msg.attach(part1)
            msg.attach(part2)

            # Send email — port 465 uses implicit SSL; port 587 uses STARTTLS
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
                    server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.username, self.password)
                    server.send_message(msg)

            return True

        except Exception as e:
            raise NotificationChannelError(f"Failed to send email notification: {str(e)}")

    async def test_connection(self) -> bool:
        """Test email connection."""
        try:
            import smtplib

            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
                    server.noop()
            else:
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls()
                    server.noop()
            return True
        except Exception as e:
            raise NotificationChannelError(f"Email connection test failed: {str(e)}")
