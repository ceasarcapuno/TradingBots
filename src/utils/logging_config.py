"""
Logging configuration for the trading system.
Uses structlog for structured, context-rich logging.
"""

import logging
import structlog
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_file: str = "logs/trading.log"):
    """Configure structured logging for the entire application."""

    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Standard library logging config (for uvicorn, httpx, etc.)
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ]
    )

    # Structlog configuration
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
