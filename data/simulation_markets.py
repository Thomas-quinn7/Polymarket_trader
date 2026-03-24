"""
Simulation market data generator
Produces synthetic markets that exercise the full strategy/execution path
without making any real API calls.
"""

import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict


# Fixed synthetic markets — prices and close times shift each call to simulate live data
_MARKET_TEMPLATES = [
    {"slug": "sim-btc-above-100k-eod", "question": "Will BTC be above $100k end of day?", "category": "crypto"},
    {"slug": "sim-eth-above-4k-eod",   "question": "Will ETH be above $4k end of day?",   "category": "crypto"},
    {"slug": "sim-sol-above-200-eod",  "question": "Will SOL be above $200 end of day?",  "category": "crypto"},
    {"slug": "sim-btc-weekly-high",    "question": "Will BTC set a weekly high this week?","category": "crypto"},
    {"slug": "sim-fed-rate-hold",      "question": "Will Fed hold rates at next meeting?", "category": "fed"},
    {"slug": "sim-eth-etf-approved",   "question": "Will ETH ETF get approved this month?","category": "regulatory"},
]


def _make_token_id(seed: str) -> str:
    """Generate a deterministic fake token ID from a seed string."""
    return str(abs(hash(seed)) % (10 ** 76)).zfill(76)


def generate_simulation_markets(category: str = None) -> list:
    """
    Return a list of synthetic market dicts that match the shape the strategy expects.
    Prices are randomised each call within realistic ranges so the strategy
    occasionally finds opportunities in the [0.985, 1.00] window.
    """
    now = datetime.now(timezone.utc)
    markets = []

    for i, tmpl in enumerate(_MARKET_TEMPLATES):
        if category and tmpl["category"] != category:
            continue

        # Randomise: ~20% chance the price is in the arb window [0.985, 1.00]
        if random.random() < 0.20:
            yes_price = round(random.uniform(0.985, 0.999), 4)
            # Close in 5–30 seconds so timers fire quickly during testing
            seconds_to_close = random.randint(5, 30)
        else:
            yes_price = round(random.uniform(0.50, 0.984), 4)
            seconds_to_close = random.randint(60, 3600)

        no_price = round(1.0 - yes_price, 4)
        end_date = (now + timedelta(seconds=seconds_to_close)).strftime("%Y-%m-%dT%H:%M:%SZ")

        token_yes = _make_token_id(f"{tmpl['slug']}_yes")
        token_no  = _make_token_id(f"{tmpl['slug']}_no")

        markets.append({
            "id": f"sim-{i+1:04d}",
            "slug": tmpl["slug"],
            "question": tmpl["question"],
            "active": True,
            "closed": False,
            "endDate": end_date,
            "clobTokenIds": [token_yes, token_no],
            "outcomePrices": [str(yes_price), str(no_price)],
            "tags": [{"label": tmpl["category"]}],
            # Synthetic volume so the liquidity filter passes in simulation mode
            "volume": round(random.uniform(5000.0, 50000.0), 2),
            # Simulation flag — lets get_price() return the baked-in price
            "_sim_yes_price": yes_price,
        })

    return markets


def generate_sim_order_book(token_id: str, mid_price: float, levels: int = 5) -> Dict:
    """
    Generate a synthetic order book for simulation mode.

    Produces a realistic-looking bid/ask ladder centred on `mid_price` with
    random sizes so downstream consumers see a properly shaped book.

    Returns a dict with keys ``bids`` and ``asks``, each a list of
    ``{"price": float, "size": float}`` dicts sorted in the usual direction
    (bids high→low, asks low→high).
    """
    spread = round(random.uniform(0.001, 0.005), 4)
    tick = round(random.uniform(0.001, 0.003), 4)

    bids = []
    for i in range(levels):
        price = round(mid_price - spread / 2 - i * tick, 4)
        size = round(random.uniform(50.0, 500.0), 2)
        bids.append({"price": max(price, 0.001), "size": size})

    asks = []
    for i in range(levels):
        price = round(mid_price + spread / 2 + i * tick, 4)
        size = round(random.uniform(50.0, 500.0), 2)
        asks.append({"price": min(price, 0.999), "size": size})

    return {
        "bids": bids,   # high → low
        "asks": asks,   # low → high
        "mid_price": mid_price,
    }
