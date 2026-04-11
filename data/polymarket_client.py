"""
Polymarket API Client
Wrapper around py-clob-client SDK
"""

import math
import os
import random
import time as _time
from typing import List, Optional, Dict

import requests as _requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from config.polymarket_config import config
from utils.logger import logger

# Module-level Session reuses TCP connections across all PolymarketClient instances.
# This avoids the 3-way handshake + TLS negotiation overhead on every API call.
_http_session = _requests.Session()
_http_session.headers.update({"Accept": "application/json"})


def _with_retry(fn, retries: int = None, delays: tuple = None):
    """Call fn(); on exception retry up to `retries` times with jittered backoff.

    Defaults to config.MAX_RETRIES and a delay derived from config.RETRY_DELAY_MS
    so that both the executor and the client-level HTTP calls honour the same
    settings.  Callers may pass explicit values to override (e.g. tests).

    Each base delay is multiplied by a random factor in [0.5, 1.5) so that
    concurrent callers don't all hammer the API at the same instant after a
    shared error (thundering-herd prevention).
    """
    if retries is None:
        retries = config.MAX_RETRIES
    if delays is None:
        base_s = config.RETRY_DELAY_MS / 1000.0
        delays = (base_s, base_s * 5, base_s * 20)

    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                base = delays[min(attempt, len(delays) - 1)]
                delay = base * (0.5 + random.random())
                logger.warning(
                    f"Attempt {attempt + 1}/{retries} failed: {exc} — retrying in {delay:.2f}s"
                )
                _time.sleep(delay)
    raise last_exc


