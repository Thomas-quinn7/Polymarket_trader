"""
Test Discord Webhook Configuration
Validates Discord webhook and sends a test notification
"""

import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def test_discord_webhook():
    """Test Discord webhook connection"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    discord_username = os.getenv("DISCORD_MENTION_USER", "")
    enabled = os.getenv("ENABLE_DISCORD_ALERTS", "False").lower() == "true"

    print("=" * 70)
    print("Discord Configuration Test")
    print("=" * 70)

    # Check configuration
    print("\n📋 Configuration:")
    print(f"   Discord Alerts: {'Enabled' if enabled else 'Disabled'}")

    if not enabled:
        print("\n⚠️  Discord alerts are disabled in .env")
        print("   Set: ENABLE_DISCORD_ALERTS=True")
        return False

    if (
        not webhook_url
        or webhook_url == "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
    ):
        print("\n❌ Error: DISCORD_WEBHOOK_URL not configured")
        print("\n💡 How to get your webhook URL:")
        print("   1. Go to your Discord server settings")
        print("   2. Go to Integrations → Webhooks")
        print("   3. Click 'New Webhook'")
        print("   4. Copy the webhook URL")
        print("   5. Add to .env: DISCORD_WEBHOOK_URL=your_webhook_url")
        return False

    print(f"   Webhook URL: {webhook_url[:50]}...")
    # Build the mention string — use as-is if already in <@ID> format
    mention = (
        discord_username
        if discord_username.startswith("<@")
        else f"@{discord_username}" if discord_username else "everyone"
    )
    print(f"   Mention User: {mention}")

    # Test webhook
    print("\n🔗 Testing Discord webhook...")
    try:
        # Create test payload
        test_payload = {
            "content": f"{mention} **[TEST] Discord Webhook Test** ✅",
            "embeds": [
                {
                    "title": "📧 Discord Alert Test",
                    "description": "This is a test message from your Polymarket Arbitrage Bot.",
                    "color": 5763719,  # Green
                    "fields": [
                        {"name": "Status", "value": "✅ Working!", "inline": True},
                        {"name": "Mentions", "value": mention, "inline": True},
                    ],
                    "footer": {"text": "Polymarket Arbitrage Bot - Test"},
                }
            ],
            "allowed_mentions": {"parse": ["users"]},
        }

        # Send test message
        response = requests.post(webhook_url, json=test_payload, timeout=10)

        if response.status_code in [200, 201, 204]:
            print("✅ Discord webhook successful!")
            print(f"\n📱 Check your Discord server for the test message!")
            print(f"   You should see a test message with @{discord_username or 'no user'} mention")
            return True
        else:
            print(f"⚠️  Discord webhook returned {response.status_code}")
            print(f"   Response: {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("❌ Discord webhook timeout")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ Discord connection error")
        print("\n💡 Check:")
        print("   - Webhook URL is correct")
        print("   - Internet connection is working")
        print("   - Discord is accessible")
        return False
    except Exception as e:
        print(f"❌ Discord webhook error: {e}")
        return False


def main():
    """Main function"""
    success = test_discord_webhook()

    if success:
        print("\n" + "=" * 70)
        print("Discord configuration is working! 🎉")
        print("=" * 70)
        print("\n📚 Next steps:")
        print("   1. Run: python validate_setup.py")
        print("   2. Start the bot: python main.py")
        print("   3. Make a trade to test Discord alerts")
        return 0
    else:
        print("\n" + "=" * 70)
        print("Please fix the issues above before continuing")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
