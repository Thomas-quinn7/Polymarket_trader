"""
Quick Start Script
Simplified setup for Polymarket Arbitrage Bot
"""

import os
import sys
import subprocess
from pathlib import Path


def print_step(step_num, title):
    """Print formatted step"""
    print(f"\n{'=' * 70}")
    print(f"Step {step_num}: {title}")
    print(f"{'=' * 70}\n")


def run_command(command, description):
    """Run a shell command"""
    print(f"📋 {description}...")
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✅ {description} - Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - Failed")
        print(f"   Error: {e.stderr}")
        return False


def main():
    """Main quick start function"""
    print("\n" + "=" * 70)
    print("Polymarket Arbitrage Bot - Quick Start")
    print("=" * 70)

    # Step 1: Create virtual environment
    print_step(1, "Create Virtual Environment")
    if not Path("venv").exists():
        run_command(
            sys.executable + " -m venv venv",
            "Creating virtual environment"
        )
    else:
        print("✅ Virtual environment already exists")

    # Step 2: Activate virtual environment
    print_step(2, "Activate Virtual Environment")
    print("\n📌 Activate virtual environment:")
    if os.name == 'nt':  # Windows
        print("   venv\\Scripts\\activate")
    else:  # Unix/Linux/Mac
        print("   source venv/bin/activate")

    # Step 3: Install dependencies
    print_step(3, "Install Dependencies")
    run_command(
        "pip install -r requirements.txt",
        "Installing Python packages"
    )

    # Step 4: Create .env file
    print_step(4, "Configure Environment Variables")
    if not Path(".env").exists():
        run_command(
            "cp .env.example .env",
            "Creating .env from template"
        )
        print("\n📝 IMPORTANT: Edit .env file with your credentials:")
        print("   1. Add your Polymarket private key")
        print("   2. (Optional) Add builder credentials for 3000 req/day")
        print("   3. (Optional) Configure email and Discord alerts")
        print("   4. Keep PAPER_TRADING_ONLY=True for safety")
    else:
        print("✅ .env file already exists")

    # Step 5: Run setup validation
    print_step(5, "Validate Setup")
    print("\n📋 Run validation script to check everything is working:")
    print("   python validate_setup.py")

    # Step 6: Start the bot
    print_step(6, "Start the Bot")
    print("\n🚀 After validation, start the bot:")
    print("   python main.py")

    # Step 7: Access dashboard
    print_step(7, "Access Dashboard")
    print("\n📊 Dashboard will be available at:")
    print("   http://localhost:8080")

    # Summary
    print("\n" + "=" * 70)
    print("Quick Start Complete!")
    print("=" * 70)

    print("\n📋 Next Steps:")
    print("   1. Edit .env with your credentials")
    print("   2. Run: python validate_setup.py")
    print("   3. Fix any validation errors")
    print("   4. Run: python main.py")
    print("   5. Visit: http://localhost:8080")

    print("\n📚 Documentation:")
    print("   - README.md - Full documentation")
    print("   - BUILDER_VERIFICATION.md - Get 3000 req/day")
    print("   - .env.example - Configuration template")

    print("\n⚠️  Safety Notes:")
    print("   - PAPER_TRADING_ONLY=True ensures no real money trades")
    print("   - Test with fake currency first")
    print("   - Never share your API keys or private keys")
    print("   - Keep builder credentials secure")

    print("\n")


if __name__ == "__main__":
    main()
