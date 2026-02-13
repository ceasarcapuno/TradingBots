"""
Account Manager

Manages the lifecycle and state of all 20 trading accounts.
Maintains one TradovateClient per account and handles:
  - Account initialization and authentication
  - State synchronization with Tradovate
  - Order routing to the correct account
  - Daily resets and maintenance
"""

import asyncio
import structlog
from datetime import datetime
from typing import Optional

from src.core.models import (
    AccountState, AccountPhase, AccountStatus, RiskLevel,
    TradingSignal, SignalAction, Order, Position,
)
from src.core.events import event_bus, Event, EventType
from src.accounts.tradovate_client import TradovateClient
from config.settings import SystemConfig

logger = structlog.get_logger()


class AccountManager:
    """
    Central manager for all trading accounts.
    """

    def __init__(self, config: SystemConfig):
        self.config = config
        self._accounts: dict[str, AccountState] = {}
        self._clients: dict[str, TradovateClient] = {}

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    async def initialize(self, account_configs: list[dict]):
        """
        Initialize all accounts from configuration.

        account_configs: list of dicts with:
          - account_id: str
          - phase: "EVAL" or "PERFORMANCE"
          - credentials: {username, password, ...}
          - starting_balance: float (default 50000)
        """
        for acfg in account_configs:
            account_id = acfg["account_id"]

            # Create account state
            phase = AccountPhase(acfg.get("phase", "EVAL"))
            state = AccountState(
                account_id=account_id,
                phase=phase,
                starting_balance=acfg.get("starting_balance", 50000.0),
                current_balance=acfg.get("starting_balance", 50000.0),
                high_water_mark=acfg.get("starting_balance", 50000.0),
            )
            self._accounts[account_id] = state

            # Create Tradovate client
            client = TradovateClient(
                account_id=account_id,
                config=self.config.tradovate,
                credentials=acfg.get("credentials", {}),
            )
            self._clients[account_id] = client

        logger.info("accounts_initialized",
                     total=len(self._accounts),
                     eval=sum(1 for a in self._accounts.values()
                              if a.phase == AccountPhase.EVAL),
                     performance=sum(1 for a in self._accounts.values()
                                     if a.phase == AccountPhase.PERFORMANCE))

    async def authenticate_all(self) -> dict[str, bool]:
        """Authenticate all accounts with Tradovate API."""
        results = {}
        tasks = [
            self._authenticate_account(aid, client)
            for aid, client in self._clients.items()
        ]
        auth_results = await asyncio.gather(*tasks, return_exceptions=True)

        for (aid, _), result in zip(self._clients.items(), auth_results):
            if isinstance(result, Exception):
                results[aid] = False
                logger.error("account_auth_exception",
                             account_id=aid, error=str(result))
            else:
                results[aid] = result

        return results

    async def _authenticate_account(self, account_id: str,
                                    client: TradovateClient) -> bool:
        success = await client.authenticate()
        if not success:
            self._accounts[account_id].status = AccountStatus.PAUSED
        return success

    # -------------------------------------------------------------------------
    # Order Routing
    # -------------------------------------------------------------------------

    async def submit_order(self, signal: TradingSignal,
                           account: AccountState) -> Optional[Order]:
        """Submit an order for a specific account."""
        client = self._clients.get(account.account_id)
        if not client:
            logger.error("no_client_for_account",
                         account_id=account.account_id)
            return None

        if self.config.dry_run:
            logger.info("dry_run_order",
                        account_id=account.account_id,
                        signal_id=signal.signal_id,
                        action=signal.action.value,
                        instrument=signal.instrument,
                        contracts=signal.contracts)
            # Simulate a filled order
            return Order(
                order_id=f"dry_{signal.signal_id}",
                account_id=account.account_id,
                instrument=signal.instrument,
                quantity=signal.contracts,
                signal_id=signal.signal_id,
            )

        # Flatten action
        if signal.action == SignalAction.FLATTEN:
            await client.flatten_all()
            return None

        # Entry with bracket (stop + target)
        if signal.stop_loss and signal.take_profit:
            return await client.place_bracket_order(signal, account)

        # Simple order
        return await client.place_order(signal, account)

    async def flatten_account(self, account_id: str) -> bool:
        """Flatten all positions for one account."""
        client = self._clients.get(account_id)
        if not client:
            return False

        if self.config.dry_run:
            logger.info("dry_run_flatten", account_id=account_id)
            return True

        result = await client.flatten_all()
        if result:
            await client.cancel_all_orders()
        return result

    async def flatten_all_accounts(self) -> dict[str, bool]:
        """Emergency: flatten all positions across all accounts."""
        results = {}
        tasks = []
        for aid in self._accounts:
            tasks.append(self._flatten_single(aid))

        flat_results = await asyncio.gather(*tasks, return_exceptions=True)
        for aid, result in zip(self._accounts.keys(), flat_results):
            results[aid] = result if not isinstance(result, Exception) else False
        return results

    async def _flatten_single(self, account_id: str) -> bool:
        return await self.flatten_account(account_id)

    # -------------------------------------------------------------------------
    # State Synchronization
    # -------------------------------------------------------------------------

    async def sync_account_states(self):
        """Fetch latest positions and balances from Tradovate for all accounts."""
        if self.config.dry_run:
            return

        tasks = [
            self._sync_single_account(aid)
            for aid in self._accounts
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _sync_single_account(self, account_id: str):
        client = self._clients.get(account_id)
        account = self._accounts.get(account_id)
        if not client or not account:
            return

        try:
            # Sync positions
            positions = await client.get_positions()
            account.open_positions = positions

            # Sync balance
            balance_info = await client.get_account_balance()
            if balance_info:
                account.current_balance = balance_info.get(
                    "balance", account.current_balance
                )
                # Update daily P&L
                unrealized = balance_info.get("unrealized_pnl", 0)
                realized = balance_info.get("realized_pnl", 0)
                account.daily_pnl = realized + unrealized

                # Update high water mark (end of day only, but track intraday for safety)
                if account.current_balance > account.high_water_mark:
                    account.high_water_mark = account.current_balance

            account.last_update = datetime.utcnow()

        except Exception as e:
            logger.error("account_sync_failed",
                         account_id=account_id,
                         error=str(e))

    # -------------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------------

    def get_all_accounts(self) -> dict[str, AccountState]:
        return self._accounts

    def get_account(self, account_id: str) -> Optional[AccountState]:
        return self._accounts.get(account_id)

    def get_active_accounts(self) -> dict[str, AccountState]:
        return {
            aid: acct for aid, acct in self._accounts.items()
            if acct.status == AccountStatus.ACTIVE
        }

    def get_eval_accounts(self) -> dict[str, AccountState]:
        return {
            aid: acct for aid, acct in self._accounts.items()
            if acct.phase == AccountPhase.EVAL
        }

    def get_performance_accounts(self) -> dict[str, AccountState]:
        return {
            aid: acct for aid, acct in self._accounts.items()
            if acct.phase == AccountPhase.PERFORMANCE
        }

    def get_account_summary(self) -> dict:
        accounts = self._accounts.values()
        return {
            "total": len(self._accounts),
            "active": sum(1 for a in accounts if a.status == AccountStatus.ACTIVE),
            "paused": sum(1 for a in accounts if a.status in (
                AccountStatus.PAUSED, AccountStatus.DAILY_LIMIT)),
            "critical": sum(1 for a in accounts if a.status == AccountStatus.CRITICAL),
            "passed": sum(1 for a in accounts if a.status == AccountStatus.PASSED),
            "terminated": sum(1 for a in accounts if a.status == AccountStatus.TERMINATED),
            "total_daily_pnl": sum(a.daily_pnl for a in accounts),
            "total_pnl": sum(a.total_pnl for a in accounts),
            "total_open_positions": sum(len(a.open_positions) for a in accounts),
        }

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    async def shutdown(self):
        """Clean up all clients."""
        for client in self._clients.values():
            await client.close()
        logger.info("account_manager_shutdown")
