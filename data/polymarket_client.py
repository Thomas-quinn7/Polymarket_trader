"""
Polymarket API Client
Wrapper around py-clob-client SDK
"""

from typing import List, Optional, Dict
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
import os
import time as _time
from utils.logger import logger

from config.polymarket_config import config


def _with_retry(fn, retries: int = 3, delays: tuple = (0.1, 0.5, 2.0)):
    """Call fn(); on exception retry up to `retries` times with backoff."""
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    f"Attempt {attempt + 1}/{retries} failed: {exc} — retrying in {delay}s"
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

        if self._simulation:
            self.client = None
            logger.info("PolymarketClient running in SIMULATION mode — no API calls will be made")
            return

        self.host = config.CLOB_API_URL
        self.chain_id = config.CHAIN_ID
        self.private_key = config.POLYMARKET_PRIVATE_KEY
        self.funder_address = config.POLYMARKET_FUNDER_ADDRESS

        # Check if builder credentials are configured
        if config.BUILDER_ENABLED:
            try:
                from py_builder_signing_sdk import BuilderConfig, BuilderApiKeyCreds

                # Configure builder credentials for verified status
                builder_creds = BuilderApiKeyCreds(
                    key=config.BUILDER_API_KEY,
                    secret=config.BUILDER_SECRET,
                    passphrase=config.BUILDER_PASSPHRASE,
                )

                builder_config = BuilderConfig(
                    local_builder_creds=builder_creds
                )

                # Initialize SDK client with credentials
                self.client = ClobClient(
                    host=self.host,
                    chain_id=self.chain_id,
                    key=self.private_key,
                    signature_type=1,  # Email/Magic wallet
                    funder=self.funder_address,
                )

                # Set user API credentials
                self.client.set_api_creds(
                    self.client.create_or_derive_api_creds()
                )

                # Update client with builder config
                self.client.builder_config = builder_config

                logger.info("Polymarket client initialized with Builder credentials (verified mode)")

            except Exception as e:
                logger.warning(f"Failed to initialize Builder credentials: {e}, falling back to standard mode")
                self._initialize_standard_mode()
        else:
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
            self.client.set_api_creds(
                self.client.create_or_derive_api_creds()
            )

            logger.info("Polymarket client initialized (unverified mode - 200 req/day limit)")
        except Exception as e:
            self.client = None
            logger.info(f"ClobClient unavailable (no valid private key) — price fetching disabled: {e}")

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
            logger.debug(f"[SIM] Generated {len(self._sim_markets)} synthetic markets (category={category})")
            return self._sim_markets

        import requests
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
                    lambda: requests.get(
                        f"{config.GAMMA_API_URL}/events",
                        params=params,
                        timeout=10,
                    )
                )
            except requests.exceptions.Timeout:
                logger.error(f"Timeout fetching markets page (offset={offset}) for category '{category}'")
                break
            except Exception as e:
                logger.error(f"Request error fetching markets page (offset={offset}) for category '{category}': {e}")
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
                logger.error(f"Failed to parse Gamma API response for category '{category}' (offset={offset}): {e}")
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

            # Stop when the API returned a short page (last page of events)
            # or when a full page yielded no active markets (all filtered out)
            if len(events) < page_size or not page_markets:
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
            import requests
            from config.polymarket_config import config

            response = requests.get(
                f"{config.GAMMA_API_URL}/markets?token_id={market_id}"
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
            # Look up the baked-in price from the last generated market set
            for m in self._sim_markets:
                if m.get("clobTokenIds") and m["clobTokenIds"][0] == token_id:
                    return m["_sim_yes_price"]
            return 0.0
        if self.client is None:
            return 0.0
        try:
            return self.client.get_price(token_id, side="BUY")
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
            mid = 0.5
            for m in self._sim_markets:
                if m.get("clobTokenIds") and token_id in m["clobTokenIds"]:
                    mid = m["_sim_yes_price"]
                    break
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
                        out.append({"price": float(lvl.get("price", 0)), "size": float(lvl.get("size", 0))})
                    else:
                        out.append({"price": float(getattr(lvl, "price", 0)), "size": float(getattr(lvl, "size", 0))})
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
        self, token_id: str, amount: float, price: Optional[float] = None, side: str = BUY
    ) -> dict:
        """
        Create and submit a market order (FOK).

        Args:
            token_id: Token ID to trade
            amount: Dollar amount (BUY) or shares (SELL)
            price: Optional price cap; if None the SDK calculates best market price
            side: BUY or SELL (default BUY)

        Returns:
            Order response dict from Polymarket, or {} on failure
        """
        if self.client is None:
            logger.warning("ClobClient not initialized — order not submitted")
            return {}
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                price=price or 0,
                side=side,
                order_type=OrderType.FOK,
            )

            signed_order = self.client.create_market_order(order_args)
            response = _with_retry(
                lambda: self.client.post_order(signed_order, OrderType.FOK),
                retries=3,
                delays=(0.1, 0.5, 2.0),
            )

            logger.info(
                f"Order submitted: {side} {token_id[:16]}… amount={amount:.4f} "
                f"price={price} status={response.get('status') if isinstance(response, dict) else response}"
            )
            return response if isinstance(response, dict) else {}

        except Exception as e:
            logger.error(f"Error submitting order for {token_id}: {e}")
            return {}

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
