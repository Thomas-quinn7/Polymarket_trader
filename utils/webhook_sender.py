"""
Webhook Sender Module
Handles webhook notifications for alerts (Slack, Discord, etc.)
"""

import json
import os
import requests
from typing import Dict, Optional
from datetime import datetime

from utils.logger import logger


class WebhookSender:
    """
    Webhook notification sender

    Features:
    - Generic webhook support for any service
    - Customizable message formatting
    - Error handling and retry logic
    - Support for Slack and Discord formats
    - Discord user mentions support
    """

    def __init__(self, webhook_url: str, discord_username: Optional[str] = None):
        from config.polymarket_config import config

        self.webhook_url = webhook_url
        self.timeout = 10
        self.retry_count = 3
        self.enabled = bool(webhook_url)

        # Discord-specific settings
        self.discord_username = discord_username or config.DISCORD_MENTION_USER
        self.mention_user = config.DISCORD_MENTION_USER is not None

        if not self.enabled:
            logger.warning("Webhook sender not configured")
        else:
            logger.info("Webhook sender initialized")
            if "discord.com" in webhook_url and self.discord_username:
                logger.info(
                    f"Discord mentions configured for user: @{self.discord_username}"
                )

    def send_webhook(self, payload: Dict) -> bool:
        """
        Send a webhook notification

        Args:
            payload: Dictionary containing webhook payload

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        for attempt in range(self.retry_count):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code in [200, 201, 204]:
                    logger.debug(f"Webhook sent successfully: {response.status_code}")
                    return True
                else:
                    logger.warning(
                        f"Webhook returned status {response.status_code}: {response.text}"
                    )

            except requests.exceptions.Timeout:
                logger.error(
                    f"Webhook timeout (attempt {attempt + 1}/{self.retry_count})"
                )
            except requests.exceptions.ConnectionError:
                logger.error(
                    f"Webhook connection error (attempt {attempt + 1}/{self.retry_count})"
                )
            except requests.exceptions.RequestException as e:
                logger.error(
                    f"Webhook request error (attempt {attempt + 1}/{self.retry_count}): {e}"
                )

            if attempt < self.retry_count - 1:
                import time

                time.sleep(2**attempt)  # Exponential backoff

        logger.error("Failed to send webhook after all retries")
        return False

    def send_alert(self, alert_data: Dict) -> bool:
        """
        Send an alert via webhook

        Args:
            alert_data: Dictionary containing alert information

        Returns:
            True if sent successfully
        """
        # Detect webhook type and format appropriately
        if "slack.com" in self.webhook_url:
            payload = self._format_slack(alert_data)
        elif "discord.com" in self.webhook_url:
            payload = self._format_discord(alert_data)
        else:
            # Generic format
            payload = self._format_generic(alert_data)

        return self.send_webhook(payload)

    def _get_discord_mention(self) -> str:
        """Get Discord mention string"""
        if self.mention_user and self.discord_username:
            # Format as @username for Discord
            return f"@{self.discord_username}"
        return ""

    def _format_generic(self, alert_data: Dict) -> Dict:
        """Format alert for generic webhook"""
        alert_type = alert_data.get("alert_type", "ALERT")
        severity = alert_data.get("severity", "INFO")
        title = alert_data.get("title", "Trading Alert")
        message = alert_data.get("message", "")
        data = alert_data.get("data")

        payload = {
            "alert_type": alert_type,
            "severity": severity,
            "title": title,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "source": "Polymarket Arbitrage Bot",
        }

        if data:
            try:
                parsed_data = json.loads(data) if isinstance(data, str) else data
                payload["data"] = parsed_data
            except Exception:
                pass

        return payload

    def _format_slack(self, alert_data: Dict) -> Dict:
        """Format alert for Slack webhook"""
        alert_type = alert_data.get("alert_type", "ALERT")
        severity = alert_data.get("severity", "INFO")
        title = alert_data.get("title", "Trading Alert")
        message = alert_data.get("message", "")
        data = alert_data.get("data")

        # Color based on severity
        color_map = {
            "INFO": "#2196F3",
            "WARNING": "#FF9800",
            "ERROR": "#f44336",
            "CRITICAL": "#B71C1C",
        }
        color = color_map.get(severity, "#2196F3")

        # Build message
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{severity} - {title}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Alert Type:*\n{alert_type}"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Timestamp:*\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    },
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Message:*\n{message}"},
            },
        ]

        # Add additional data if available
        if data:
            try:
                parsed_data = json.loads(data) if isinstance(data, str) else data
                fields = []
                for key, value in parsed_data.items():
                    fields.append({"type": "mrkdwn", "text": f"*{key}:*\n{value}"})

                if fields:
                    blocks.append(
                        {
                            "type": "section",
                            "fields": fields[:5],  # Limit to 5 fields
                        }
                    )
            except Exception:
                pass

        return {
            "attachments": [
                {
                    "color": color,
                    "blocks": blocks,
                    "footer": "Polymarket Arbitrage Bot",
                    "ts": int(datetime.now().timestamp()),
                }
            ]
        }

    def _format_discord(self, alert_data: Dict) -> Dict:
        """Format alert for Discord webhook"""
        alert_type = alert_data.get("alert_type", "ALERT")
        severity = alert_data.get("severity", "INFO")
        title = alert_data.get("title", "Trading Alert")
        message = alert_data.get("message", "")
        data = alert_data.get("data")

        # Color based on severity
        color_map = {
            "INFO": 0x2196F3,
            "WARNING": 0xFF9800,
            "ERROR": 0xF44336,
            "CRITICAL": 0xB71C1C,
        }
        color = color_map.get(severity, 0x2196F3)

        # Get Discord mention - mention for all important alerts
        mention = self._get_discord_mention()
        should_mention = severity in ["ERROR", "CRITICAL"] or alert_type in [
            "stop_loss_triggered",
            "circuit_breaker",
            "daily_loss_limit",
            "position_loss",
        ]

        # Build title with mention
        if should_mention and mention:
            display_title = f"{mention} **[{severity}] {title}**"
        else:
            display_title = f"[{severity}] {title}"

        # Build embed
        embed = {
            "title": f"[{severity}] {title}",  # Clean title without mention
            "color": color,
            "timestamp": datetime.now().isoformat(),
            "fields": [
                {"name": "Alert Type", "value": alert_type, "inline": True},
                {"name": "Severity", "value": severity, "inline": True},
            ],
        }

        # Add message with mention for important alerts
        if message:
            embed["description"] = (
                f"{mention}\n{message}" if should_mention else message
            )

        # Add additional data if available
        if data:
            try:
                parsed_data = json.loads(data) if isinstance(data, str) else data
                for key, value in parsed_data.items():
                    if len(embed["fields"]) < 25:  # Discord limit
                        embed["fields"].append(
                            {"name": key, "value": str(value), "inline": True}
                        )
            except Exception:
                pass

        # Add footer
        if should_mention and mention:
            embed["footer"] = {
                "text": f"{mention} - Action Required!",
            }
        else:
            embed["footer"] = {"text": "Polymarket Arbitrage Bot"}

        return {
            "content": display_title
            if should_mention
            else None,  # Mention in content for visibility
            "embeds": [embed],
            "allowed_mentions": {
                "parse": ["users"],
                "users": [self.discord_username] if self.discord_username else [],
            },
        }

    def test_connection(self) -> bool:
        """Test webhook connection"""
        if not self.enabled:
            return False

        test_payload = {
            "test": True,
            "message": "Test webhook connection",
            "timestamp": datetime.now().isoformat(),
        }

        return self.send_webhook(test_payload)
