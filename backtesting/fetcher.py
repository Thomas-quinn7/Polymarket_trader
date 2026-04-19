# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

import time
import requests
from datetime import datetime
from typing import Callable, List, Optional

from utils.logger import logger
from backtesting.db import BacktestDB
from backtesting.config import BacktestConfig

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_MIN_PRICE_TICKS = 3  # skip markets with fewer than this many price data points


class HistoricalDataFetcher:
    """
    Fetches resolved markets and their YES-token price history from Gamma API.
    Cache-first: all fetched data is stored in BacktestDB and reused on subsequent runs.
    """

    def __init__(self, db: BacktestDB, rate_limit_rps: float = 3.0):
        self._db = db
        self._min_interval_s = 1.0 / rate_limit_rps
        self._last_call_ts = 0.0
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _throttle(self):
        """Block until we are allowed to make the next API call."""
        elapsed = time.monotonic() - self._last_call_ts
        wait = self._min_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    # ── Market fetching ───────────────────────────────────────────────────────

    def fetch_markets_for_range(
        self,
        config: BacktestConfig,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[str]:
        """
        Return list of condition_ids matching the config filters.

        1. Check bt_markets for sufficient cached coverage.
        2. If cache is thin, paginate Gamma API and populate cache.
        3. Apply in-memory filters and return condition_ids.
        """
        start_iso = config.start_date + "T00:00:00+00:00"
        end_iso = config.end_date + "T23:59:59+00:00"

        cached_count = self._db.count_markets_in_range(start_iso, end_iso, config.category)

        if cached_count < 50:
            if progress_callback:
                progress_callback(0, "Fetching market list from Gamma API...")
            self._paginate_markets(config, start_iso, end_iso, progress_callback)

        rows = self._db.get_markets_in_range(
            start_iso,
            end_iso,
            category=config.category,
            max_duration_s=config.max_duration_seconds,
            min_volume=config.min_volume_usd,
        )

        condition_ids = [r["condition_id"] for r in rows if r["resolution"] is not None]
        logger.info(f"[Fetcher] {len(condition_ids)} markets in range after filters")
        return condition_ids

    def _paginate_markets(
        self,
        config: BacktestConfig,
        start_iso: str,
        end_iso: str,
        progress_callback=None,
    ):
        """Page through Gamma /markets?closed=true and insert into cache."""
        offset = 0
        limit = 100
        total_inserted = 0

        while True:
            self._throttle()
            url = (
                f"{_GAMMA_BASE}/markets"
                f"?closed=true&category={config.category}"
                f"&limit={limit}&offset={offset}"
            )
            try:
                resp = self._session.get(url, timeout=15)
                resp.raise_for_status()
                markets = resp.json()
            except Exception as exc:
                logger.warning(f"[Fetcher] Market page {offset} failed: {exc}")
                break

            if not markets:
                break

            for raw in markets:
                parsed = self._parse_market(raw)
                if parsed is None:
                    continue
                if not (start_iso <= parsed["end_time"] <= end_iso):
                    continue
                self._db.upsert_market(parsed)
                total_inserted += 1

            if progress_callback:
                progress_callback(total_inserted, f"Fetched {total_inserted} markets...")

            if len(markets) < limit:
                break
            offset += limit

        logger.info(f"[Fetcher] Inserted {total_inserted} markets into cache")

    def _parse_market(self, raw: dict) -> Optional[dict]:
        """Extract and normalise fields from a raw Gamma API market dict."""
        condition_id = raw.get("conditionId") or raw.get("id")
        if not condition_id:
            return None

        clob_token_ids = raw.get("clobTokenIds") or []
        token_id_yes = clob_token_ids[0] if len(clob_token_ids) > 0 else None
        token_id_no = clob_token_ids[1] if len(clob_token_ids) > 1 else None

        end_time_str = (
            raw.get("endDate")
            or raw.get("end_date")
            or raw.get("closeTime")
            or raw.get("close_time")
        )
        created_at_str = raw.get("createdAt") or raw.get("created_at")

        duration_s = None
        if end_time_str and created_at_str:
            try:
                end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                cre_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                duration_s = int((end_dt - cre_dt).total_seconds())
            except Exception:
                pass

        # Determine resolution from outcomePrices if present.
        # For a resolved binary market the YES price is at or near 1.0 (YES won)
        # or 0.0 (NO won).  Using 0.5 as the midpoint is an objective read of
        # which outcome was awarded — it carries no strategy-specific meaning.
        # Also checks the winner/winnerOutcome field when provided by the API.
        resolution = None
        winner_field = raw.get("winner") or raw.get("winnerOutcome") or ""
        if winner_field:
            if str(winner_field).upper() in ("YES", "1", "TRUE"):
                resolution = 1.0
            elif str(winner_field).upper() in ("NO", "0", "FALSE"):
                resolution = 0.0
        if resolution is None:
            out_prices = raw.get("outcomePrices")
            if out_prices:
                try:
                    import json as _json

                    if isinstance(out_prices, str):
                        out_prices = _json.loads(out_prices)
                    yes_price = float(out_prices[0])
                    resolution = 1.0 if yes_price >= 0.5 else 0.0
                except Exception:
                    pass

        from data.market_schema import classify_category

        category = classify_category(raw.get("tags", []))

        return {
            "condition_id": str(condition_id),
            "slug": raw.get("slug") or raw.get("marketSlug") or str(condition_id),
            "question": raw.get("question") or raw.get("title") or "",
            "category": category,
            "volume": float(raw.get("volume") or raw.get("volumeClob") or 0.0),
            "end_time": end_time_str or "",
            "created_at": created_at_str,
            "resolution": resolution,
            "token_id_yes": token_id_yes,
            "token_id_no": token_id_no,
            "duration_seconds": duration_s,
        }

    # ── Price history fetching ────────────────────────────────────────────────

    def fetch_price_history(self, condition_id: str, interval: str = "5m") -> List[tuple]:
        """
        Return list of (ts, price) pairs for a market.
        Uses cache if already stored (>= 3 ticks present).
        Returns empty list if market has insufficient data.
        """
        if self._db.has_price_history(condition_id):
            return self._db.get_price_history(condition_id)

        self._throttle()
        url = f"{_GAMMA_BASE}/prices-history?market={condition_id}&interval={interval}"
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"[Fetcher] Price history for {condition_id} failed: {exc}")
            return []

        history = data.get("history", [])
        raw = []
        for point in history:
            try:
                raw.append((int(point["t"]), float(point["p"])))
            except (KeyError, ValueError, TypeError):
                continue

        # Classify the whole series once to avoid mixing units within a single
        # price history (a 0.5 tick and a 50.0 tick would map to the same value
        # under per-tick classification, masking real scale inconsistencies).
        needs_scale = raw and max(p for _, p in raw) > 1.0
        ticks = [
            (ts, p / 100.0 if needs_scale else p)
            for ts, p in raw
            if 0.0 <= (p / 100.0 if needs_scale else p) <= 1.0
        ]

        if len(ticks) < _MIN_PRICE_TICKS:
            logger.debug(f"[Fetcher] Skipping {condition_id}: only {len(ticks)} ticks")
            return []

        self._db.insert_price_history(condition_id, ticks)
        return ticks

    def prefetch_all_price_histories(
        self,
        condition_ids: List[str],
        interval: str = "5m",
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Batch-fetch price histories for all given markets.
        Skips markets already in cache.
        Returns count of markets with usable price data.
        """
        usable = 0
        for i, cid in enumerate(condition_ids):
            ticks = self.fetch_price_history(cid, interval)
            if ticks:
                usable += 1
            if progress_callback:
                progress_callback(i + 1, len(condition_ids))
        logger.info(f"[Fetcher] {usable}/{len(condition_ids)} markets have usable price history")
        return usable
