"""
ShowcaseDemo — synthetic demo strategy for live dashboard demonstrations.

Drives realistic-looking trading activity through the full framework stack
using 40 pre-defined synthetic markets. No API credentials or internet
access are required in simulation mode.

Recommended .env settings for a nice dashboard demo
----------------------------------------------------
    STRATEGY=showcase_demo
    TRADING_MODE=simulation
    PAPER_TRADING_ONLY=true
    FAKE_CURRENCY_BALANCE=10000.00
    MAX_POSITIONS=5
    CAPITAL_SPLIT_PERCENT=8
    SCAN_INTERVAL_MS=20000

Do not use for live or real paper trading.
"""

import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from data.external.snapshot import ExternalSnapshot

from config.polymarket_config import config
from data.market_provider import MarketCriteria
from data.market_schema import PolymarketMarket
from data.polymarket_models import TradeOpportunity, TradeStatus
from strategies.base import BaseStrategy
from strategies.config_loader import load_strategy_config
from utils.logger import logger

_STRATEGY_NAME = "showcase_demo"

_DEFAULTS: Dict = {
    "hold_seconds_min": 90,
    "hold_seconds_max": 600,
    "win_rate": 0.68,
    "edge_min": 2.5,
    "edge_max": 11.0,
    "confidence_min": 0.40,
    "confidence_max": 0.92,
    "min_price": 0.18,
    "max_price": 0.82,
}

# ---------------------------------------------------------------------------
# Synthetic market universe — 40 markets across 4 categories
# Token IDs follow the pattern  dtk_<id>_yes / dtk_<id>_no
# ---------------------------------------------------------------------------

