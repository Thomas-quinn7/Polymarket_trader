"""
Order Executor Module
Handles order execution with paper trading
"""

import math
import time
from collections import deque
from datetime import datetime
from typing import Optional, Dict, List

from py_clob_client.order_builder.constants import SELL
from utils.logger import logger, trade_logger
from utils.alerts import alert_manager
from utils.slippage import estimate_slippage, liquidity_available_usd
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
        # Bounded deque: keeps the last 500 orders, O(1) append and bounded memory.
        self.order_history: deque = deque(maxlen=500)

        if config.PAPER_TRADING_ONLY:
            logger.info("Order executor initialized — PAPER mode (no real money trades)")
        else:
            logger.warning(
                "Order executor initialized — LIVE mode: real orders WILL be submitted to Polymarket"
            )

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
            # Size each position as a fixed fraction of currently available cash so
            # that position sizes scale down naturally after drawdowns instead of
            # attempting to allocate a fixed dollar amount that may exceed the balance.
            capital_to_allocate = (
                self.currency_tracker.get_available() * config.CAPITAL_SPLIT_PERCENT
            )

            # Guard: invalid price means we cannot safely size the position
            if not opportunity.current_price or opportunity.current_price <= 0:
                logger.error(
                    f"Invalid price {opportunity.current_price!r} for {position_id} — aborting buy"
                )
                return False

            # ── Pre-trade slippage estimate from real order book ───────────
            # Fetch the live order book and walk the ask side to estimate how
            # much price impact our order will have given current liquidity.
            # In paper mode this becomes the recorded simulated slippage.
            # In live mode it acts as a pre-trade gate AND we still compare the
            # actual filled price post-trade as a second safety check.
            slippage_pct = 0.0
            order_book: dict = {}
            if self.polymarket_client is not None:
                try:
                    order_book = self.polymarket_client.get_order_book(
                        opportunity.winning_token_id, levels=10
                    )
                    slip_est = estimate_slippage(order_book, capital_to_allocate, side="BUY")
                    slippage_pct = slip_est["slippage_pct"]

                    total_liquidity = liquidity_available_usd(order_book, side="BUY")
                    logger.debug(
                        f"Pre-trade estimate for {position_id}: "
                        f"VWAP=${slip_est['vwap']:.4f} "
                        f"(best ask=${slip_est['best_price']:.4f}), "
                        f"estimated slippage={slippage_pct:.3f}%, "
                        f"book liquidity=${total_liquidity:.2f}, "
                        f"levels consumed={slip_est['levels_consumed']}"
                    )

                    if slip_est["insufficient_liquidity"]:
                        logger.warning(
                            f"Thin book for {position_id}: only ${total_liquidity:.2f} "
                            f"available vs ${capital_to_allocate:.2f} order size — "
                            f"${slip_est['unfilled_usd']:.2f} would not fill"
                        )

                    if slippage_pct > config.SLIPPAGE_TOLERANCE_PERCENT:
                        logger.warning(
                            f"Pre-trade slippage estimate {slippage_pct:.2f}% exceeds tolerance "
                            f"{config.SLIPPAGE_TOLERANCE_PERCENT:.1f}% for {position_id} — aborting"
                        )
                        return False

                except Exception as exc:
                    # Non-fatal: if the order book fetch fails we proceed without
                    # the estimate rather than blocking the trade entirely.
                    logger.warning(
                        f"Could not fetch order book for pre-trade estimate "
                        f"({position_id}): {exc} — proceeding without slippage gate"
                    )

            # Calculate shares and expected profit
            shares = capital_to_allocate / opportunity.current_price
            expected_profit = capital_to_allocate * (opportunity.edge_percent / 100.0)

            # Simulate entry fee (paper) / record actual fee (live)
            entry_fee = capital_to_allocate * (config.TAKER_FEE_PERCENT / 100.0)

            # Place real order on exchange if live trading is enabled
            if not config.PAPER_TRADING_ONLY and self.polymarket_client is not None:
                order_response = None
                retry_delay = config.RETRY_DELAY_MS / 1000.0
                for attempt in range(1, config.MAX_RETRIES + 1):
                    try:
                        order_response = self.polymarket_client.create_market_order(
                            token_id=opportunity.winning_token_id,
                            amount=capital_to_allocate,
                        )
                        if order_response:
                            break
                    except Exception as exc:
                        logger.warning(
                            f"Order attempt {attempt}/{config.MAX_RETRIES} failed for "
                            f"{position_id}: {exc}"
                        )
                    if attempt < config.MAX_RETRIES:
                        time.sleep(retry_delay)

                if not order_response:
                    logger.error(
                        f"Exchange rejected order for {position_id} after "
                        f"{config.MAX_RETRIES} attempt(s) — aborting"
                    )
                    return False
                order_status = order_response.get("status", "")
                if order_status not in ("MATCHED", "DELAYED", "LIVE"):
                    logger.error(
                        f"Order not filled for {position_id} (status={order_status!r}) — aborting"
                    )
                    return False

                # Extract filled price and enforce slippage tolerance.
                # Sign convention: positive = paid MORE than expected (adverse for buyer),
                # negative = paid LESS than expected (favourable for buyer).
                # Only positive (adverse) slippage is checked against the tolerance.
                filled_price_raw = order_response.get("price") or order_response.get(
                    "average_price"
                )
                if filled_price_raw:
                    try:
                        filled_price = float(filled_price_raw)
                        if filled_price > 0:
                            slippage_pct = (
                                (filled_price - opportunity.current_price)
                                / opportunity.current_price
                                * 100
                            )
                            # Reject only if we paid more than the tolerance allows.
                            # Favourable fills (slippage_pct < 0) always pass.
                            if slippage_pct > config.SLIPPAGE_TOLERANCE_PERCENT:
                                logger.error(
                                    f"Adverse slippage {slippage_pct:.2f}% exceeds tolerance "
                                    f"{config.SLIPPAGE_TOLERANCE_PERCENT:.1f}% for {position_id} "
                                    f"(expected ${opportunity.current_price:.4f}, "
                                    f"filled ${filled_price:.4f}) — aborting"
                                )
                                return False
                            if abs(slippage_pct) > 0.01:
                                direction = "adverse" if slippage_pct > 0 else "favourable"
                                logger.info(
                                    f"Slippage for {position_id}: {slippage_pct:+.2f}% "
                                    f"({direction}, expected ${opportunity.current_price:.4f}, "
                                    f"filled ${filled_price:.4f})"
                                )
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse filled price={filled_price_raw!r}")

                # Use actual filled size if returned by the exchange.
                filled_size = order_response.get("size_matched")
                if filled_size is not None:
                    try:
                        parsed = float(filled_size)
                        if parsed > 0:
                            shares = parsed
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Could not parse size_matched={filled_size!r}, using estimated shares"
                        )

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
                    entry_fee=entry_fee,
                    slippage_pct=slippage_pct,
                )
            except Exception:
                # Roll back the currency allocation so balance stays consistent
                rolled_back = self.currency_tracker.return_to_balance(
                    position_id=position_id,
                    return_amount=capital_to_allocate,
                )
                if not rolled_back:
                    logger.critical(
                        f"BALANCE INCONSISTENCY: could not roll back ${capital_to_allocate:.2f} "
                        f"for {position_id} after position creation failure — "
                        f"deployed capital and balance are now out of sync"
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
                "fee": entry_fee,
                "slippage_pct": slippage_pct,
                "executed_at": datetime.now(),
                "status": "FILLED",
            }
            self.order_history.append(order_record)

            fee_str = f" | fee ${entry_fee:.2f}" if entry_fee > 0 else ""
            slip_str = f" | slippage {slippage_pct:+.2f}%" if abs(slippage_pct) > 0.01 else ""
            logger.info(
                f"✅ Buy order executed: {position_id} - "
                f"{shares:.4f} shares @ ${opportunity.current_price:.4f} "
                f"(Total: ${capital_to_allocate:.2f}{fee_str}{slip_str})"
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
            order_response = None
            retry_delay = config.RETRY_DELAY_MS / 1000.0
            for attempt in range(1, config.MAX_RETRIES + 1):
                try:
                    order_response = self.polymarket_client.create_market_order(
                        token_id=position.winning_token_id,
                        amount=position.shares,
                        side=SELL,
                    )
                    if order_response:
                        break
                except Exception as exc:
                    logger.warning(
                        f"SELL attempt {attempt}/{config.MAX_RETRIES} failed for "
                        f"{position_id}: {exc}"
                    )
                if attempt < config.MAX_RETRIES:
                    time.sleep(retry_delay)

            if not order_response:
                logger.error(
                    f"Exchange rejected SELL order for {position_id} after "
                    f"{config.MAX_RETRIES} attempt(s)"
                )
                return None
            filled_price = order_response.get("price")
            if filled_price:
                current_price = float(filled_price)

        return self.settle_position(position_id, settlement_price=current_price)

    def settle_position(
        self,
        position_id: str,
        settlement_price: float = 0.0,
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

            # Clamp settlement price to [0, 1] — Polymarket tokens can only
            # resolve to values in this range; anything outside is a bad input.
            if not math.isfinite(settlement_price) or settlement_price < 0:
                logger.warning(
                    f"Invalid settlement price {settlement_price!r} for {position_id} "
                    f"— clamping to 0"
                )
                settlement_price = 0.0
            elif settlement_price > 1.0:
                logger.warning(
                    f"Settlement price {settlement_price:.4f} > 1.0 for {position_id} "
                    f"— clamping to 1.0"
                )
                settlement_price = 1.0

            # Calculate gross return and fees
            gross_return = position.shares * settlement_price
            exit_fee = gross_return * (config.TAKER_FEE_PERCENT / 100.0)
            # Deduct both exit fee and entry fee (originally paid at open) from the return
            net_return = gross_return - exit_fee - position.entry_fee

            # Return net proceeds to balance
            returned = self.currency_tracker.return_to_balance(
                position_id=position_id,
                return_amount=net_return,
            )

            if not returned:
                logger.warning(f"Failed to return currency for {position_id}")

            # Settle position (passes exit_fee so PnL tracker computes net correctly)
            pnl = self.position_tracker.settle_position(
                position_id=position_id,
                settlement_price=settlement_price,
                exit_fee=exit_fee,
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

            total_fees = position.entry_fee + exit_fee
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
                "total": net_return,
                "fee": exit_fee,
                "total_fees": total_fees,
                "gross_pnl": position.gross_pnl,
                "slippage_pct": 0.0,
                "executed_at": datetime.now(),
                "status": "FILLED",
                "pnl": pnl,
            }
            self.order_history.append(order_record)

            fee_str = f" | fees ${total_fees:.2f}" if total_fees > 0 else ""
            logger.info(
                f"✅ Position settled: {position_id} - "
                f"Exit: ${settlement_price:.4f}, "
                f"Gross: ${(position.gross_pnl or 0.0):.2f}, "
                f"Net PnL: ${(pnl or 0.0):.2f}{fee_str}"
            )

            return pnl

        except Exception as e:
            logger.error(f"Error settling position {position_id}: {e}")
            alert_manager.send_error_alert(str(e), f"Position settlement failed for {position_id}")
            return None

    def get_order_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get order history (newest first; orders are appended chronologically)."""
        if limit is not None and limit > 0:
            items = list(self.order_history)[-limit:]
        else:
            items = list(self.order_history)
        items.reverse()
        return items

    def get_recent_orders(self, limit: int = 10) -> List[Dict]:
        """Get recent orders"""
        return self.get_order_history(limit)

    def get_execution_stats(self) -> Dict:
        """Get execution statistics including fee totals and slippage."""
        total_orders = len(self.order_history)

        buy_count = sell_count = filled_count = 0
        total_volume = 0.0
        total_fees = 0.0
        slippage_values = []

        for o in self.order_history:
            if o["action"] == "BUY":
                buy_count += 1
            else:
                sell_count += 1
            if o["status"] == "FILLED":
                filled_count += 1
                total_volume += o["total"]
            total_fees += o.get("fee", 0.0)
            slip = o.get("slippage_pct", 0.0)
            if o["action"] == "BUY":
                slippage_values.append(slip)

        # avg_slippage: mean signed value (negative = fills were better than expected on average).
        # max_slippage: worst adverse fill (largest positive slippage seen across all orders).
        avg_slippage = sum(slippage_values) / len(slippage_values) if slippage_values else 0.0
        max_slippage = max((v for v in slippage_values if v > 0), default=0.0)

        return {
            "total_orders": total_orders,
            "buy_orders": buy_count,
            "sell_orders": sell_count,
            "filled_orders": filled_count,
            "failed_orders": total_orders - filled_count,
            "fill_rate": (filled_count / total_orders * 100) if total_orders > 0 else 0.0,
            "total_volume": total_volume,
            "total_fees_paid": total_fees,
            "avg_slippage_pct": avg_slippage,
            "max_slippage_pct": max_slippage,
        }

    def reset(self):
        """Reset executor"""
        self.order_history = deque(maxlen=500)
        logger.info("Order executor reset")