class PolymarketClient:
    """
    Wrapper around Polymarket's Python SDK

    Key Features:
    - SDK-based authentication (no custom signature)
    - Order book and price fetching
    - Order creation and management
    - Error handling and retries
    """

    def __init__(self):
        """Initialize Polymarket client"""
        self._simulation = config.TRADING_MODE == "simulation"
        self._sim_markets: list = []  # cache for the current sim market set
        self._sim_price_index: dict = {}  # token_id → yes_price (O(1) lookup)
        self._relayer_headers: Optional[Dict[str, str]] = None  # set in relayer mode

        if self._simulation:
            self.client = None
            logger.info("PolymarketClient running in SIMULATION mode — no API calls will be made")
            return

        self.host = config.CLOB_API_URL
        self.chain_id = config.CHAIN_ID
        self.private_key = config.POLYMARKET_PRIVATE_KEY
        self.funder_address = config.POLYMARKET_FUNDER_ADDRESS

        # Auth priority: Relayer > Builder > Standard
        if config.RELAYER_ENABLED:
            self._initialize_relayer_mode()
        elif config.BUILDER_ENABLED:
            missing = [
                name
                for name, val in (
                    ("BUILDER_API_KEY", config.BUILDER_API_KEY),
                    ("BUILDER_SECRET", config.BUILDER_SECRET),
                    ("BUILDER_PASSPHRASE", config.BUILDER_PASSPHRASE),
                )
                if not val
            ]
            if missing:
                logger.warning(
                    f"BUILDER_ENABLED=True but the following .env keys are missing or empty: "
                    f"{', '.join(missing)} — falling back to standard mode"
                )
                self._initialize_standard_mode()
                return

            try:
                from py_builder_signing_sdk import BuilderConfig, BuilderApiKeyCreds

                # Configure builder credentials for verified status
                builder_creds = BuilderApiKeyCreds(
                    key=config.BUILDER_API_KEY,
                    secret=config.BUILDER_SECRET,
                    passphrase=config.BUILDER_PASSPHRASE,
                )

                builder_config = BuilderConfig(local_builder_creds=builder_creds)

                # Initialize SDK client with credentials
                self.client = ClobClient(
                    host=self.host,
                    chain_id=self.chain_id,
                    key=self.private_key,
                    signature_type=1,  # Email/Magic wallet
                    funder=self.funder_address,
                )

                # Set user API credentials
                self.client.set_api_creds(self.client.create_or_derive_api_creds())

                # Update client with builder config
                self.client.builder_config = builder_config

                logger.info(
                    f"Polymarket client initialized with Builder credentials "
                    f"— tier: {config.builder_tier_label}"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to initialize Builder credentials: {e}, falling back to standard mode"
                )
                self._initialize_standard_mode()
        else:
            self._initialize_standard_mode()

    def _initialize_relayer_mode(self):
        """
        Initialize with Relayer API key authentication.

        Relayer keys (generated at polymarket.com/settings?tab=api-keys) provide unlimited
        relay transactions for a single wallet without tier approval. Orders are submitted
        with standard L2 CLOB headers plus RELAYER_API_KEY and RELAYER_API_KEY_ADDRESS headers.
        """
        missing = [
            name
            for name, val in (
                ("RELAYER_API_KEY", config.RELAYER_API_KEY),
                ("RELAYER_API_KEY_ADDRESS", config.RELAYER_API_KEY_ADDRESS),
            )
            if not val
        ]
        if missing:
            logger.warning(
                f"RELAYER_ENABLED=True but the following .env keys are missing or empty: "
                f"{', '.join(missing)} — falling back to standard mode"
            )
            self._initialize_standard_mode()
            return

        try:
            self.client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=self.private_key,
                signature_type=1,
                funder=self.funder_address,
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            # Store relayer headers to inject into every order submission
            self._relayer_headers = {
                "RELAYER_API_KEY": config.RELAYER_API_KEY,
                "RELAYER_API_KEY_ADDRESS": config.RELAYER_API_KEY_ADDRESS,
            }
            logger.info(
                f"Polymarket client initialized with Relayer credentials "
                f"— tier: {config.builder_tier_label}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to initialize Relayer credentials: {e} — falling back to standard mode"
            )
            self._relayer_headers = None
            self._initialize_standard_mode()

    def _initialize_standard_mode(self):
        """Initialize without builder credentials (unverified mode)"""
        try:
            self.client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=self.private_key,
                signature_type=1,  # Email/Magic wallet
                funder=self.funder_address,
            )

            # Set API credentials
            self.client.set_api_creds(self.client.create_or_derive_api_creds())

            logger.info(f"Polymarket client initialized — tier: {config.builder_tier_label}")
        except Exception as e:
            self.client = None
            logger.info(
                f"ClobClient unavailable (no valid private key) — price fetching disabled: {e}"
            )

    def get_all_markets(self, category: Optional[str] = None) -> list:  # noqa: C901
        """
        Get all active markets from Gamma API with pagination.

        Args:
            category: Optional category (crypto, fed, regulatory, economic, other)

        Returns:
            List of raw market dicts (all pages combined)
        """
        if self._simulation:
            from data.simulation_markets import generate_simulation_markets

            self._sim_markets = generate_simulation_markets(category)
            # Build O(1) price lookup index keyed by token_id
            self._sim_price_index = {
                tid: m["_sim_yes_price"]
                for m in self._sim_markets
                if m.get("clobTokenIds")
                for tid in m["clobTokenIds"]
            }
            logger.debug(
                f"[SIM] Generated {len(self._sim_markets)} synthetic markets (category={category})"
            )
            return self._sim_markets

        import json as _json

        tag_map = {"crypto": "21", "fed": "7"}
        all_markets: list = []
        page_size = 100
        offset = 0

        while True:
            params = {"active": "true", "closed": "false", "limit": page_size, "offset": offset}
            if category in tag_map:
                params["tag_id"] = tag_map[category]

            try:
                response = _with_retry(
                    lambda: _http_session.get(
                        f"{config.GAMMA_API_URL}/events",
                        params=params,
                        timeout=10,
                    )
                )
            except _requests.exceptions.Timeout:
                logger.error(
                    f"Timeout fetching markets page (offset={offset}) for category '{category}'"
                )
                break
            except _requests.exceptions.RequestException as e:
                logger.error(
                    f"Request error fetching markets page (offset={offset}) for category '{category}': {e}"
                )
                break

            if response.status_code != 200:
                logger.warning(
                    f"Gamma API returned {response.status_code} for category '{category}' "
                    f"(offset={offset}): {response.text[:200]}"
                )
                break

            try:
                events = response.json()
            except ValueError as e:
                logger.error(
                    f"Failed to parse Gamma API response for category '{category}' (offset={offset}): {e}"
                )
                break

            if not isinstance(events, list):
                logger.warning(f"Unexpected Gamma API response type: {type(events)}")
                break

            # Flatten events → markets, attach event tags, parse clobTokenIds
            page_markets = []
            for event in events:
                event_tags = event.get("tags", [])
                for market in event.get("markets", []):
                    if not market.get("active") or market.get("closed"):
                        continue
                    market["tags"] = event_tags
                    clob = market.get("clobTokenIds")
                    if isinstance(clob, str):
                        try:
                            market["clobTokenIds"] = _json.loads(clob)
                        except Exception:
                            market["clobTokenIds"] = []
                    page_markets.append(market)

            all_markets.extend(page_markets)

            # Stop only when the API returned fewer events than requested —
            # that is the authoritative signal that there are no more pages.
            # A full page whose markets all happen to be closed/inactive is NOT
            # a stop signal: the next page may contain active markets.
            if len(events) < page_size:
                break

            offset += page_size

        logger.info(f"Fetched {len(all_markets)} total markets for category '{category}'")
        return all_markets

    def get_market(self, market_id: str) -> dict:
        """
        Get specific market details

        Args:
            market_id: Market token ID

        Returns:
            Market dictionary
        """
        try:
            response = _with_retry(
                lambda: _http_session.get(
                    f"{config.GAMMA_API_URL}/markets?token_id={market_id}",
                    timeout=10,
                )
            )

            if response.status_code == 200:
                return response.json()

            logger.error(f"Error fetching market {market_id}: {response.status_code}")
            return {}

        except Exception as e:
            logger.error(f"Error fetching market {market_id}: {e}")
            return {}

    def get_price(self, token_id: str) -> float:
        """
        Get current price of a token

        Args:
            token_id: Token ID to query

        Returns:
            Current price in dollars (0-100)
        """
        if self._simulation:
            return self._sim_price_index.get(token_id, 0.0)
        if self.client is None:
            return 0.0
        try:
            result = self.client.get_price(token_id, side="BUY")
            # CLOB client may return a dict {"price": "0.97"}, a str, or a float
            if isinstance(result, dict):
                raw = float(result.get("price", 0) or 0)
            else:
                raw = float(result) if result else 0.0
            # Reject NaN / Infinity — these propagate silently into calculations
            if not math.isfinite(raw):
                logger.warning(f"Non-finite price {raw!r} for {token_id} — treating as 0")
                return 0.0
            return raw
        except Exception as e:
            logger.error(f"Error fetching price for {token_id}: {e}")
            return 0.0

    def get_order_book(self, token_id: str, levels: int = 5) -> dict:
        """
        Get order book for a token.

        Args:
            token_id: Token ID
            levels: Number of bid/ask levels to return (default 5)

        Returns:
            Dict with ``bids`` (high→low), ``asks`` (low→high), ``mid_price``.
            Each level is ``{"price": float, "size": float}``.
        """
        if self._simulation:
            from data.simulation_markets import generate_sim_order_book

            mid = self._sim_price_index.get(token_id, 0.5)
            return generate_sim_order_book(token_id, mid, levels=levels)

        if self.client is None:
            return {"bids": [], "asks": [], "mid_price": 0.0}
        try:
            book = self.client.get_order_book(token_id)
            raw_bids = book.get("bids", []) if isinstance(book, dict) else getattr(book, "bids", [])
            raw_asks = book.get("asks", []) if isinstance(book, dict) else getattr(book, "asks", [])

            def _normalise(levels_raw):
                out = []
                for lvl in levels_raw:
                    if isinstance(lvl, dict):
                        out.append(
                            {"price": float(lvl.get("price", 0)), "size": float(lvl.get("size", 0))}
                        )
                    else:
                        out.append(
                            {
                                "price": float(getattr(lvl, "price", 0)),
                                "size": float(getattr(lvl, "size", 0)),
                            }
                        )
                return out

            mid_price = float(self.client.get_midpoint(token_id))
            return {
                "bids": _normalise(raw_bids)[:levels],
                "asks": _normalise(raw_asks)[:levels],
                "mid_price": mid_price,
            }
        except Exception as e:
            logger.error(f"Error fetching order book for {token_id}: {e}")
            return {"bids": [], "asks": [], "mid_price": 0.0}

    def create_market_order(
        self,
        token_id: str,
        amount: float,
        price: Optional[float] = None,
        side: str = BUY,
        neg_risk: bool = False,
    ) -> dict:
        """
        Create and submit a market order (FOK).

        Args:
            token_id:  Token ID to trade.
            amount:    Dollar amount (BUY) or share count (SELL).
            price:     Optional price cap. None → SDK uses best available.
            side:      BUY or SELL (default BUY).
            neg_risk:  Whether the market uses neg-risk (inverse) settlement.
                       Must match the market's actual type — an incorrect value
                       corrupts the order hash and the exchange will reject the
                       order.  Callers should pass this from market data; the
                       default False is correct for standard (non-neg-risk) markets.

        Returns:
            Order response dict from Polymarket, or {} on failure.

        Safety:
            This method is split into two isolated phases so that retries always
            reuse the same signed order (same salt) rather than generating new ones:

            Phase 1 — Signing (local, no exchange side-effects).  Safe to fail;
                      returns {} without submitting anything.
            Phase 2 — Submission (exchange side-effect).  _with_retry reuses the
                      same signed_order so the exchange deduplicates by salt.
                      If all retries fail we return {}.  The executor must NOT
                      retry at the caller level after this returns {} — doing so
                      would create a new signed order with a new salt and risk
                      a double-spend.
        """
        # Defense-in-depth: refuse to submit if paper mode is active.
        # The executor already gates on PAPER_TRADING_ONLY; this guard catches
        # any future code path that calls create_market_order directly without
        # checking the flag.
        if config.PAPER_TRADING_ONLY:
            logger.error(
                "SAFETY: create_market_order called while PAPER_TRADING_ONLY=True "
                "— refusing to submit. This is a bug in the calling code."
            )
            return {}

        if self.client is None:
            logger.warning("ClobClient not initialized — order not submitted")
            return {}

        # ── Phase 1: Sign the order locally (no exchange side-effects) ────────
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                price=price or 0,
                side=side,
                order_type=OrderType.FOK,
            )
            signed_order = self.client.create_market_order(order_args)
        except Exception as e:
            logger.error(f"Order signing failed for {token_id}: {e}")
            return {}

        # ── Phase 2: Submit to exchange (retries reuse the SAME signed order) ──
        try:
            if self._relayer_headers:
                # Relayer mode: submit to the relayer endpoint with L2 CLOB headers
                # merged with RELAYER_API_KEY / RELAYER_API_KEY_ADDRESS headers so
                # that orders are attributed to the relayer account (unlimited relay
                # transactions, no tier approval required).
                import json as _json
                from py_clob_client.headers.headers import create_level_2_headers
                from py_clob_client.clob_types import RequestArgs
                from py_clob_client.utilities import order_to_json

                _RELAYER_URL = "https://relayer-v2.polymarket.com"
                _ORDER_PATH = "/order"

                # neg_risk must match the actual market type — see docstring.
                body = order_to_json(
                    signed_order, self.client.creds.api_key, OrderType.FOK, neg_risk
                )
                serialized = _json.dumps(body, separators=(",", ":"), ensure_ascii=False)
                req_args = RequestArgs(
                    method="POST",
                    request_path=_ORDER_PATH,
                    body=body,
                    serialized_body=serialized,
                )
                l2_headers = create_level_2_headers(self.client.signer, self.client.creds, req_args)
                # Content-Type is required; the relayer will reject/misparse the body without it.
                merged_headers = {
                    "Content-Type": "application/json",
                    **l2_headers,
                    **self._relayer_headers,
                }

                def _submit_via_relayer():
                    resp = _http_session.post(
                        f"{_RELAYER_URL}{_ORDER_PATH}",
                        headers=merged_headers,
                        data=serialized,
                        timeout=10,
                    )
                    if not resp.ok:
                        raise RuntimeError(
                            f"Relayer returned {resp.status_code}: {resp.text[:200]}"
                        )
                    return resp.json()

                response = _with_retry(_submit_via_relayer)
            else:
                response = _with_retry(lambda: self.client.post_order(signed_order, OrderType.FOK))
        except Exception as e:
            # All retries exhausted — the order was NOT successfully submitted.
            logger.error(f"Order submission failed for {token_id} after all retries: {e}")
            return {}

        result = response if isinstance(response, dict) else {}
        logger.info(
            f"Order submitted: {side} {token_id[:16]}… amount={amount:.4f} "
            f"price={price} status={result.get('status')}"
        )
        return result

    def get_order(self, order_id: str) -> dict:
        """
        Get order status

        Args:
            order_id: Order ID

        Returns:
            Order status
        """
        if self.client is None:
            return {}
        try:
            return self.client.get_order(order_id)
        except Exception as e:
            logger.error(f"Error fetching order {order_id}: {e}")
            return {}

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order

        Args:
            order_id: Order ID

        Returns:
            True if successful
        """
        if self.client is None:
            return False
        try:
            self.client.cancel(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    def get_positions(self) -> list:
        """
        Get all open positions (orders)

        Returns:
            List of open orders
        """
        if self.client is None:
            return []
        try:
            from py_clob_client.clob_types import OpenOrderParams

            orders = self.client.get_orders(OpenOrderParams())

            # Filter for live (open) orders — Polymarket uses "LIVE" not "OPEN"
            open_orders = [o for o in orders if o.get("status") in ("LIVE", "OPEN", "UNMATCHED")]

            return open_orders

        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
