"""
Strategy Registry
Maps strategy names (used in config/env) to their implementation classes.

To add a new strategy:
  1. Implement TradingStrategy (strategies/base.py)
  2. Add an entry to STRATEGY_REGISTRY below
  3. Set STRATEGY=<name> in .env
"""

from typing import Dict, Type

from strategies.base import TradingStrategy

# Populated lazily to avoid circular imports at module load time
_REGISTRY: Dict[str, Type] = {}


def _build_registry() -> Dict[str, Type]:
    from strategies.examples.settlement_arbitrage import SettlementArbitrage
    from strategies.examples.demo_buy import DemoBuy
    from strategies.examples.paper_demo import PaperDemo

    return {
        "settlement_arbitrage": SettlementArbitrage,
        "demo_buy": DemoBuy,
        "paper_demo": PaperDemo,
    }


def load_strategy(name: str, client) -> TradingStrategy:
    """
    Instantiate a strategy by its registered name.

    Args:
        name: Strategy name as defined in STRATEGY_REGISTRY (e.g. "settlement_arbitrage")
        client: PolymarketClient instance passed to the strategy constructor

    Returns:
        Instantiated TradingStrategy

    Raises:
        ValueError: If the name is not found in the registry
    """
    global _REGISTRY
    if not _REGISTRY:
        _REGISTRY = _build_registry()

    strategy_class = _REGISTRY.get(name)
    if strategy_class is None:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"Unknown strategy '{name}'. Available strategies: {available}"
        )

    return strategy_class(client)


def available_strategies() -> list:
    """Return a list of all registered strategy names."""
    global _REGISTRY
    if not _REGISTRY:
        _REGISTRY = _build_registry()
    return list(_REGISTRY.keys())
