# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

"""
Strategy Registry — auto-discovers strategies from subfolders.

Each strategy lives in its own folder under strategies/:

    strategies/
        my_strategy/
            __init__.py     ← must export a class that subclasses BaseStrategy
            strategy.py     ← implementation
            config.yaml     ← YAML parameters

The registry scans all subfolders at first use, imports each package, and
registers any class that subclasses BaseStrategy.  No manual registration
is needed — adding a new folder with a valid __init__.py is enough.

Set STRATEGY=<folder_name> in .env to select which strategy the bot runs.
"""

import importlib
import inspect
import os
from typing import Dict, Optional, Type

from strategies.base import BaseStrategy, TradingStrategy
from utils.logger import logger

# Subfolders that are part of the framework itself, not strategies.
_SKIP_DIRS = {"__pycache__", "examples", "configs"}

_REGISTRY: Dict[str, Type[BaseStrategy]] = {}
_STRATEGIES_DIR = os.path.dirname(__file__)


def _build_registry() -> Dict[str, Type[BaseStrategy]]:
    """
    Scan strategies/ for subfolders that export a BaseStrategy subclass.

    A folder qualifies when it:
      - is a directory (not a file)
      - is not in _SKIP_DIRS and does not start with '_'
      - contains an __init__.py
      - exports at least one class that subclasses BaseStrategy
    """
    registry: Dict[str, Type[BaseStrategy]] = {}

    for entry in sorted(os.scandir(_STRATEGIES_DIR), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS or entry.name.startswith("_"):
            continue
        if not os.path.exists(os.path.join(entry.path, "__init__.py")):
            continue

        module_name = f"strategies.{entry.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.warning(f"Registry: could not import {module_name!r}: {exc}")
            continue

        # Find the first BaseStrategy subclass exported by the package
        strategy_class: Optional[Type[BaseStrategy]] = None
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy
                and obj is not TradingStrategy
            ):
                strategy_class = obj
                break

        if strategy_class is None:
            logger.debug(f"Registry: {module_name!r} has no BaseStrategy subclass — skipping")
            continue

        registry[entry.name] = strategy_class
        logger.debug(f"Registry: registered '{entry.name}' → {strategy_class.__name__}")

    return registry


def _get_registry() -> Dict[str, Type[BaseStrategy]]:
    global _REGISTRY
    if not _REGISTRY:
        _REGISTRY = _build_registry()
    return _REGISTRY


def load_strategy(name: str, client) -> BaseStrategy:
    """
    Instantiate a strategy by its folder name.

    Args:
        name:   Strategy folder name, e.g. ``"settlement_arbitrage"``.
        client: PolymarketClient instance passed to the strategy constructor.

    Returns:
        Instantiated BaseStrategy.

    Raises:
        ValueError: If the name is not found in the registry.
    """
    registry = _get_registry()
    strategy_class = registry.get(name)
    if strategy_class is None:
        available = ", ".join(sorted(registry))
        raise ValueError(f"Unknown strategy '{name}'. Available strategies: {available}")
    return strategy_class(client)


def available_strategies() -> list:
    """Return a sorted list of all auto-discovered strategy names."""
    return sorted(_get_registry())
