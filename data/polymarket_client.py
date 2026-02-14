"""
Polymarket API Client
Wrapper around py-clob-client SDK
"""

from typing import List, Optional, Dict
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY
import os
from utils.logger import logger

from config.polymarket_config import config


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
        self.host = config.CLOB_API_URL
        self.chain_id = config.CHAIN_ID
        self.private_key = config.POLYMARKET_PRIVATE_KEY
        self.funder_address = config.POLYMARKET_FUNDER_ADDRESS

        # Initialize SDK client
        self.client = ClobClient(self.host)

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

                # Set user API credentials
                self.client.set_api_creds(
                    self.client.create_or_derive_api_creds(
                        key=self.private_key,
                        chain_id=self.chain_id,
                        signature_type=1,  # Email/Magic wallet
                        funder=self.funder_address,
                    )
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
        # Set API credentials
        self.client.set_api_creds(
            self.client.create_or_derive_api_creds(
                key=self.private_key,
                chain_id=self.chain_id,
                signature_type=1,  # Email/Magic wallet
                funder=self.funder_address,
            )
        )

        logger.info("Polymarket client initialized (unverified mode - 200 req/day limit)")

    def get_all_markets(self, category: Optional[str] = None) -> list:
        """
        Get all active markets from Gamma API

        Args:
            category: Optional category (crypto, fed, regulatory, economic, other)

        Returns:
            List of market objects
        """
        try:
            import requests
            from config.polymarket_config import config

            if category == "crypto":
                # Crypto markets
                response = requests.get(
                    f"{config.GAMMA_API_URL}/events",
                    params={
                        "active": "true",
                        "closed": "false",
                        "tag_id": "21",  # Crypto tag
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    if "data" in data:
                        return data["data"]

            elif category == "fed":
                # FED decisions
                response = requests.get(
                    f"{config.GAMMA_API_URL}/events",
                    params={
                        "active": "true",
                        "closed": "false",
                        "tag_id": "7",  # FED tag (check actual)
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    if "data" in data:
                        return data["data"]

            # Default: get all markets
            response = requests.get(
                f"{config.GAMMA_API_URL}/events",
                params={"active": "true", "closed": "false"},
            )

            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    return data["data"]

            logger.warning(
                f"Failed to get markets for category {category}: {response.status_code}"
            )
            return []

        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

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
        try:
            return self.client.get_price(token_id, side="BUY")
        except Exception as e:
            logger.error(f"Error fetching price for {token_id}: {e}")
            return 0.0

    def get_order_book(self, token_id: str) -> dict:
        """
        Get order book for a token

        Args:
            token_id: Token ID

        Returns:
            Order book with bids and asks
        """
        try:
            book = self.client.get_order_book(token_id)
            return {
                "bids": book["bids"][:10],  # Top 10 bids
                "asks": book["asks"][:10],  # Top 10 asks
                "mid_price": self.client.get_midpoint(token_id),
            }
        except Exception as e:
            logger.error(f"Error fetching order book for {token_id}: {e}")
            return {"bids": [], "asks": [], "mid_price": 0.0}

    def create_market_order(
        self, token_id: str, amount: float, price: Optional[float] = None
    ) -> dict:
        """
        Create a market order (FOK)

        Args:
            token_id: Token ID to buy
            amount: Number of shares
            price: Optional price (None for market order)

        Returns:
            Order response
        """
        try:
            from config.polymarket_config import config

            # Create order arguments
            if price is None:
                # Market order (no price specified)
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount,
                    side=BUY,
                    order_type=OrderType.FOK,  # Fill or Kill
                )
            else:
                # Limit order (not used for arbitrage but available)
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    price=price,
                    size=set(amount),
                    side=BUY,
                    order_type=OrderType.FOK,
                )

            # Sign order
            signed_order = self.client.create_market_order(order_args)

            # Submit to Polymarket
            response = self.client.post_order(signed_order, OrderType.FOK)

            logger.info(f"Order created: {token_id}, amount: {amount}, price: {price}")
            return response

        except Exception as e:
            logger.error(f"Error creating order for {token_id}: {e}")
            return {}

    def get_order(self, order_id: str) -> dict:
        """
        Get order status

        Args:
            order_id: Order ID

        Returns:
            Order status
        """
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
        try:
            from py_clob_client.clob_types import OpenOrderParams

            orders = self.client.get_orders(OpenOrderParams())

            # Filter for open orders only
            open_orders = [o for o in orders if o.get("status") == "OPEN"]

            return open_orders

        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
