"""
ExternalDataBus — single point of access for all external market signals.

Owns one instance of each provider, caches results at per-provider TTLs,
and assembles a typed ExternalSnapshot on demand. Thread-safe via RLock.

Design contract
───────────────
• get_snapshot() is called once per trading loop tick (from main.py).
• The bus decides internally whether any provider needs refreshing.
• All network I/O runs synchronously inside the lock. Per-provider timeouts
  bound total latency (worst case: ~10s if all three refresh simultaneously,
  which only happens on first call or after a long idle).
• Any provider failure leaves the corresponding snapshot fields as None.
  The trading loop is NEVER blocked or raised by a provider error.
• When EXTERNAL_DATA_ENABLED=False, get_snapshot() returns an empty snapshot
  with zero network calls.

Instantiate once in TradingBot.__init__(), pass the result of get_snapshot()
to strategy.scan_for_opportunities(markets, ext=ext) on every tick.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from config.polymarket_config import config as _config
from data.external.snapshot import ExternalSnapshot
import data.external.binance as _binance
import data.external.coingecko as _cg
import data.external.fear_greed as _fg
import data.external.indicators as _ind
from data.external.fred import FREDProvider
from utils.logger import logger


class ExternalDataBus:
    """
    Coordinates all external data providers with per-provider TTL caching.

    All public methods are thread-safe. Designed to be instantiated once in
    TradingBot.__init__() and shared between the trading thread and the
    dashboard thread.
    """

    def __init__(self, cfg=None) -> None:
        self._cfg = cfg or _config

        self._lock = threading.RLock()

        # Provider instances
        self._fred = FREDProvider(api_key=getattr(self._cfg, "FRED_API_KEY", "") or "")

        # Cached data — updated by _refresh_* methods
        self._crypto_prices: Dict[str, float] = {}
        self._crypto_rsi: Dict[str, float] = {}
        self._crypto_change: Dict[str, float] = {}
        self._crypto_volume: Dict[str, float] = {}
        self._fg_index: Optional[int] = None
        self._fg_label: Optional[str] = None
        self._macro: Dict[str, Optional[float]] = {}

        # Monotonic timestamps of last successful fetch (0 = never fetched)
        self._crypto_ts: float = 0.0
        self._fg_ts: float = 0.0
        self._macro_ts: float = 0.0

        # TTLs (seconds) — read from config with defaults
        self._crypto_ttl: float = float(getattr(self._cfg, "EXTERNAL_CRYPTO_TTL_S", 15))
        self._fg_ttl: float = float(getattr(self._cfg, "EXTERNAL_FNG_TTL_S", 3600))
        self._macro_ttl: float = float(getattr(self._cfg, "EXTERNAL_MACRO_TTL_S", 3600))

        # Symbols to track — parsed from EXTERNAL_CRYPTO_SYMBOLS
        raw = getattr(self._cfg, "EXTERNAL_CRYPTO_SYMBOLS", "BTC,ETH,SOL")
        self._symbols: List[str] = [s.strip().upper() for s in raw.split(",") if s.strip()]

        logger.info(
            f"[ExternalDataBus] Initialized | "
            f"symbols={self._symbols} | "
            f"crypto_ttl={self._crypto_ttl}s | "
            f"fred={'enabled' if getattr(self._cfg, 'FRED_API_KEY', '') else 'disabled (no key)'}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_snapshot(self) -> ExternalSnapshot:
        """
        Return a current ExternalSnapshot.

        Fast path (cache hit): returns in <1 ms — just assembles a dataclass
        from existing cache dicts inside the lock.

        Slow path (stale cache): refreshes any expired providers, then assembles.
        Binance timeout = 10s, Fear&Greed = 8s, FRED = 12s. With the default
        3 symbols (BTC, ETH, SOL), crypto refresh makes 1 bulk spot call + 3
        per-symbol 24h calls + 3 per-symbol klines calls sequentially — worst-case
        latency for that provider alone is ~70s under full timeout. In practice
        calls complete in <1s each; only F&G and FRED refresh at most once per hour.
        TTL timestamps are only updated when a provider returns data, so a total
        failure triggers a retry on the next tick.

        Always returns a valid ExternalSnapshot — NEVER raises.
        """
        if not self._is_enabled():
            return ExternalSnapshot()

        with self._lock:
            try:
                self._refresh_stale()
            except Exception as e:
                logger.warning(f"[ExternalDataBus] Refresh error (non-fatal): {e}")
            return self._build_snapshot()

    def invalidate(self) -> None:
        """Force all caches to expire — next get_snapshot() will re-fetch everything."""
        with self._lock:
            self._crypto_ts = 0.0
            self._fg_ts = 0.0
            self._macro_ts = 0.0
        logger.debug("[ExternalDataBus] All caches invalidated")

    # ── Internal refresh ──────────────────────────────────────────────────────

    def _is_enabled(self) -> bool:
        return bool(getattr(self._cfg, "EXTERNAL_DATA_ENABLED", True))

    def _refresh_stale(self) -> None:
        """Check TTLs and refresh only what has expired. Called inside _lock.

        Timestamps are only advanced when a provider returns data — a total
        failure leaves the timestamp unchanged so the next tick retries.
        """
        now = time.monotonic()
        if now - self._crypto_ts > self._crypto_ttl:
            if self._refresh_crypto():
                self._crypto_ts = now
        if now - self._fg_ts > self._fg_ttl:
            if self._refresh_fear_greed():
                self._fg_ts = now
        if now - self._macro_ts > self._macro_ttl:
            if self._refresh_macro():
                self._macro_ts = now

    def _refresh_crypto(self) -> bool:
        """Fetch spot prices, 24h stats, and 1h RSI from Binance (with CoinGecko fallback).

        Returns True if spot prices were obtained (the most critical data),
        False on total failure so the caller can decide whether to retry sooner.
        """
        logger.debug(f"[ExternalDataBus] Refreshing crypto | symbols={self._symbols}")

        # 1. Spot prices — single bulk call to Binance
        prices = _binance.fetch_spot_prices(self._symbols)
        if not prices:
            logger.debug("[ExternalDataBus] Binance spot empty, trying CoinGecko fallback")
            prices = _cg.fetch_prices(self._symbols)
        if prices:
            self._crypto_prices = prices

        # 2. 24h stats — one call per symbol on Binance
        stats = _binance.fetch_ticker_24h(self._symbols)
        changes: Dict[str, float] = {}
        volumes: Dict[str, float] = {}
        for sym, s in stats.items():
            changes[sym] = s.get("priceChangePercent", 0.0)
            volumes[sym] = s.get("quoteVolume", 0.0)
        if changes:
            self._crypto_change = changes
        if volumes:
            self._crypto_volume = volumes

        # 3. RSI(14) on 1h closes — one klines call per symbol
        rsi_map: Dict[str, float] = {}
        for sym in self._symbols:
            closes = _binance.fetch_closes(sym, interval="1h", limit=50)
            if closes:
                val = _ind.rsi(closes, period=14)
                if val is not None:
                    rsi_map[sym] = val
        if rsi_map:
            self._crypto_rsi = rsi_map

        logger.debug(
            f"[ExternalDataBus] Crypto done | prices={list(prices.keys())} | rsi={rsi_map}"
        )
        return bool(prices)

    def _refresh_fear_greed(self) -> bool:
        """Fetch Fear & Greed Index from alternative.me.

        Returns True if a value was obtained, False on failure.
        """
        logger.debug("[ExternalDataBus] Refreshing Fear & Greed...")
        index, label = _fg.fetch()
        if index is not None:
            self._fg_index = index
            self._fg_label = label
            return True
        return False

    def _refresh_macro(self) -> bool:
        """Fetch FRED macro series. Silent no-op if api_key not configured.

        Returns True when no key is set (nothing to retry) or when data was
        obtained. Returns False only when a key is set but the fetch failed.
        """
        if not getattr(self._cfg, "FRED_API_KEY", ""):
            return True  # no key → nothing to retry, advance the timestamp
        logger.debug("[ExternalDataBus] Refreshing FRED macro...")
        data = self._fred.fetch_all()
        if data:
            self._macro = data
            return True
        return False

    def _build_snapshot(self) -> ExternalSnapshot:
        """Assemble an ExternalSnapshot from the current cache state."""
        return ExternalSnapshot(
            crypto_prices=dict(self._crypto_prices),
            crypto_rsi_1h=dict(self._crypto_rsi),
            crypto_change_24h=dict(self._crypto_change),
            crypto_volume_24h=dict(self._crypto_volume),
            fear_greed_index=self._fg_index,
            fear_greed_label=self._fg_label,
            fed_funds_rate=self._macro.get("fed_funds_rate"),
            cpi_level=self._macro.get("cpi_level"),
            core_pce_level=self._macro.get("core_pce_level"),
            unemployment_rate=self._macro.get("unemployment_rate"),
        )