_SYNTHETIC_MARKETS: List[Dict] = [
    # ── Crypto ───────────────────────────────────────────────────────────────
    {
        "id": "c01",
        "slug": "btc-100k-2026",
        "question": "Will BTC reach $100K in 2026?",
        "category": "crypto",
        "price": 0.42,
    },
    {
        "id": "c02",
        "slug": "eth-10k-2026",
        "question": "Will ETH reach $10K in 2026?",
        "category": "crypto",
        "price": 0.28,
    },
    {
        "id": "c03",
        "slug": "btc-ath-q1-2026",
        "question": "Will BTC set a new all-time high in Q1 2026?",
        "category": "crypto",
        "price": 0.35,
    },
    {
        "id": "c04",
        "slug": "sol-200-2026",
        "question": "Will SOL exceed $200 by end of 2026?",
        "category": "crypto",
        "price": 0.53,
    },
    {
        "id": "c05",
        "slug": "btc-halving-rally",
        "question": "Will BTC rally >50% in the 6 months post-halving?",
        "category": "crypto",
        "price": 0.47,
    },
    {
        "id": "c06",
        "slug": "eth-btc-ratio-06",
        "question": "Will the ETH/BTC ratio exceed 0.06 in 2026?",
        "category": "crypto",
        "price": 0.31,
    },
    {
        "id": "c07",
        "slug": "btc-etf-50b",
        "question": "Will BTC spot ETF inflows exceed $50B cumulative in 2026?",
        "category": "crypto",
        "price": 0.67,
    },
    {
        "id": "c08",
        "slug": "crypto-cap-5t",
        "question": "Will total crypto market cap exceed $5T in 2026?",
        "category": "crypto",
        "price": 0.38,
    },
    {
        "id": "c09",
        "slug": "bnb-1000-2026",
        "question": "Will BNB reach $1,000 in 2026?",
        "category": "crypto",
        "price": 0.44,
    },
    {
        "id": "c10",
        "slug": "defi-tvl-500b",
        "question": "Will total DeFi TVL exceed $500B in 2026?",
        "category": "crypto",
        "price": 0.24,
    },
    # ── Fed / Macro ──────────────────────────────────────────────────────────
    {
        "id": "f01",
        "slug": "fed-cut-june-2026",
        "question": "Will the Fed cut rates at the June 2026 FOMC?",
        "category": "fed",
        "price": 0.72,
    },
    {
        "id": "f02",
        "slug": "fed-cut-q3-2026",
        "question": "Will the Fed cut rates at least once in Q3 2026?",
        "category": "fed",
        "price": 0.65,
    },
    {
        "id": "f03",
        "slug": "fed-funds-below-4",
        "question": "Will the Fed funds rate be below 4% by end of 2026?",
        "category": "fed",
        "price": 0.55,
    },
    {
        "id": "f04",
        "slug": "us-cpi-below-3",
        "question": "Will US CPI fall below 3% by September 2026?",
        "category": "fed",
        "price": 0.48,
    },
    {
        "id": "f05",
        "slug": "us-recession-2026",
        "question": "Will the US enter a recession in 2026?",
        "category": "fed",
        "price": 0.27,
    },
    {
        "id": "f06",
        "slug": "10yr-below-4-2026",
        "question": "Will the 10-year Treasury yield fall below 4% in 2026?",
        "category": "fed",
        "price": 0.41,
    },
    {
        "id": "f07",
        "slug": "fed-cut-sept-2026",
        "question": "Will the Fed cut rates at the September 2026 FOMC?",
        "category": "fed",
        "price": 0.78,
    },
    {
        "id": "f08",
        "slug": "us-gdp-above-2-2026",
        "question": "Will US GDP growth exceed 2% in 2026?",
        "category": "fed",
        "price": 0.62,
    },
    {
        "id": "f09",
        "slug": "unemployment-below-4",
        "question": "Will US unemployment remain below 4% through Q2 2026?",
        "category": "fed",
        "price": 0.59,
    },
    {
        "id": "f10",
        "slug": "fomc-three-cuts-2026",
        "question": "Will the Fed cut rates at least 3 times in 2026?",
        "category": "fed",
        "price": 0.33,
    },
    # ── Regulatory ───────────────────────────────────────────────────────────
    {
        "id": "r01",
        "slug": "sec-crypto-framework",
        "question": "Will the SEC release a comprehensive crypto framework in 2026?",
        "category": "regulatory",
        "price": 0.39,
    },
    {
        "id": "r02",
        "slug": "eu-mica-enforcement",
        "question": "Will EU MiCA enforcement begin before Q3 2026?",
        "category": "regulatory",
        "price": 0.71,
    },
    {
        "id": "r03",
        "slug": "us-crypto-bill-2026",
        "question": "Will the US Congress pass a crypto market structure bill?",
        "category": "regulatory",
        "price": 0.22,
    },
    {
        "id": "r04",
        "slug": "stablecoin-reg-us",
        "question": "Will the US pass stablecoin legislation by end of 2026?",
        "category": "regulatory",
        "price": 0.45,
    },
    {
        "id": "r05",
        "slug": "us-cbdc-pilot-2026",
        "question": "Will the US launch a CBDC pilot program in 2026?",
        "category": "regulatory",
        "price": 0.19,
    },
    {
        "id": "r06",
        "slug": "sec-eth-futures-etf",
        "question": "Will the SEC approve an Ethereum futures ETF before mid-2026?",
        "category": "regulatory",
        "price": 0.74,
    },
    {
        "id": "r07",
        "slug": "ftx-80-cents",
        "question": "Will FTX creditor distributions exceed 80 cents on the dollar?",
        "category": "regulatory",
        "price": 0.68,
    },
    {
        "id": "r08",
        "slug": "defi-us-guidance",
        "question": "Will US regulators issue formal DeFi guidance in 2026?",
        "category": "regulatory",
        "price": 0.29,
    },
    {
        "id": "r09",
        "slug": "crypto-tax-change",
        "question": "Will US crypto capital gains tax rates change in 2026?",
        "category": "regulatory",
        "price": 0.21,
    },
    {
        "id": "r10",
        "slug": "offshore-us-license",
        "question": "Will a major offshore exchange obtain a US federal license?",
        "category": "regulatory",
        "price": 0.36,
    },
    # ── Other ────────────────────────────────────────────────────────────────
    {
        "id": "o01",
        "slug": "ai-regulation-2026",
        "question": "Will the US pass major AI regulation legislation in 2026?",
        "category": "other",
        "price": 0.31,
    },
    {
        "id": "o02",
        "slug": "tesla-robotaxi-2026",
        "question": "Will Tesla launch commercial robotaxi service in 2026?",
        "category": "other",
        "price": 0.52,
    },
    {
        "id": "o03",
        "slug": "openai-ipo-2026",
        "question": "Will OpenAI complete an IPO or major restructuring in 2026?",
        "category": "other",
        "price": 0.37,
    },
    {
        "id": "o04",
        "slug": "sp500-6000-q2",
        "question": "Will the S&P 500 exceed 6,000 by end of Q2 2026?",
        "category": "other",
        "price": 0.63,
    },
    {
        "id": "o05",
        "slug": "nvidia-4t-cap",
        "question": "Will NVIDIA's market cap exceed $4T in 2026?",
        "category": "other",
        "price": 0.48,
    },
    {
        "id": "o06",
        "slug": "gold-3000-2026",
        "question": "Will the gold price reach $3,000/oz in 2026?",
        "category": "other",
        "price": 0.57,
    },
    {
        "id": "o07",
        "slug": "meta-ar-glasses-2026",
        "question": "Will Meta launch consumer AR glasses before end of 2026?",
        "category": "other",
        "price": 0.42,
    },
    {
        "id": "o08",
        "slug": "apple-ai-chip-2026",
        "question": "Will Apple release a dedicated AI chip in 2026?",
        "category": "other",
        "price": 0.76,
    },
    {
        "id": "o09",
        "slug": "twitter-2b-mau",
        "question": "Will X/Twitter reach 2B monthly active users in 2026?",
        "category": "other",
        "price": 0.18,
    },
    {
        "id": "o10",
        "slug": "usd-reserve-below-55",
        "question": "Will the USD share of global reserves fall below 55% in 2026?",
        "category": "other",
        "price": 0.23,
    },
]

