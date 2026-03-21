"""
Execution Timer System
Times market close and triggers execution
"""

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime, timedelta
import time

from utils.logger import logger
from config.polymarket_config import config


@dataclass
class TimedExecution:
    """Represents a timed execution"""

    market_id: str
    execute_at: datetime
    opportunity: dict


class ExecutionTimer:
    """
    Manages execution timing for arbitrage opportunities

    Key Features:
    - Tracks time to market close
    - Triggers execution X seconds before close
    - Configurable delay
    """

    def __init__(self):
        from config.polymarket_config import config

        self.execute_before_close = config.EXECUTE_BEFORE_CLOSE_SECONDS
        self.active_timers: Dict[str, TimedExecution] = {}

    def start_timer(self, market_id: str, opportunity: dict) -> bool:
        """
        Start countdown to market close

        Args:
            market_id: Market ID
            opportunity: Opportunity data

        Returns:
            True if timer started
        """
        end_time = opportunity.get("end_time")
        if not end_time:
            logger.warning(f"Market {market_id} has no end time")
            return False

        try:
            close_time = datetime.fromisoformat(end_time)
            execute_time = close_time - timedelta(seconds=self.execute_before_close)

            # Check if we should still execute
            if execute_time <= datetime.utcnow():
                timed_exec = TimedExecution(
                    market_id=market_id,
                    execute_at=execute_time,
                    opportunity=opportunity,
                )

                self.active_timers[market_id] = timed_exec
                logger.info(
                    f"⏱️ Timer started: {market_id} - "
                    f"Execute in {(execute_time - datetime.utcnow()).total_seconds():.0f}s"
                )
                return True
            else:
                logger.warning(
                    f"⏰ Too late to execute: {market_id} - "
                    f"Market closes in {(close_time - datetime.utcnow()).total_seconds():.0f}s"
                )
                return False

        except Exception as e:
            logger.error(f"Error starting timer for {market_id}: {e}")
            return False

    def check_executions(self) -> List[str]:
        """
        Check which timers should trigger execution now

        Returns:
            List of market IDs to execute
        """
        ready_to_execute = []
        now = datetime.utcnow()

        for market_id, timed_exec in self.active_timers.items():
            if now >= timed_exec.execute_at:
                ready_to_execute.append(market_id)
                logger.info(f"⏰ Time to execute: {market_id}")

        if ready_to_execute:
            logger.info(f"📈 Ready to execute {len(ready_to_execute)} markets")

        return ready_to_execute

    def remove_timer(self, market_id: str):
        """
        Remove timer after execution

        Args:
            market_id: Market ID
        """
        if market_id in self.active_timers:
            del self.active_timers[market_id]
            logger.info(f"✅ Timer removed: {market_id}")
