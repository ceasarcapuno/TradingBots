"""
Autonomous Trading System — Entry Point

Usage:
  python main.py                    # Start with default config (dry run)
  python main.py --live             # Start in live mode
  python main.py --status           # Show system status
  python main.py --accounts config/accounts.json  # Use custom account config

Environment:
  Set configuration via .env file or environment variables.
  See .env.example for all available settings.
"""

import asyncio
import argparse
import json
import signal
import sys
import structlog
from pathlib import Path

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

from config.settings import SystemConfig
from src.core.orchestrator import Orchestrator


logger = structlog.get_logger()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Autonomous Trading System for Apex Trader Funding"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Run in live trading mode (default is dry run)"
    )
    parser.add_argument(
        "--accounts", type=str, default=None,
        help="Path to JSON file with account configurations"
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="Override webhook server port"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show system status and exit"
    )
    return parser.parse_args()


def load_account_configs(path: str) -> list[dict]:
    """Load account configurations from a JSON file."""
    config_path = Path(path)
    if not config_path.exists():
        logger.error("account_config_not_found", path=path)
        sys.exit(1)

    with open(config_path) as f:
        configs = json.load(f)

    logger.info("account_configs_loaded", count=len(configs), path=path)
    return configs


async def main():
    args = parse_args()

    # Load configuration
    config = SystemConfig()

    if args.live:
        config.dry_run = False
        logger.warning("LIVE_MODE_ENABLED — real orders will be placed")

    if args.port:
        config.webhook.port = args.port

    # Load account configs
    account_configs = None
    if args.accounts:
        account_configs = load_account_configs(args.accounts)

    # Create orchestrator
    orchestrator = Orchestrator(config)

    if args.status:
        # Just show status
        print(json.dumps(orchestrator.get_system_status(), indent=2, default=str))
        return

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def shutdown_handler(sig):
        logger.info("shutdown_signal_received", signal=sig.name)
        asyncio.create_task(orchestrator.graceful_shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: shutdown_handler(s))

    # Print startup banner
    print("=" * 60)
    print("  AUTONOMOUS TRADING SYSTEM")
    print(f"  Mode: {'DRY RUN' if config.dry_run else 'LIVE'}")
    print(f"  Accounts: {config.total_accounts}")
    print(f"  Webhook: {config.webhook.host}:{config.webhook.port}")
    print(f"  News Filter: {'ON' if config.enable_news_filter else 'OFF'}")
    print(f"  Copy Trading: {'ON' if config.enable_copy_trading else 'OFF'}")
    print("=" * 60)

    # Start the system
    try:
        await orchestrator.start(account_configs)
    except KeyboardInterrupt:
        await orchestrator.graceful_shutdown()
    except Exception as e:
        logger.critical("system_crash", error=str(e))
        await orchestrator.emergency_shutdown(f"crash: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
