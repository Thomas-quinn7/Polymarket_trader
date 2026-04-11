"""
Quick Start Script
Automated setup for the Polymarket Trading Framework using uv.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def print_step(step_num, title):
    print(f"\n{'=' * 70}")
    print(f"Step {step_num}: {title}")
    print(f"{'=' * 70}\n")


def run(command, description):
    print(f"  Running: {command}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  OK: {description}")
        return True
    else:
        print(f"  FAILED: {description}")
        if result.stderr:
            print(f"  {result.stderr.strip()}")
        return False


def check_uv():
    """Ensure uv is available."""
    if shutil.which("uv"):
        return True
    print("  uv not found. Install it first:")
    print(
        "    Windows:  powershell -ExecutionPolicy ByPass -c "
        '"irm https://astral.sh/uv/install.ps1 | iex"'
    )
    print("    macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh")
    return False


def main():
    print("\n" + "=" * 70)
    print("Polymarket Trading Framework - Quick Start")
    print("=" * 70)

    # Step 1: Check uv
    print_step(1, "Check uv")
    if not check_uv():
        sys.exit(1)
    print("  uv is available")

    # Step 2: Create virtual environment
    print_step(2, "Create Virtual Environment")
    venv_path = Path(".venv")
    if not venv_path.exists():
        if not run("uv venv", "Create .venv"):
            sys.exit(1)
    else:
        print("  .venv already exists — skipping")

    # Step 3: Install project and dependencies
    print_step(3, "Install Project and Dependencies")
    if not run("uv pip install -e .", "Install project (editable)"):
        sys.exit(1)
    print("\n  The 'polymarket' command is now registered in your venv.")

    # Step 4: Configure .env
    print_step(4, "Configure Environment Variables")
    if not Path(".env").exists():
        if Path(".env.template").exists():
            run(
                "cp .env.template .env" if os.name != "nt" else "copy .env.template .env",
                "Create .env from template",
            )
        print("\n  Edit .env and set your credentials:")
        print("    POLYMARKET_PRIVATE_KEY=your_key_here")
        print("    POLYMARKET_FUNDER_ADDRESS=your_address_here")
        print("    PAPER_TRADING_ONLY=True  (keep True until you're ready to go live)")
    else:
        print("  .env already exists — skipping")

    # Step 5: Activate and validate
    print_step(5, "Next Steps")
    if os.name == "nt":
        activate = ".venv\\Scripts\\activate"
    else:
        activate = "source .venv/bin/activate"

    print(f"  1. Activate the environment:  {activate}")
    print("  2. Edit .env with your credentials")
    print("  3. Validate setup:            python tests/scripts/validate_setup.py")
    print("  4. Start the bot:             polymarket")
    print("  5. Open dashboard:            http://localhost:8080")

    print("\n" + "=" * 70)
    print("Setup complete.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
