"""
Order Executor Module
Handles order execution with paper trading
"""

from typing import Optional, Dict, List
from datetime import datetime
import time

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
    ):
        self.pnl_tracker = pnl_tracker
        self.position_tracker = position_tracker
        self.currency_tracker = currency_tracker
        self.order_history: List[Dict] = []

        # Safety check for paper trading only mode
        if config.PAPER_TRADING_ONLY:
            logger.info("Order executor initialized (PAPER TRADING ONLY MODE)")
            logger.warning("🔒 SAFETY MODE: Only paper trading is allowed - no real money trades")
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

            # Allocate currency
            allocated = self.currency_tracker.allocate_to_position(
                position_id=position_id,
                market_id=opportunity.market_id,
                amount=capital_to_allocate,
            )

            if not allocated:
                logger.warning(f"Failed to allocate currency for {position_id}")
                return False

            # Create position
            self.position_tracker.create_position(
                opportunity=opportunity,
                shares=shares,
                allocated_capital=capital_to_allocate,
                expected_profit=expected_profit,
            )

            # Log trade
            trade_logger.log_position_opened(
                position_id=position_id,
                market_id=opportunity.market_id,
                quantity=shares,
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
                f"PnL: ${pnl:.2f if pnl else 0:.2f}"
            )

            return pnl

        except Exception as e:
            logger.error(f"Error settling position {position_id}: {e}")
            alert_manager.send_error_alert(str(e), f"Position settlement failed for {position_id}")
            return None

    def get_order_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get order history"""
        orders = sorted(self.order_history, key=lambda x: x["executed_at"], reverse=True)

        if limit:
            return orders[:limit]

        return orders

    def get_recent_orders(self, limit: int = 10) -> List[Dict]:
        """Get recent orders"""
        return self.get_order_history(limit)

    def get_execution_stats(self) -> Dict:
        """Get execution statistics"""
        total_orders = len(self.order_history)
        buy_orders = [o for o in self.order_history if o["action"] == "BUY"]
        sell_orders = [o for o in self.order_history if o["action"] == "SELL"]

        filled_orders = [o for o in self.order_history if o["status"] == "FILLED"]
        failed_orders = [o for o in self.order_history if o["status"] != "FILLED"]

        total_volume = sum(o["total"] for o in filled_orders)

        return {
            "total_orders": total_orders,
            "buy_orders": len(buy_orders),
            "sell_orders": len(sell_orders),
            "filled_orders": len(filled_orders),
            "failed_orders": len(failed_orders),
            "fill_rate": (len(filled_orders) / total_orders * 100) if total_orders > 0 else 0.0,
            "total_volume": total_volume,
        }

    def reset(self):
        """Reset executor"""
        self.order_history = []
        logger.info("Order executor reset")
