"""
Logging Utility
Provides colored console logging and file logging with rotation
"""

import logging
import sys
import io
import codecs
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime
import colorlog

from config.polymarket_config import config


# Configure UTF-8 encoding for stdout on Windows
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)


class UTF8ColorStreamHandler(colorlog.StreamHandler):
    """Stream handler that handles UTF-8 encoding properly"""

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            
            # Ensure UTF-8 encoding
            if hasattr(stream, 'buffer') and hasattr(stream, 'encoding'):
                if stream.encoding.lower() != 'utf-8':
                    stream.reconfigure(encoding='utf-8', errors='replace')
            
            # Write with error handling
            try:
                stream.write(msg + self.terminator)
            except (UnicodeEncodeError, UnicodeDecodeError):
                # Fallback: encode and decode with replace
                stream.write(msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace') + self.terminator)
            
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    """
    Set up a logger with console and file handlers

    Args:
        name: Logger name
        log_file: Optional log file name

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Console handler with colors and UTF-8 encoding
    console_handler = UTF8ColorStreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    console_format = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        }
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler with rotation
    if config.LOG_TO_FILE:
        if log_file is None:
            log_file = f"{name}_{datetime.now().strftime('%Y%m%d')}.log"

        logs_dir = Path(__file__).parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)

        file_path = logs_dir / log_file
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)

        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


class TradeLogger:
    """Specialized logger for trade events"""

    def __init__(self):
        self.logger = setup_logger("trades", "trades.log")
        logs_dir = Path(__file__).parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.trade_file = logs_dir / f"trade_history_{datetime.now().strftime('%Y%m%d')}.csv"

        # Create CSV header if file doesn't exist
        if not self.trade_file.exists():
            with open(self.trade_file, "w") as f:
                f.write("timestamp,action,symbol,quantity,price,total,reason\n")

    def log_trade(
        self,
        action: str,
        symbol: str,
        quantity: float,
        price: float,
        reason: str = ""
    ):
        """Log a trade to both logger and CSV"""
        total = quantity * price

        message = f"{action.upper()} {quantity} {symbol} @ ${price:.4f} (Total: ${total:.2f})"
        if reason:
            message += f" - Reason: {reason}"

        self.logger.info(message)

        # Append to CSV
        with open(self.trade_file, "a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp},{action},{symbol},{quantity},{price},{total},{reason}\n")

    def log_order_rejected(self, symbol: str, reason: str):
        """Log rejected orders"""
        self.logger.warning(f"Order REJECTED for {symbol}: {reason}")

    def log_opportunity_detected(
        self,
        market_id: str,
        price: float,
        edge: float,
        time_to_close: float
    ):
        """Log arbitrage opportunity detection"""
        self.logger.info(
            f"Opportunity detected: {market_id} - "
            f"Price: ${price:.4f}, Edge: {edge:.2f}%, "
            f"Time to close: {time_to_close:.0f}s"
        )

    def log_position_opened(
        self,
        position_id: str,
        market_id: str,
        shares: float,
        entry_price: float,
        expected_profit: float
    ):
        """Log position opening"""
        self.logger.info(
            f"Position opened: {position_id} - "
            f"{shares:.4f} shares @ ${entry_price:.4f}, "
            f"Expected profit: ${expected_profit:.2f}"
        )

    def log_position_closed(
        self,
        position_id: str,
        market_id: str,
        exit_price: float,
        realized_pnl: float
    ):
        """Log position closing"""
        if realized_pnl >= 0:
            self.logger.info(
                f"Position settled: {position_id} - "
                f"Exit: ${exit_price:.4f}, "
                f"Profit: ${realized_pnl:.2f}"
            )
        else:
            self.logger.warning(
                f"Position settled: {position_id} - "
                f"Exit: ${exit_price:.4f}, "
                f"Loss: ${abs(realized_pnl):.2f}"
            )


# Create module-level logger instances
logger = setup_logger("polymarket_trading")
trade_logger = TradeLogger()
