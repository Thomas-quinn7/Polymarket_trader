"""
Structured logging module using structlog.
Provides consistent, structured logging across the application.
"""

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import Processor


def configure_logger(
    level: str = "INFO",
    log_to_file: bool = False,
    log_file: str = "logs/app.log",
    json_logs: bool = False,
) -> None:
    """
    Configure the application logger with structlog.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to write logs to a file
        log_file: Path to the log file
        json_logs: Whether to output JSON logs (False = pretty console format)
    """
    # Set up standard logging
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        stream=sys.stdout,
    )

    # Enrichment processors — must all run before the terminal renderer
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Renderer must be the final processor
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # File logging is handled by stdlib — attach a handler to the root logger
    if log_to_file:
        log_dir = Path(log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode="a")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        )
        logging.getLogger().addHandler(file_handler)

    logging.getLogger().setLevel(log_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger for a specific module or component.

    Args:
        name: Module name or component name. If None, uses the caller's module name.

    Returns:
        Configured logger instance
    """
    if name is None:
        # Get the caller's module name
        import inspect

        frame = inspect.currentframe().f_back
        name = inspect.getmodule(frame).__name__
    return structlog.get_logger(name)


def log_exception(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    exc_info: BaseException | bool = True,
    **kwargs: Any,
) -> None:
    """
    Log an exception with full traceback.

    Args:
        logger: Logger instance to use
        event: Event message
        exc_info: Whether to include exception traceback
        **kwargs: Additional context data
    """
    logger.exception(event, **kwargs)


def log_error(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    **kwargs: Any,
) -> None:
    """
    Log an error event.

    Args:
        logger: Logger instance to use
        event: Event message
        **kwargs: Additional context data
    """
    logger.error(event, **kwargs)


def log_warning(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    **kwargs: Any,
) -> None:
    """
    Log a warning event.

    Args:
        logger: Logger instance to use
        event: Event message
        **kwargs: Additional context data
    """
    logger.warning(event, **kwargs)


def log_info(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    **kwargs: Any,
) -> None:
    """
    Log an info event.

    Args:
        logger: Logger instance to use
        event: Event message
        **kwargs: Additional context data
    """
    logger.info(event, **kwargs)


def log_debug(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    **kwargs: Any,
) -> None:
    """
    Log a debug event.

    Args:
        logger: Logger instance to use
        event: Event message
        **kwargs: Additional context data
    """
    logger.debug(event, **kwargs)


# Convenience functions for common logging patterns
logger = get_logger("app")


# Initialize default logger configuration
configure_logger(level="INFO", log_to_file=True)
