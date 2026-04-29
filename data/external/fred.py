"""
FRED (Federal Reserve Economic Data) provider.

Free API key required — register at:
https://fred.stlouisfed.org/docs/api/api_key.html

Series fetched:
  FEDFUNDS  — Federal Funds Effective Rate (monthly, %)
  CPIAUCSL  — CPI All Urban Consumers (monthly index level)
  PCEPILFE  — Core PCE Price Index (monthly index level)
  UNRATE    — Civilian Unemployment Rate (monthly, %)

All series are fetched with sort_order=desc so the most recent
observation comes first. FRED uses "." to indicate missing values;
these are skipped until a real number is found.

ExternalDataBus caches FRED results for 1 hour (EXTERNAL_MACRO_TTL_S).
Silently no-ops when FRED_API_KEY is empty.

Rate limit: 120 requests/minute — hourly fetch of 4 series uses 4 calls.
Docs: https://fred.stlouisfed.org/docs/api/fred/
"""

from __future__ import annotations

from typing import Dict, Optional

import requests

from utils.logger import logger

_BASE = "https://api.stlouisfed.org/fred"
_TIMEOUT = 12

_session = requests.Session()
_session.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "polymarket-trading-bot/1.0",
    }
)


def _fetch_latest_value(series_id: str, api_key: str) -> Optional[float]:
    """
    Fetch the most recent non-missing observation value for a FRED series.

    Args:
        series_id: FRED series ID, e.g. "FEDFUNDS".
        api_key:   Your FRED API key string.

    Returns:
        Most recent float value, or None on any error or missing data.
    """
    url = f"{_BASE}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",  # most recent first
        "limit": 5,  # grab a few in case the latest is "." (missing)
    }
    try:
        resp = _session.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":  # FRED signals missing data as literal "."
                try:
                    return float(val)
                except ValueError:
                    pass
    except requests.exceptions.Timeout:
        logger.warning(f"[FRED] Timeout fetching {series_id}")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        if status == 400:
            logger.warning(f"[FRED] Bad request for {series_id} — check series ID or API key")
        elif status == 429:
            logger.warning("[FRED] Rate limited (429)")
        else:
            logger.warning(f"[FRED] HTTP {status} for {series_id}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[FRED] Request error for {series_id}: {e}")
    except Exception as e:
        logger.warning(f"[FRED] Unexpected error for {series_id}: {e}")
    return None


class FREDProvider:
    """
    Fetches all configured macro series in a single fetch_all() call.

    Designed to be instantiated once in ExternalDataBus and called
    at most once per hour (TTL enforced by the bus).
    """

    # Series to fetch: (attribute_name_on_snapshot, FRED_series_id)
    _SERIES = [
        ("fed_funds_rate", "FEDFUNDS"),
        ("cpi_level", "CPIAUCSL"),
        ("core_pce_level", "PCEPILFE"),
        ("unemployment_rate", "UNRATE"),
    ]

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def fetch_all(self) -> Dict[str, Optional[float]]:
        """
        Fetch all macro series.

        Returns a dict whose keys match ExternalSnapshot field names:
            fed_funds_rate, cpi_level, core_pce_level, unemployment_rate

        Each value is a float or None. An empty dict is returned when
        api_key is not configured (caller should check before calling).
        """
        if not self._api_key:
            logger.debug("[FRED] api_key not set — skipping macro fetch")
            return {}

        logger.debug("[FRED] Fetching macro series...")
        result: Dict[str, Optional[float]] = {}
        for attr, series_id in self._SERIES:
            result[attr] = _fetch_latest_value(series_id, self._api_key)
        logger.debug(f"[FRED] Result: {result}")
        return result
