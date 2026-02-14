"""
Email Sender Module
Handles email notifications for alerts
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional
import os
from datetime import datetime

from utils.logger import logger


class EmailSender:
    """
    Email notification sender

    Features:
    - SMTP authentication
    - HTML and plain text emails
    - Configurable from/to addresses
    - Error handling and retry logic
    """

    def __init__(self):
        from config.polymarket_config import config

        self.smtp_server = config.SMTP_SERVER
        self.smtp_port = config.SMTP_PORT
        self.smtp_username = config.SMTP_USERNAME
        self.smtp_password = config.SMTP_PASSWORD
        self.from_email = config.EMAIL_FROM
        self.to_email = config.EMAIL_TO

        self.enabled = self._validate_configuration()

        if not self.enabled:
            logger.warning("Email sender not fully configured")
        else:
            logger.info("Email sender initialized")

    def _validate_configuration(self) -> bool:
        """Validate email configuration"""
        if not self.smtp_username or not self.smtp_password:
            logger.warning("Email credentials not configured")
            return False

        if not self.to_email:
            logger.warning("No recipient email configured")
            return False

        return True

    def send_email(
        self, subject: str, body: str, html_body: Optional[str] = None
    ) -> bool:
        """
        Send an email

        Args:
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            logger.warning("Email sending disabled - not configured")
            return False

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = self.to_email
            msg["Subject"] = f"[Polymarket Arbitrage Bot] {subject}"

            # Add plain text part
            msg.attach(MIMEText(body, "plain"))

            # Add HTML part if provided
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            # Connect to SMTP server
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("Email authentication failed - check SMTP credentials")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False

    def send_alert(self, alert_data: Dict) -> bool:
        """
        Send an alert notification

        Args:
            alert_data: Dictionary containing alert information

        Returns:
            True if sent successfully
        """
        alert_type = alert_data.get("alert_type", "ALERT")
        severity = alert_data.get("severity", "INFO")
        title = alert_data.get("title", "Trading Alert")
        message = alert_data.get("message", "")
        data = alert_data.get("data")

        # Create subject
        severity_emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🚨"}
        subject = f"{severity_emoji.get(severity, '⚠️')} [{severity}] {title}"

        # Create email body
        body = f"""
Polymarket Arbitrage Bot Alert
{'=' * 50}

Alert Type: {alert_type}
Severity: {severity}
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Title: {title}

{message}
"""

        # Add additional data if available
        if data:
            try:
                import json

                parsed_data = json.loads(data) if isinstance(data, str) else data
                body += "\nAdditional Information:\n"
                for key, value in parsed_data.items():
                    body += f"  {key}: {value}\n"
            except Exception as e:
                logger.debug(f"Could not parse alert data: {e}")

        # Create HTML version
        html_body = f"""
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
        .header {{ background-color: #f4f4f4; padding: 20px; }}
        .content {{ padding: 20px; }}
        .alert-type {{ font-weight: bold; color: #333; }}
        .severity-INFO {{ color: #2196F3; }}
        .severity-WARNING {{ color: #FF9800; }}
        .severity-ERROR {{ color: #f44336; }}
        .severity-CRITICAL {{ color: #B71C1C; }}
        .message {{ background-color: #f9f9f9; padding: 15px; margin: 10px 0; border-left: 3px solid #ccc; }}
        .footer {{ background-color: #f4f4f4; padding: 10px; text-align: center; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>Polymarket Arbitrage Bot Alert</h2>
    </div>
    <div class="content">
        <p><span class="alert-type">Alert Type:</span> {alert_type}</p>
        <p><span class="alert-type">Severity:</span> <span class="severity-{severity}">{severity}</span></p>
        <p><span class="alert-type">Timestamp:</span> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <h3>{title}</h3>
        <div class="message">{message.replace(chr(10), "<br>")}</div>
"""

        if data:
            try:
                import json

                parsed_data = json.loads(data) if isinstance(data, str) else data
                html_body += "<h4>Additional Information:</h4><ul>"
                for key, value in parsed_data.items():
                    html_body += f"<li><strong>{key}:</strong> {value}</li>"
                html_body += "</ul>"
            except Exception:
                pass

        html_body += """
    </div>
    <div class="footer">
        <p>This is an automated alert from your Polymarket Arbitrage Bot.</p>
        <p>Please do not reply to this email.</p>
    </div>
</body>
</html>
"""

        return self.send_email(subject, body.strip(), html_body)

    def test_connection(self) -> bool:
        """Test SMTP connection"""
        if not self.enabled:
            return False

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                if self.smtp_username and self.smtp_password:
                    server.login(self.smtp_username, self.smtp_password)
            return True
        except Exception as e:
            logger.error(f"SMTP connection test failed: {e}")
            return False

    def send_test_email(self) -> bool:
        """Send a test email to verify configuration"""
        if not self.enabled:
            logger.warning("Email sender not configured")
            return False

        subject = "🧪 Polymarket Arbitrage Bot - Test Email"
        body = f"""
This is a test email from your Polymarket Arbitrage Bot.

Configuration:
- SMTP Server: {self.smtp_server}:{self.smtp_port}
- Username: {self.smtp_username}
- From: {self.from_email}
- To: {self.to_email}

If you received this email, your email notifications are working correctly!

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        return self.send_email(subject, body)
