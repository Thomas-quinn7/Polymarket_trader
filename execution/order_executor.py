"""
Order Executor Module
Handles order execution with paper trading
"""

from typing import Optional, Dict, List
from datetime import datetime
import time

from py_clob_client.order_builder.constants import SELL
from utils.logger import logger, trade_logger
from utils.alerts import alert_manager
from utils.pnl_tracker import PnLTracker
from portfolio.position_tracker import PositionTracker
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from config.polymarket_config import config


class OrderExecutor:
    """
    Executes trades in paper trading mode

    Features:
    - Paper trading execution
    - Track all orders
    - Validate trades
    - Error handling and logging
    - Alert on failures
    """

    def __init__(
        self,
        pnl_tracker: PnLTracker,
        position_tracker: PositionTracker,
        currency_tracker: FakeCurrencyTracker,
        polymarket_client=None,
    ):
        self.pnl_tracker = pnl_tracker
        self.position_tracker = position_tracker
        self.currency_tracker = currency_tracker
        self.polymarket_client = polymarket_client
        self.order_history: List[Dict] = []

        # Safety check for paper trading only mode
        if config.PAPER_TRADING_ONLY:
            logger.info("Order executor initialized — paper trading only, no real money trades")
        else:
            logger.info("Order executor initialized (paper trading mode)")

    def execute_buy(
        self,
        opportunity,
        position_id: str,
    ) -> bool:
        """
        Execute a buy order (paper trading)

        Args:
            opportunity: ArbitrageOpportunity object
            position_id: Position ID

        Returns:
            True if successful
        """
        try:
            # Calculate position size (20% of starting balance)
            capital_to_allocate = self.currency_tracker.starting_balance * config.CAPITAL_SPLIT_PERCENT

            # Calculate shares
            shares = capital_to_allocate / opportunity.current_price

            # Expected profit
            expected_profit = shares * (1.00 - opportunity.current_price)

            # Place real order on exchange if live trading is enabled
            if not config.PAPER_TRADING_ONLY and self.polymarket_client is not None:
                order_response = self.polymarket_client.create_market_order(
                    token_id=opportunity.winning_token_id,
                    amount=capital_to_allocate,
                )
                if not order_response:
                    logger.error(f"Exchange rejected order for {position_id} — aborting")
                    return False
                order_status = order_response.get("status", "")
                if order_status not in ("MATCHED", "DELAYED", "LIVE"):
                    logger.error(
                        f"Order not filled for {position_id} (status={order_status!r}) — aborting"
                    )
                    return False
                # Use actual filled size if returned by the exchange
                filled_size = order_response.get("size_matched")
                if filled_size:
                    shares = float(filled_size)

            # Allocate currency
            allocated = self.currency_tracker.allocate_to_position(
                position_id=position_id,
                market_id=opportunity.market_id,
                amount=capital_to_allocate,
            )

            if not allocated:
                logger.warning(f"Failed to allocate currency for {position_id}")
                return False

            # Create position — pass the same position_id so callers can look it up
            try:
                self.position_tracker.create_position(
                    opportunity=opportunity,
                    shares=shares,
                    allocated_capital=capital_to_allocate,
                    expected_profit=expected_profit,
                    position_id=position_id,
                )
            except Exception:
                # Roll back the currency allocation so balance stays consistent
                self.currency_tracker.return_to_balance(
                    position_id=position_id,
                    return_amount=capital_to_allocate,
                )
                raise

            # Log trade
            trade_logger.log_position_opened(
                position_id=position_id,
                market_id=opportunity.market_id,
                shares=shares,
                entry_price=opportunity.current_price,
                expected_profit=expected_profit,
            )

            # Send alert
            alert_manager.send_position_opened_alert(
                position_id=position_id,
                market_id=opportunity.market_slug,
                quantity=shares,
                price=opportunity.current_price,
            )

            # Record order
            order_record = {
                "order_id": f"{position_id}_BUY",
                "position_id": position_id,
                "action": "BUY",
                "market_id": opportunity.market_id,
                "market_slug": opportunity.market_slug,
                "token_id": opportunity.winning_token_id,
                "quantity": shares,
                "price": opportunity.current_price,
                "total": capital_to_allocate,
                "executed_at": datetime.now(),
                "status": "FILLED",
            }
            self.order_history.append(order_record)

            logger.info(
                f"✅ Buy order executed: {position_id} - "
                f"{shares:.4f} shares @ ${opportunity.current_price:.4f} "
                f"(Total: ${capital_to_allocate:.2f})"
            )

            return True

        except Exception as e:
            logger.error(f"Error executing buy order for {position_id}: {e}")
            alert_manager.send_error_alert(str(e), f"Buy order execution failed for {position_id}")
            return False

    def execute_sell(
        self,
        position_id: str,
        current_price: float,
        reason: str = "manual",
    ) -> Optional[float]:
        """
        Exit a position early by selling at the current market price.

        In live mode this submits a real SELL order to Polymarket before
        updating the internal books. In paper mode it settles at current_price
        directly (no exchange call).

        Args:
            position_id: Position to close
            current_price: Current market price of the winning token
            reason: Why the sell was triggered (logged)

        Returns:
            Realised PnL or None on failure
        """
        position = self.position_tracker.get_position(position_id)
        if not position:
            logger.warning(f"execute_sell: position {position_id} not found")
            return None

        logger.info(
            f"Selling position {position_id} at ${current_price:.4f} "
            f"(entry ${position.entry_price:.4f}, reason={reason})"
        )

        # Place real SELL order when live trading is enabled
        if not config.PAPER_TRADING_ONLY and self.polymarket_client is not None:
            order_response = self.polymarket_client.create_market_order(
                token_id=position.winning_token_id,
                amount=position.shares,
                side=SELL,
            )
            if not order_response:
                logger.error(f"Exchange rejected SELL order for {position_id}")
                return None
            filled_price = order_response.get("price")
            if filled_price:
                current_price = float(filled_price)

        return self.settle_position(position_id, settlement_price=current_price)

    def settle_position(
        self,
        position_id: str,
        settlement_price: float = 1.0,  # Default to $1.00 (YES token wins)
    ) -> Optional[float]:
        """
        Settle a position (paper trading)

        Args:
            position_id: Position ID
            settlement_price: Final settlement price

        Returns:
            Realized PnL
        """
        try:
            # Get position
            position = self.position_tracker.get_position(position_id)
            if not position:
                logger.warning(f"Position {position_id} not found for settlement")
                return None

            # Calculate return amount
            return_amount = position.shares * settlement_price

            # Return to balance
            returned = self.currency_tracker.return_to_balance(
                position_id=position_id,
                return_amount=return_amount,
            )

            if not returned:
                logger.warning(f"Failed to return currency for {position_id}")

            # Settle position
            pnl = self.position_tracker.settle_position(
                position_id=position_id,
                settlement_price=settlement_price,
            )

            # Log trade
            trade_logger.log_position_closed(
                position_id=position_id,
                market_id=position.market_id,
                exit_price=settlement_price,
                realized_pnl=pnl or 0.0,
            )

            # Send alert
            alert_manager.send_position_closed_alert(
                position_id=position_id,
                market_id=position.market_slug,
                exit_price=settlement_price,
                pnl=pnl or 0.0,
            )

            # Send loss alert if applicable
            if pnl and pnl < 0:
                alert_manager.send_position_loss_alert(
                    position_id=position_id,
                    market_id=position.market_slug,
                    loss=pnl,
                )

            # Record order
            order_record = {
                "order_id": f"{position_id}_SELL",
                "position_id": position_id,
                "action": "SELL",
                "market_id": position.market_id,
                "market_slug": position.market_slug,
                "token_id": position.winning_token_id,
                "quantity": position.shares,
                "price": settlement_price,
                "total": return_amount,
                "executed_at": datetime.now(),
                "status": "FILLED",
                "pnl": pnl,
            }
            self.order_history.append(order_record)

            logger.info(
                f"✅ Position settled: {position_id} - "
                f"Exit: ${settlement_price:.4f}, "
                f"PnL: ${(pnl or 0.0):.2f}"
            )

            return pnl

        except Exception as e:
            logger.error(f"Error settling position {position_id}: {e}")
            alert_manager.send_error_alert(str(e), f"Position settlement failed for {position_id}")
            return None

    def get_order_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get order history (newest first; orders are appended chronologically)"""
        if limit:
            return self.order_history[-limit:][::-1]
        return self.order_history[::-1]

    def get_recent_orders(self, limit: int = 10) -> List[Dict]:
        """Get recent orders"""
        return self.get_order_history(limit)

    def get_execution_stats(self) -> Dict:
        """Get execution statistics"""
        total_orders = len(self.order_history)

        # Single pass over order history
        buy_count = sell_count = filled_count = 0
        total_volume = 0.0
        for o in self.order_history:
            if o["action"] == "BUY":
                buy_count += 1
            else:
                sell_count += 1
            if o["status"] == "FILLED":
                filled_count += 1
                total_volume += o["total"]

        return {
            "total_orders": total_orders,
            "buy_orders": buy_count,
            "sell_orders": sell_count,
            "filled_orders": filled_count,
            "failed_orders": total_orders - filled_count,
            "fill_rate": (filled_count / total_orders * 100) if total_orders > 0 else 0.0,
            "total_volume": total_volume,
        }

    def reset(self):
        """Reset executor"""
        self.order_history = []
        logger.info("Order executor reset")
