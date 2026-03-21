"""
Setup Validation Script
Validates all configurations, tests connections, and ensures everything is working
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_header(text):
    """Print formatted header"""
    print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{BLUE}{text:^70}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")


def print_success(text):
    """Print success message"""
    print(f"{GREEN}✅ {text}{RESET}")


def print_error(text):
    """Print error message"""
    print(f"{RED}❌ {text}{RESET}")


def print_warning(text):
    """Print warning message"""
    print(f"{YELLOW}⚠️  {text}{RESET}")


def print_info(text):
    """Print info message"""
    print(f"{BLUE}ℹ️  {text}{RESET}")


def check_file_exists(filepath, description):
    """Check if a file exists"""
    if Path(filepath).exists():
        print_success(f"{description}: {filepath}")
        return True
    else:
        print_error(f"{description} not found: {filepath}")
        return False


def check_env_var(var_name, description, required=True):
    """Check if environment variable is set"""
    value = os.getenv(var_name)
    if value and value != f"your_{var_name.lower()}_here" and value != "":
        print_success(f"{description}: Set")
        return True
    elif required:
        print_error(f"{description}: Not set in .env")
        print(f"   Add to .env: {var_name}=your_value_here")
        return False
    else:
        print_warning(f"{description}: Not set (optional)")
        return True


def check_import(module_name, package_name):
    """Check if a Python module can be imported"""
    try:
        __import__(module_name)
        print_success(f"{package_name}: Installed")
        return True
    except ImportError:
        print_error(f"{package_name}: Not installed")
        print(f"   Run: pip install {package_name}")
        return False


def check_api_connection(url, description, timeout=5):
    """Check if an API endpoint is accessible"""
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code in [200, 201, 204]:
            print_success(f"{description}: Accessible ({response.status_code})")
            return True
        else:
            print_warning(f"{description}: Accessible but returned {response.status_code}")
            return True
    except requests.exceptions.Timeout:
        print_error(f"{description}: Connection timeout")
        return False
    except requests.exceptions.ConnectionError:
        print_error(f"{description}: Connection error")
        return False
    except Exception as e:
        print_error(f"{description}: {str(e)}")
        return False


def check_smtp_connection(smtp_server, smtp_port, username, password):
    """Check SMTP email connection"""
    try:
        import smtplib

        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
        print_success("SMTP Email: Connection successful")
        return True
    except smtplib.SMTPAuthenticationError:
        print_error("SMTP Email: Authentication failed (check username/password)")
        return False
    except Exception as e:
        print_error(f"SMTP Email: {str(e)}")
        return False


def check_discord_webhook(webhook_url, discord_username):
    """Check Discord webhook connection"""
    try:
        if not webhook_url or webhook_url == "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN":
            print_warning("Discord Webhook: Not configured")
            return True

        test_payload = {
            "test": True,
            "message": "Setup validation test",
            "timestamp": "2024-01-01T00:00:00Z",
        }

        response = requests.post(webhook_url, json=test_payload, timeout=10)

        if response.status_code in [200, 201, 204]:
            print_success(f"Discord Webhook: Working (mentions @{discord_username or 'none'})")
            return True
        else:
            print_warning(f"Discord Webhook: Returned {response.status_code}")
            return True
    except Exception as e:
        print_warning(f"Discord Webhook: {str(e)}")
        return True


def validate_polymarket_credentials():
    """Validate Polymarket API credentials"""
    print_header("Polymarket Configuration")

    # Check environment variables
    api_key_ok = check_env_var("POLYMARKET_PRIVATE_KEY", "Polymarket Private Key")
    funder_ok = check_env_var("POLYMARKET_FUNDER_ADDRESS", "Polymarket Funder Address")

    # Check if we can import the client
    client_ok = check_import("py_clob_client.client", "py-clob-client")

    return api_key_ok and funder_ok and client_ok


def validate_builder_credentials():
    """Validate Builder credentials"""
    print_header("Builder Configuration (Optional)")

    builder_enabled = os.getenv("BUILDER_ENABLED", "False").lower() == "true"

    if not builder_enabled:
        print_warning("Builder mode disabled (will use 200 req/day)")
        return True

    print_info("Builder mode enabled (will use 3000 req/day)")

    # Check builder credentials
    api_key_ok = check_env_var("BUILDER_API_KEY", "Builder API Key", required=False)
    secret_ok = check_env_var("BUILDER_SECRET", "Builder Secret", required=False)
    passphrase_ok = check_env_var("BUILDER_PASSPHRASE", "Builder Passphrase", required=False)

    # Check if builder SDK is installed
    sdk_ok = check_import("py_builder_signing_sdk", "py-builder-signing-sdk")

    if api_key_ok and secret_ok and passphrase_ok and sdk_ok:
        print_success("All builder credentials configured")
    else:
        print_warning("Some builder credentials missing (will fall back to unverified mode)")

    return True  # Builder is optional


def validate_email_configuration():
    """Validate email notification configuration"""
    print_header("Email Configuration")

    enabled = os.getenv("ENABLE_EMAIL_ALERTS", "False").lower() == "true"

    if not enabled:
        print_warning("Email alerts disabled")
        return True

    print_info("Email alerts enabled")

    # Check configuration
    smtp_server = os.getenv("SMTP_SERVER", "")
    smtp_port = os.getenv("SMTP_PORT", "587")
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    email_to = os.getenv("ALERT_EMAIL_TO", "")

    if not smtp_server or smtp_server == "smtp.gmail.com":
        print_warning("Using default SMTP server (configure your own)")

    check_env_var("SMTP_USERNAME", "SMTP Username", required=enabled)
    check_env_var("SMTP_PASSWORD", "SMTP Password", required=enabled)
    check_env_var("ALERT_EMAIL_TO", "Alert Email", required=enabled)

    # Test connection if configured
    if enabled and smtp_server and username and password:
        check_smtp_connection(smtp_server, int(smtp_port), username, password)

    return True


def validate_discord_configuration():
    """Validate Discord webhook configuration"""
    print_header("Discord Configuration")

    enabled = os.getenv("ENABLE_DISCORD_ALERTS", "False").lower() == "true"

    if not enabled:
        print_warning("Discord alerts disabled")
        return True

    print_info("Discord alerts enabled")

    # Check configuration
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    discord_username = os.getenv("DISCORD_MENTION_USER", "")

    if not webhook_url or "YOUR_WEBHOOK" in webhook_url:
        print_warning("Discord webhook not configured (skip test)")

    if not discord_username or "your_discord_username" in discord_username:
        print_warning("Discord mention user not set")

    # Test webhook
    if enabled:
        check_discord_webhook(webhook_url, discord_username)

    return True


def validate_paper_trading():
    """Validate paper trading configuration"""
    print_header("Paper Trading Configuration")

    # Check paper trading is enabled
    paper_enabled = os.getenv("PAPER_TRADING_ENABLED", "True").lower() == "true"

    if paper_enabled:
        print_success("Paper Trading: Enabled")
    else:
        print_error("Paper Trading: Disabled!")
        print_error("   Add to .env: PAPER_TRADING_ENABLED=True")
        return False

    # Check fake currency balance
    balance = os.getenv("FAKE_CURRENCY_BALANCE", "10000.00")
    print_success(f"Fake Currency Balance: ${balance}")

    # Check PAPER_TRADING_ONLY flag
    paper_only = os.getenv("PAPER_TRADING_ONLY", "True").lower() == "true"

    if paper_only:
        print_success("Paper Trading Only Mode: Enabled (Safety on)")
    else:
        print_warning("Paper Trading Only Mode: Disabled (can trade real money)")

    return True


def validate_strategy_configuration():
    """Validate strategy configuration"""
    print_header("Strategy Configuration")

    # Check execution timing
    timing = os.getenv("EXECUTE_BEFORE_CLOSE_SECONDS", "2")
    print_success(f"Execution Timing: {timing} seconds before close")

    # Check price thresholds
    min_price = os.getenv("MIN_PRICE_THRESHOLD", "0.985")
    max_price = os.getenv("MAX_PRICE_THRESHOLD", "1.00")
    print_success(f"Price Threshold: ${min_price} - ${max_price}")

    # Check position limits
    max_positions = os.getenv("MAX_POSITIONS", "5")
    print_success(f"Max Positions: {max_positions}")

    # Check capital split
    capital_split = os.getenv("CAPITAL_SPLIT_PERCENT", "0.2")
    print_success(f"Capital Split: {float(capital_split) * 100:.0f}% per position")

    return True


def validate_project_structure():
    """Validate project structure"""
    print_header("Project Structure")

    all_ok = True

    # Check key files and directories
    required_items = [
        ("main.py", "Main bot file"),
        ("config/polymarket_config.py", "Configuration file"),
        ("data/polymarket_client.py", "Polymarket client"),
        ("strategies/settlement_arbitrage.py", "Strategy file"),
        ("portfolio/fake_currency_tracker.py", "Portfolio tracker"),
        ("execution/order_executor.py", "Order executor"),
        ("utils/logger.py", "Logger"),
        ("utils/alerts.py", "Alert manager"),
        ("dashboard/api.py", "Dashboard API"),
        (".env", "Environment file"),
    ]

    for filepath, description in required_items:
        if not check_file_exists(filepath, description):
            all_ok = False

    # Check directories
    required_dirs = [
        ("logs", "Logs directory"),
        ("dashboard/static", "Dashboard static files"),
    ]

    for dirname, description in required_dirs:
        if not Path(dirname).exists():
            Path(dirname).mkdir(parents=True, exist_ok=True)
            print_success(f"{description}: Created")

    return all_ok


def validate_dependencies():
    """Validate all Python dependencies"""
    print_header("Python Dependencies")

    # Core dependencies
    deps = [
        ("dotenv", "python-dotenv"),
        ("requests", "requests"),
        ("py_clob_client.client", "py-clob-client"),
        ("colorlog", "colorlog"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
        ("sqlalchemy", "sqlalchemy"),
    ]

    all_ok = True
    for module, package in deps:
        if not check_import(module, package):
            all_ok = False

    # Check for builder SDK (optional)
    check_import("py_builder_signing_sdk", "py-builder-signing-sdk")

    return all_ok


def generate_setup_report(results):
    """Generate setup report"""
    print_header("Setup Validation Report")

    total_checks = len(results)
    passed_checks = sum(1 for r in results.values() if r)

    print(f"\n{BOLD}Results:{RESET}")
    print(f"  Total Checks: {total_checks}")
    print(f"  Passed: {GREEN}{passed_checks}{RESET}")
    print(f"  Failed: {RED}{total_checks - passed_checks}{RESET}")
    print(f"  Success Rate: {GREEN}{(passed_checks / total_checks * 100):.0f}%{RESET}\n")

    if passed_checks == total_checks:
        print_success("All checks passed! Your bot is ready to run. 🎉")
        print("\nTo start the bot:")
        print(f"  {BLUE}python main.py{RESET}\n")
        print("To access the dashboard:")
        print(f"  {BLUE}http://localhost:8080{RESET}\n")
        return 0
    else:
        print_error(f"{total_checks - passed_checks} check(s) failed. Please fix the issues above.")
        print("\nTo re-run validation:")
        print(f"  {BLUE}python validate_setup.py{RESET}\n")
        return 1


def main():
    """Main validation function"""
    print_header("Polymarket Arbitrage Bot - Setup Validation")
    print("This script will validate your configuration and test connections.\n")

    # Track results
    results = {}

    # Validate project structure
    results["Project Structure"] = validate_project_structure()

    # Validate dependencies
    results["Dependencies"] = validate_dependencies()

    # Validate Polymarket credentials
    results["Polymarket"] = validate_polymarket_credentials()

    # Validate builder credentials
    results["Builder"] = validate_builder_credentials()

    # Validate paper trading
    results["Paper Trading"] = validate_paper_trading()

    # Validate strategy
    results["Strategy"] = validate_strategy_configuration()

    # Validate email
    results["Email"] = validate_email_configuration()

    # Validate Discord
    results["Discord"] = validate_discord_configuration()

    # Generate report
    return generate_setup_report(results)


if __name__ == "__main__":
    sys.exit(main())
