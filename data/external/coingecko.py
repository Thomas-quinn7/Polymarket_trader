"""
CoinGecko public API — free tier, no API key required.

Used as a fallback when Binance is unavailable, and for assets
not available as USDT pairs on Binance.

Rate limits: ~30 requests/minute on the free tier.
ExternalDataBus only calls this as a fallback — Binance is primary.

Docs: https://www.coingecko.com/api/documentation
"""

from __future__ import annotations

from typing import Dict, List, Optional

import requests

from utils.logger import logger

_BASE = "https://api.coingecko.com/api/v3"
_TIMEOUT = 10

# CoinGecko uses its own ID system, not ticker symbols.
# Extend this map to support additional assets.
_SYMBOL_TO_ID: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "ATOM": "cosmos",
    "NEAR": "near",
}

_session = requests.Session()
_session.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "polymarket-trading-bot/1.0",
    }
)


def _get(path: str, params: Optional[dict] = None) -> Optional[object]:
    url = _BASE + path
    try:
        resp = _session.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("[CoinGecko] Rate limited (429)")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning(f"[CoinGecko] Timeout for {path}")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        logger.warning(f"[CoinGecko] HTTP {status} for {path}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[CoinGecko] Request error: {e}")
    except Exception as e:
        logger.warning(f"[CoinGecko] Unexpected error: {e}")
    return None


def fetch_prices(symbols: List[str]) -> Dict[str, float]:
    """
    Fetch current USD prices for a list of symbols.

    Symbols not in _SYMBOL_TO_ID are silently skipped.
    Used as a fallback when Binance returns empty results.

    Returns dict mapping UPPERCASE symbol → float price.
    """
    ids = [_SYMBOL_TO_ID[s.upper()] for s in symbols if s.upper() in _SYMBOL_TO_ID]
    if not ids:
        return {}

    data = _get(
        "/simple/price",
        params={
            "ids": ",".join(ids),
            "vs_currencies": "usd",
        },
    )
    if not data or not isinstance(data, dict):
        return {}

    id_to_sym = {v: k for k, v in _SYMBOL_TO_ID.items()}
    out: Dict[str, float] = {}
    for cg_id, prices in data.items():
        sym = id_to_sym.get(cg_id)
        if sym and "usd" in prices:
            try:
                out[sym] = float(prices["usd"])
            except (ValueError, TypeError):
                pass
    return out
