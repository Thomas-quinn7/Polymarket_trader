"""
Binance public REST API provider.

No API key required for the endpoints used here (public market data).
A module-level requests.Session reuses TCP connections to reduce latency,
matching the _http_session pattern in data/polymarket_client.py.

Rate limits (weight budget: 6000/minute):
  /api/v3/ticker/price (all symbols)  — weight 4
  /api/v3/ticker/24hr  (per symbol)   — weight 4 each
  /api/v3/klines       (per request)  — weight 2
  Typical usage per ExternalDataBus refresh: <30 weight total.

Docs: https://binance-docs.github.io/apidocs/spot/en/
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import requests

from utils.logger import logger

_BASE = "https://api.binance.com"
_TIMEOUT = 10  # seconds per request

# Module-level session — reuses TCP connections across all calls in this process.
_session = requests.Session()
_session.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "polymarket-trading-bot/1.0",
    }
)


def _get(path: str, params: Optional[dict] = None) -> Optional[object]:
    """GET a Binance endpoint. Returns parsed JSON or None on any error."""
    url = _BASE + path
    try:
        resp = _session.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning(f"[Binance] Timeout fetching {path}")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        logger.warning(f"[Binance] HTTP {status} for {path}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[Binance] Request error for {path}: {e}")
    except Exception as e:
        logger.warning(f"[Binance] Unexpected error for {path}: {e}")
    return None


def fetch_spot_prices(symbols: List[str]) -> Dict[str, float]:
    """
    Fetch current USDT spot prices for a list of base symbols.

    Uses the bulk /api/v3/ticker/price endpoint (weight=4 total regardless
    of symbol count). Filters the full response to only requested symbols.

    Args:
        symbols: Base asset names, e.g. ["BTC", "ETH", "SOL"].
                 Automatically paired with USDT.

    Returns:
        Dict mapping UPPERCASE symbol → float price.
        Missing symbols are silently omitted (not zero-filled).

    Example:
        {"BTC": 94500.0, "ETH": 1820.5, "SOL": 147.3}
    """
    wanted = {f"{s.upper()}USDT" for s in symbols}
    data = _get("/api/v3/ticker/price")
    if not data or not isinstance(data, list):
        return {}

    out: Dict[str, float] = {}
    for item in data:
        pair = item.get("symbol", "")
        if pair in wanted:
            try:
                symbol = pair[:-4]  # strip "USDT" suffix
                out[symbol] = float(item["price"])
            except (KeyError, ValueError):
                pass

    missing = {s.upper() for s in symbols} - set(out.keys())
    if missing:
        logger.debug(f"[Binance] Spot prices not found for: {missing}")
    return out


def fetch_ticker_24h(symbols: List[str]) -> Dict[str, dict]:
    """
    Fetch 24-hour ticker statistics for a list of symbols.

    Makes one API call per symbol to avoid the weight=80 bulk penalty
    (vs weight=4 per individual symbol call).

    Returns dict keyed by UPPERCASE symbol, each value containing:
        priceChangePercent: float  — 24h change in % (e.g. -3.5 = fell 3.5%)
        volume:             float  — base asset volume (e.g. BTC quantity)
        quoteVolume:        float  — USDT volume (more useful for $ comparisons)
        lastPrice:          float  — current last traded price
    """
    out: Dict[str, dict] = {}
    for sym in symbols:
        pair = f"{sym.upper()}USDT"
        data = _get("/api/v3/ticker/24hr", params={"symbol": pair})
        if data and isinstance(data, dict):
            try:
                out[sym.upper()] = {
                    "priceChangePercent": float(data.get("priceChangePercent", 0)),
                    "volume": float(data.get("volume", 0)),
                    "quoteVolume": float(data.get("quoteVolume", 0)),
                    "lastPrice": float(data.get("lastPrice", 0)),
                }
            except (ValueError, TypeError) as e:
                logger.debug(f"[Binance] Could not parse 24h ticker for {sym}: {e}")
    return out


def fetch_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 50,
) -> List[Tuple[int, float, float, float, float, float]]:
    """
    Fetch OHLCV candlestick data.

    Args:
        symbol:   Base asset, e.g. "BTC" → automatically becomes "BTCUSDT".
        interval: Binance kline interval: "1m","5m","15m","1h","4h","1d","1w".
        limit:    Number of candles to return (max 1000, default 50).
                  For RSI(14) you need at least 15; 50 gives the SMMA room
                  to converge and produces a more accurate value.

    Returns:
        List of (open_time_ms, open, high, low, close, volume) tuples,
        oldest first. Returns empty list on any error.
    """
    pair = f"{symbol.upper()}USDT"
    data = _get(
        "/api/v3/klines",
        params={
            "symbol": pair,
            "interval": interval,
            "limit": limit,
        },
    )
    if not data or not isinstance(data, list):
        return []

    out = []
    for candle in data:
        try:
            out.append(
                (
                    int(candle[0]),  # open_time_ms
                    float(candle[1]),  # open
                    float(candle[2]),  # high
                    float(candle[3]),  # low
                    float(candle[4]),  # close  ← used by indicators.rsi()
                    float(candle[5]),  # volume
                )
            )
        except (IndexError, ValueError):
            pass
    return out


def fetch_closes(symbol: str, interval: str = "1h", limit: int = 50) -> List[float]:
    """
    Return only close prices from fetch_klines.

    Direct input for indicators.rsi(), indicators.ema(), indicators.z_score().

    Example:
        closes = fetch_closes("BTC", interval="1h", limit=50)
        rsi_value = indicators.rsi(closes, period=14)
    """
    return [c[4] for c in fetch_klines(symbol, interval, limit)]
