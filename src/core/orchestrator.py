"""
Main Orchestrator

The central nervous system of the trading bot. Coordinates all components:
  - Starts/stops the webhook server
  - Initializes accounts and strategies
  - Runs the main trading loop
  - Handles system events (startup, shutdown, errors)
  - Manages the monitoring and compliance check cycles

Lifecycle:
  1. Initialize configuration
  2. Initialize accounts (authenticate with Tradovate)
  3. Register accounts with copy trading engine
  4. Start webhook server
  5. Start monitoring loops (risk, compliance, market intel)
  6. Run until shutdown signal
"""

import asyncio
import signal
import structlog
import uvicorn
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import SystemConfig
from src.core.events import event_bus, Event, EventType
from src.risk.risk_manager import RiskManager
from src.compliance.apex_compliance import ApexComplianceMonitor
from src.strategies.vwap_reversion import VWAPReversionStrategy
from src.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from src.strategies.momentum_scalp import MomentumScalpStrategy
from src.copy_trading.copy_engine import CopyTradingEngine
from src.webhooks.webhook_server import WebhookServer
from src.accounts.account_manager import AccountManager
from src.market_intel.news_filter import MarketIntelligence
from src.monitoring.performance_monitor import PerformanceMonitor

logger = structlog.get_logger()

CT = ZoneInfo("America/Chicago")