# Build token IDs and a flat price lookup used by the simulation price patch.
for _m in _SYNTHETIC_MARKETS:
    _m["yes_token"] = f"dtk_{_m['id']}_yes"
    _m["no_token"] = f"dtk_{_m['id']}_no"

_TOKEN_PRICES: Dict[str, float] = {}
for _m in _SYNTHETIC_MARKETS:
    _TOKEN_PRICES[_m["yes_token"]] = _m["price"]
    _TOKEN_PRICES[_m["no_token"]] = round(1.0 - _m["price"], 4)


# ---------------------------------------------------------------------------
# Exit plan — created lazily on first should_exit() call per position
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExitPlan:
    exit_at: datetime
    exit_price: float
    is_win: bool


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class ShowcaseDemo(BaseStrategy):
    """
    Demo strategy for live dashboard demonstrations.

    Generates controlled synthetic trading activity to populate all dashboard
    charts with realistic-looking data. Works in simulation mode with no API
    credentials or internet access required.

    Do not use for live or real paper trading.
    """

    def __init__(self, client):
        self._client = client
        cfg = {**_DEFAULTS, **load_strategy_config(_STRATEGY_NAME)}

        self._hold_min: int = int(cfg["hold_seconds_min"])
        self._hold_max: int = int(cfg["hold_seconds_max"])
        self._win_rate: float = float(cfg["win_rate"])
        self._edge_min: float = float(cfg["edge_min"])
        self._edge_max: float = float(cfg["edge_max"])
        self._conf_min: float = float(cfg["confidence_min"])
        self._conf_max: float = float(cfg["confidence_max"])
        self._min_price: float = float(cfg["min_price"])
        self._max_price: float = float(cfg["max_price"])

        # market_id → True: currently held (blocked from re-entry until exit)
        self._active_ids: set = set()
        # position_id → _ExitPlan
        self._exit_plans: Dict[str, _ExitPlan] = {}
        self._lock = threading.Lock()

        # In simulation mode the real API is bypassed and client.get_price()
        # returns None for every token.  The main loop skips should_exit() when
        # the price is None, so positions would never settle.  Patch the method
        # to return stable synthetic prices for showcase_demo tokens so the
        # None-guard passes and the exit path runs normally.
        if config.TRADING_MODE == "simulation":
            self._patch_get_price()

        logger.info(
            "[ShowcaseDemo] ready — "
            f"win_rate={self._win_rate:.0%}  "
            f"hold={self._hold_min}–{self._hold_max}s  "
            f"markets={len(_SYNTHETIC_MARKETS)}"
        )

    # ── BaseStrategy interface ─────────────────────────────────────────────

    def get_market_criteria(self) -> MarketCriteria:
        # Minimal criteria — showcase_demo uses synthetic markets and ignores
        # the real market list provided by MarketProvider.
        return MarketCriteria(categories=["crypto", "fed", "regulatory", "other"])

    def scan_for_opportunities(
        self,
        markets: List[PolymarketMarket],
        ext: "Optional[ExternalSnapshot]" = None,  # noqa: U100  unused — synthetic strategy
    ) -> List[TradeOpportunity]:
        """
        Ignore real markets; return opportunities from the synthetic pool.
        Only markets not currently held are eligible.
        """
        with self._lock:
            active = set(self._active_ids)

        candidates = [m for m in _SYNTHETIC_MARKETS if m["id"] not in active]
        random.shuffle(candidates)

        opportunities: List[TradeOpportunity] = []
        for mkt in candidates:
            price = mkt["price"]
            if not (self._min_price <= price <= self._max_price):
                continue

            edge = round(random.uniform(self._edge_min, self._edge_max), 2)
            confidence = round(random.uniform(self._conf_min, self._conf_max), 3)

            opportunities.append(
                TradeOpportunity(
                    market_id=mkt["id"],
                    market_slug=mkt["slug"],
                    question=mkt["question"],
                    category=mkt["category"],
                    token_id_yes=mkt["yes_token"],
                    token_id_no=mkt["no_token"],
                    winning_token_id=mkt["yes_token"],
                    current_price=price,
                    edge_percent=edge,
                    confidence=confidence,
                    detected_at=datetime.now(timezone.utc),
                    status=TradeStatus.DETECTED,
                )
            )

        return opportunities

    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        ranked = sorted(
            opportunities,
            key=lambda o: (o.edge_percent or 0.0) * (o.confidence or 0.5),
            reverse=True,
        )
        selected = ranked[:limit]

        # Register selected markets as active so we don't re-enter them until exit.
        with self._lock:
            for opp in selected:
                self._active_ids.add(opp.market_id)

        return selected

    def should_exit(self, position, current_price: float) -> bool:
        plan = self._ensure_plan(position)
        return datetime.now(timezone.utc) >= plan.exit_at

    def get_exit_price(self, position, current_price: float) -> float:
        plan = self._ensure_plan(position)
        # Release the market slot so it can be re-entered in a future scan,
        # letting the same markets cycle through the 40-market pool repeatedly.
        with self._lock:
            self._active_ids.discard(position.market_id)
        return plan.exit_price

    # ── Internal helpers ───────────────────────────────────────────────────

    def _ensure_plan(self, position) -> _ExitPlan:
        """Lazily create and cache the exit plan for a position."""
        pid = position.position_id
        with self._lock:
            if pid in self._exit_plans:
                return self._exit_plans[pid]

        entry = position.entry_price
        is_win = random.random() < self._win_rate
        hold_s = random.randint(self._hold_min, self._hold_max)

        opened_at = position.opened_at
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        exit_at = opened_at + timedelta(seconds=hold_s)

        if is_win:
            # Move toward resolution at 1.0 — scale the jump by remaining headroom
            # so high-priced entries still show a meaningful gain.
            headroom = min(0.96 - entry, 0.55)
            bump = random.uniform(max(headroom * 0.45, 0.10), max(headroom * 0.88, 0.18))
            exit_price = round(min(entry + bump, 0.96), 4)
        else:
            # Collapse toward zero — deeper drops on lower-priced entries.
            drop = random.uniform(max(entry * 0.35, 0.08), max(entry * 0.72, 0.22))
            exit_price = round(max(entry - drop, 0.04), 4)

        plan = _ExitPlan(exit_at=exit_at, exit_price=exit_price, is_win=is_win)

        with self._lock:
            self._exit_plans[pid] = plan

        logger.info(
            f"[ShowcaseDemo] {'WIN ' if is_win else 'LOSS'} "
            f"{pid[:24]}  entry={entry:.3f} → exit={exit_price:.3f}  hold={hold_s}s"
        )
        return plan

    def _patch_get_price(self) -> None:
        """
        Replace client.get_price with a synthetic version that returns stable
        prices for showcase_demo token IDs.

        Without this patch, simulation mode never calls the real API so
        get_price() returns None for all tokens.  The main loop's None-guard
        in _check_strategy_exits then skips every position, meaning should_exit()
        is never called and no position ever settles.
        """
        _rng = random.Random(42)

        def _synthetic_price(token_id: str) -> Optional[float]:
            base = _TOKEN_PRICES.get(token_id)
            if base is None:
                return None
            # Small Gaussian noise simulates live price tick updates.
            return max(0.01, min(0.99, base + _rng.gauss(0, 0.008)))

        self._client.get_price = _synthetic_price
        logger.debug("[ShowcaseDemo] client.get_price patched for simulation mode")
