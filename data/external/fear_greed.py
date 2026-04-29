"""
Alternative.me Crypto Fear & Greed Index provider.

Updates once daily. No API key or auth required.
API: https://api.alternative.me/fng/?limit=1&format=json

Index scale:
  0–24   Extreme Fear
  25–49  Fear
  50     Neutral
  51–74  Greed
  75–100 Extreme Greed

ExternalDataBus caches this for 1 hour (EXTERNAL_FNG_TTL_S) — no need
to call faster than once per hour.
"""

from __future__ import annotations

from typing import Optional, Tuple

import requests

from utils.logger import logger

_URL = "https://api.alternative.me/fng/?limit=1&format=json"
_TIMEOUT = 8

_session = requests.Session()
_session.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "polymarket-trading-bot/1.0",
    }
)


def fetch() -> Tuple[Optional[int], Optional[str]]:
    """
    Fetch the current Crypto Fear & Greed Index.

    Returns:
        Tuple of (index_value, label):
          index_value: int 0–100 (0=Extreme Fear, 100=Extreme Greed)
          label:       str, e.g. "Extreme Fear", "Fear", "Neutral",
                       "Greed", "Extreme Greed"

        Returns (None, None) on any error — never raises.
    """
    try:
        resp = _session.get(_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        entry = data.get("data", [{}])[0]
        value = int(entry.get("value", 0))
        label = entry.get("value_classification", "Unknown")
        logger.debug(f"[FearGreed] Index={value} ({label})")
        return value, label
    except requests.exceptions.Timeout:
        logger.warning("[FearGreed] Timeout")
    except requests.exceptions.HTTPError as e:
        logger.warning(f"[FearGreed] HTTP error: {e}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[FearGreed] Request error: {e}")
    except (KeyError, IndexError, ValueError, TypeError) as e:
        logger.warning(f"[FearGreed] Parse error: {e}")
    except Exception as e:
        logger.warning(f"[FearGreed] Unexpected error: {e}")
    return None, None
