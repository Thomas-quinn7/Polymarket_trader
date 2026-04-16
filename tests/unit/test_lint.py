"""
Lint tests — mirror the CI checks (black + flake8) so formatting regressions
and style violations are caught locally before a push triggers a CI failure.

These tests run the same commands as .github/workflows/ci.yml:
  black --check .
  flake8 .        (reads config from .flake8)
"""

import subprocess
import sys
from pathlib import Path

# Navigate from tests/unit/ up to the project root.
ROOT = Path(__file__).resolve().parent.parent.parent


def test_black_formatting():
    """
    All source files must be formatted by black.

    Failure means someone committed code without running `black .` first.
    Fix: run `black .` from the project root, then re-commit.
    """
    result = subprocess.run(
        [sys.executable, "-m", "black", "--check", str(ROOT)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        "black found formatting issues — run `black .` from the project root to fix.\n\n"
        + result.stderr
    )


def test_flake8_lint():
    """
    All source files must pass flake8 with the project's .flake8 settings.

    Failure means a style violation was introduced.
    Fix: address each path:line:col reported below.
    """
    result = subprocess.run(
        [sys.executable, "-m", "flake8", str(ROOT)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, "flake8 violations found:\n\n" + result.stdout
