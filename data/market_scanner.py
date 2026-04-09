"""
Multi-category market scanner.

Fetches markets from multiple Polymarket categories in parallel threads and
returns a single deduplicated list.  Strategies call this instead of
PolymarketClient.get_all_markets() directly so they automatically get broad
coverage without incurring sequential latency.
"""

import threading
from typing import List, Optional

from utils.logger import logger

# All standard Polymarket categories the Gamma API supports
ALL_CATEGORIES: List[str] = ["crypto", "fed", "regulatory", "other"]


def scan_categories(
    client,
    categories: Optional[List[str]] = None,
    deduplicate: bool = True,
) -> list:
    """
    Fetch markets for multiple categories in parallel and return a merged list.

    Args:
        client:       Initialised PolymarketClient instance.
        categories:   Categories to scan. Defaults to ALL_CATEGORIES.
        deduplicate:  Remove markets that appear in more than one category
                      response (identified by market id or slug).

    Returns:
        Merged list of raw market dicts from the Gamma API.
    """
    if categories is None:
        categories = ALL_CATEGORIES

    results: dict = {}
    lock = threading.Lock()

    def _fetch(cat: str) -> None:
        try:
            markets = client.get_all_markets(category=cat)
            with lock:
                results[cat] = markets
        except Exception as exc:
            logger.warning("market_scanner: failed to fetch '%s': %s", cat, exc)
            with lock:
                results[cat] = []

    threads = [threading.Thread(target=_fetch, args=(cat,), daemon=True) for cat in categories]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    merged: list = []
    seen_ids: set = set()

    for cat in categories:
        for market in results.get(cat, []):
            mid = market.get("id") or market.get("slug")
            if deduplicate and mid:
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
            merged.append(market)

    raw_total = sum(len(v) for v in results.values())
    logger.info(
        "market_scanner: %d unique markets across %d categories (raw total: %d)",
        len(merged),
        len(categories),
        raw_total,
    )
    return merged
