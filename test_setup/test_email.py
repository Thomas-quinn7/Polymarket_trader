"""
Test Email Configuration
Validates email SMTP configuration and sends a test email
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def test_smtp_connection():
    """Test SMTP connection"""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    email_from = os.getenv("ALERT_EMAIL_FROM", "noreply@example.com")
    email_to = os.getenv("ALERT_EMAIL_TO", "")

    print("=" * 70)
    print("Email Configuration Test")
    print("=" * 70)

    # Check configuration
    print("\n📋 Configuration:")
    print(f"   SMTP Server: {smtp_server}:{smtp_port}")
    print(f"   Username: {smtp_username}")
    print(f"   From: {email_from}")
    print(f"   To: {email_to}")

    if not smtp_username:
        print("\n❌ Error: SMTP_USERNAME not configured")
        return False

    if not smtp_password:
        print("\n❌ Error: SMTP_PASSWORD not configured")
        return False

    # Test connection
    print("\n🔗 Testing SMTP connection...")
    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
        print("✅ SMTP connection successful!")
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Authentication failed: {e}")
        print("\n💡 Common issues:")
        print("   - For Gmail: Use App Password, not your regular password")
        print("     Get one at: https://myaccount.google.com/apppasswords")
        print("   - Check email and password are correct")
        print("   - Check if 2FA is enabled (may require App Password)")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

    # Send test email
    print("\n📧 Sending test email...")
    try:
        # Create message
        msg = MIMEMultipart("alternative")
        msg["From"] = email_from
        msg["To"] = email_to
        msg["Subject"] = "[Polymarket Bot] Test Email ✅"

        # Plain text body
        body = """
This is a test email from your Polymarket Arbitrage Bot.

If you received this email, your email notifications are configured correctly! 🎉

Configuration:
- SMTP Server: {smtp_server}:{smtp_port}
- Username: {smtp_username}
- From: {email_from}
- To: {email_to}

You can now:
- Receive trade execution alerts
- Get win/loss notifications
- Get system status updates
- Get error alerts

Time: {timestamp}
        """.format(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            email_from=email_from,
            email_to=email_to,
            timestamp="2024-01-01T00:00:00Z"
        )

        msg.attach(MIMEText(body, "plain"))

        # Send email
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        print("✅ Test email sent successfully!")
        print(f"\n📧 Check your inbox: {email_to}")
        print("\n💡 Note: If email doesn't arrive, check spam folder.")

        return True

    except Exception as e:
        print(f"❌ Failed to send test email: {e}")
        return False


def main():
    """Main function"""
    success = test_smtp_connection()

    if success:
        print("\n" + "=" * 70)
        print("Email configuration is working! 🎉")
        print("=" * 70)
        print("\n📚 Next steps:")
        print("   1. Run: python validate_setup.py")
        print("   2. Start the bot: python main.py")
        print("   3. Make a trade to test email alerts")
        return 0
    else:
        print("\n" + "=" * 70)
        print("Please fix the issues above before continuing")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