class Orchestrator:
    """
    Main system orchestrator — brings all components together.
    """

    def __init__(self, config: SystemConfig = None):
        self.config = config or SystemConfig()
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Core components
        self.risk_manager = RiskManager(self.config)
        self.compliance = ApexComplianceMonitor(self.config)
        self.market_intel = MarketIntelligence(self.config)
        self.performance = PerformanceMonitor(self.config)
        self.account_manager = AccountManager(self.config)

        # Copy trading engine (wired to risk + compliance + order router)
        self.copy_engine = CopyTradingEngine(
            config=self.config,
            risk_manager=self.risk_manager,
            compliance_monitor=self.compliance,
            order_router=self.account_manager,
        )

        # Webhook server (signals go to copy engine)
        self.webhook_server = WebhookServer(
            config=self.config,
            signal_handler=self.copy_engine.distribute_signal,
        )

        # Strategies (for internal signal generation, complementing Pine Script)
        self.strategies = [
            VWAPReversionStrategy(["ES", "NQ"]),
            OpeningRangeBreakoutStrategy(["ES", "NQ"]),
            MomentumScalpStrategy(["ES", "NQ"]),
        ]

        # Register event handlers
        self._register_event_handlers()

    def _register_event_handlers(self):
        """Wire up system-level event handlers."""
        event_bus.subscribe(EventType.EMERGENCY_FLATTEN, self._on_emergency_flatten)
        event_bus.subscribe(EventType.ACCOUNT_TERMINATED, self._on_account_terminated)
        event_bus.subscribe(EventType.ACCOUNT_PASSED_EVAL, self._on_eval_passed)
        event_bus.subscribe(EventType.FLATTEN_REQUIRED, self._on_flatten_required)

    # -------------------------------------------------------------------------
    # Startup
    # -------------------------------------------------------------------------

    async def start(self, account_configs: list[dict] = None):
        """
        Start the entire trading system.

        account_configs: list of account config dicts. If None, generates
        default configs for the configured number of accounts.
        """
        logger.info("system_starting",
                     dry_run=self.config.dry_run,
                     total_accounts=self.config.total_accounts)

        # 1. Initialize accounts
        if not account_configs:
            account_configs = self._generate_default_account_configs()

        await self.account_manager.initialize(account_configs)

        # 2. Authenticate (skip in dry run with no credentials)
        if not self.config.dry_run:
            auth_results = await self.account_manager.authenticate_all()
            failed = [aid for aid, ok in auth_results.items() if not ok]
            if failed:
                logger.warning("some_accounts_auth_failed", accounts=failed)

        # 3. Register accounts with copy engine
        self.copy_engine.register_accounts(
            self.account_manager.get_all_accounts()
        )

        # 4. Publish startup event
        await event_bus.publish(Event(
            event_type=EventType.SYSTEM_START,
            data={"accounts": self.config.total_accounts,
                  "dry_run": self.config.dry_run},
            source="orchestrator"
        ))

        self._running = True

        # 5. Start concurrent loops
        await asyncio.gather(
            self._run_webhook_server(),
            self._run_monitoring_loop(),
            self._run_account_sync_loop(),
            self._wait_for_shutdown(),
        )

    async def _run_webhook_server(self):
        """Start the webhook server in the background."""
        config = uvicorn.Config(
            app=self.webhook_server.app,
            host=self.config.webhook.host,
            port=self.config.webhook.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        logger.info("webhook_server_starting",
                     host=self.config.webhook.host,
                     port=self.config.webhook.port)
        try:
            await server.serve()
        except Exception as e:
            logger.error("webhook_server_error", error=str(e))

    async def _run_monitoring_loop(self):
        """
        Periodic monitoring loop — checks compliance, risk, and market conditions.
        Runs every 30 seconds during trading hours.
        """
        while self._running:
            try:
                accounts = self.account_manager.get_all_accounts()

                # Check news blackout
                is_blackout, event_name = await self.market_intel.check_news_blackout()

                # If in blackout, flatten all active accounts
                if is_blackout:
                    for acct in accounts.values():
                        if acct.open_positions:
                            await self.account_manager.flatten_account(
                                acct.account_id
                            )

                # Compliance monitoring
                await self.compliance.monitor_positions(accounts)

                # Risk monitoring
                await self.risk_manager.update_portfolio_state(accounts)

                # Check if system should shut down
                if self.performance.should_shutdown():
                    logger.critical("performance_shutdown_triggered")
                    await self.emergency_shutdown("performance_degradation")

                # Check weekend
                if self.compliance.is_weekend():
                    # Ensure all positions are flat on weekends
                    for acct in accounts.values():
                        if acct.open_positions:
                            logger.warning("weekend_position_found",
                                           account_id=acct.account_id)
                            await self.account_manager.flatten_account(
                                acct.account_id
                            )

            except Exception as e:
                logger.error("monitoring_loop_error", error=str(e))

            await asyncio.sleep(30)

    async def _run_account_sync_loop(self):
        """Sync account states from Tradovate every 60 seconds."""
        while self._running:
            try:
                await self.account_manager.sync_account_states()
            except Exception as e:
                logger.error("account_sync_error", error=str(e))
            await asyncio.sleep(60)

    async def _wait_for_shutdown(self):
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    async def _on_emergency_flatten(self, event: Event):
        """Handle emergency flatten events."""
        account_id = event.account_id
        if account_id:
            await self.account_manager.flatten_account(account_id)
        else:
            # Flatten all
            await self.account_manager.flatten_all_accounts()

    async def _on_account_terminated(self, event: Event):
        """Handle account termination."""
        account_id = event.account_id
        logger.critical("account_terminated",
                        account_id=account_id,
                        reason=event.data.get("reason"))
        # Flatten and stop trading this account
        await self.account_manager.flatten_account(account_id)

    async def _on_eval_passed(self, event: Event):
        """Celebrate and log EVAL pass."""
        account_id = event.account_id
        logger.info("EVAL_PASSED",
                     account_id=account_id,
                     profit=event.data.get("profit"),
                     trading_days=event.data.get("trading_days"))

    async def _on_flatten_required(self, event: Event):
        """Handle compliance-mandated flatten."""
        account_id = event.account_id
        await self.account_manager.flatten_account(account_id)

    # -------------------------------------------------------------------------
    # Shutdown
    # -------------------------------------------------------------------------

    async def emergency_shutdown(self, reason: str):
        """Flatten everything and shut down."""
        logger.critical("emergency_shutdown", reason=reason)
        await self.account_manager.flatten_all_accounts()
        self._running = False
        self._shutdown_event.set()
        await event_bus.publish(Event(
            event_type=EventType.SYSTEM_SHUTDOWN,
            data={"reason": reason},
            source="orchestrator"
        ))

    async def graceful_shutdown(self):
        """Graceful shutdown — flatten, save state, close connections."""
        logger.info("graceful_shutdown_initiated")
        # Flatten all positions
        await self.account_manager.flatten_all_accounts()
        # Generate final report
        report = self.performance.generate_daily_report(
            self.account_manager.get_all_accounts()
        )
        logger.info("final_report", report=report)
        # Cleanup
        await self.account_manager.shutdown()
        self._running = False
        self._shutdown_event.set()

    # -------------------------------------------------------------------------
    # Default Account Config Generator
    # -------------------------------------------------------------------------

    def _generate_default_account_configs(self) -> list[dict]:
        """Generate default configs for N accounts (for testing/dry run)."""
        configs = []
        for i in range(1, self.config.total_accounts + 1):
            configs.append({
                "account_id": f"APEX_{i:02d}",
                "phase": "EVAL",
                "starting_balance": 50000.0,
                "credentials": {
                    "username": f"account_{i:02d}",
                    "password": "placeholder",
                },
            })
        return configs

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    def get_system_status(self) -> dict:
        """Full system status for monitoring/API."""
        return {
            "running": self._running,
            "dry_run": self.config.dry_run,
            "timestamp": datetime.utcnow().isoformat(),
            "session": self.compliance.get_session_status(),
            "accounts": self.account_manager.get_account_summary(),
            "portfolio": self.risk_manager.get_portfolio_state().__dict__,
            "copy_trading": self.copy_engine.get_distribution_stats(),
            "webhooks": self.webhook_server.get_metrics(),
            "market_context": self.market_intel.get_market_context(),
            "performance": self.performance.get_portfolio_metrics(),
        }
