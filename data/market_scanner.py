"""
Multi-category market scanner.

Fetches markets from multiple Polymarket categories in parallel threads and
returns a single deduplicated list.  Strategies call this instead of
PolymarketClient.get_all_markets() directly so they automatically get broad
coverage without incurring sequential latency.
"""

import threading
import time
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

    threads = [
        threading.Thread(target=_fetch, args=(cat,), daemon=True, name=f"scanner-{cat}")
        for cat in categories
    ]
    for t in threads:
        t.start()
    # Use a single shared deadline so sequential joins on parallel threads do
    # not compound: if there are 4 threads and each gets a fresh 30s window,
    # a slow network could block up to 4 × 30 = 120s.  With a shared deadline
    # the total wall-clock wait is capped at 30s regardless of thread count.
    deadline = time.monotonic() + 30
    for t in threads:
        remaining = max(0.0, deadline - time.monotonic())
        t.join(timeout=remaining)
        if t.is_alive():
            logger.warning(
                "market_scanner: thread '%s' did not finish within 30s — "
                "results for this category will be empty",
                t.name,
            )

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
