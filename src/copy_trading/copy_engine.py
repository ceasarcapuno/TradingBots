"""
Copy Trading Engine with Detection Avoidance

Distributes trading signals across 20 accounts while maintaining
the appearance of independent trading activity.

Detection Avoidance Techniques:
  1. Timing jitter: Random delays between account executions (0.5-5s)
  2. Size variance: ±20% position size variation between accounts
  3. Skip probability: 10% chance any account skips a given signal
  4. Account grouping: Only trade subsets of accounts per signal
  5. Strategy rotation: Different accounts use different strategies
  6. Price variance: Limit orders vary by ±2 ticks between accounts
  7. Entry sequencing: Randomized account order for each signal

The goal: Each account's trade log should look like an independent
trader making their own decisions, not 20 synchronized robots.
"""

import asyncio
import random
import structlog
from datetime import datetime
from typing import Optional

from src.core.models import (
    TradingSignal, AccountState, AccountStatus, RiskLevel,
    SignalAction, StrategyName,
)
from src.core.events import event_bus, Event, EventType
from config.settings import SystemConfig

logger = structlog.get_logger()


class CopyTradingEngine:
    """
    Routes signals to multiple accounts with detection avoidance.
    """

    def __init__(self, config: SystemConfig, risk_manager=None,
                 compliance_monitor=None, order_router=None):
        self.config = config
        self.copy_config = config.copy_trading
        self.risk_manager = risk_manager
        self.compliance = compliance_monitor
        self.order_router = order_router

        # Account registry
        self._accounts: dict[str, AccountState] = {}

        # Account groups for rotation
        self._groups: list[list[str]] = []
        self._current_group_index = 0
        self._signals_since_rotation = 0

        # Strategy assignments: account_id → list of allowed strategies
        self._strategy_assignments: dict[str, list[StrategyName]] = {}

        # Execution history for pattern analysis
        self._execution_log: list[dict] = []

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def register_accounts(self, accounts: dict[str, AccountState]):
        """Register all accounts and create groups/strategy assignments."""
        self._accounts = accounts
        self._create_groups()
        self._assign_strategies()
        logger.info("copy_engine_initialized",
                     total_accounts=len(accounts),
                     groups=len(self._groups))

    def _create_groups(self):
        """
        Divide accounts into rotating groups.
        E.g., 20 accounts with group_size=5 → 4 groups.
        Only one group is "active" at a time for any given signal.
        """
        account_ids = list(self._accounts.keys())
        random.shuffle(account_ids)  # Randomize initial grouping
        size = self.copy_config.group_size
        self._groups = [
            account_ids[i:i + size]
            for i in range(0, len(account_ids), size)
        ]
        self._current_group_index = 0

    def _assign_strategies(self):
        """
        Assign strategy subsets to each account group.
        This creates natural variation — not all accounts trade the same strategy.

        Distribution approach:
          Group 0: VWAP Reversion + Momentum Scalp
          Group 1: Opening Range Breakout + VWAP Reversion
          Group 2: Momentum Scalp + Opening Range Breakout
          Group 3: All three strategies (diversified group)
        """
        all_strategies = [
            StrategyName.VWAP_REVERSION,
            StrategyName.OPENING_RANGE_BREAKOUT,
            StrategyName.MOMENTUM_SCALP,
        ]

        strategy_combos = [
            [StrategyName.VWAP_REVERSION, StrategyName.MOMENTUM_SCALP],
            [StrategyName.OPENING_RANGE_BREAKOUT, StrategyName.VWAP_REVERSION],
            [StrategyName.MOMENTUM_SCALP, StrategyName.OPENING_RANGE_BREAKOUT],
            all_strategies,  # Diversified group
        ]

        for i, group in enumerate(self._groups):
            combo = strategy_combos[i % len(strategy_combos)]
            for account_id in group:
                self._strategy_assignments[account_id] = combo

    # -------------------------------------------------------------------------
    # Signal Distribution
    # -------------------------------------------------------------------------

    async def distribute_signal(self, signal: TradingSignal) -> int:
        """
        Main entry point: receive a signal and distribute to eligible accounts.
        Returns number of accounts that received the signal.

        Flow:
        1. Determine which accounts are eligible (group, strategy, status)
        2. Apply detection avoidance (jitter, skip, variance)
        3. Route to each eligible account with risk/compliance checks
        4. Return count
        """
        eligible = self._get_eligible_accounts(signal)
        if not eligible:
            logger.info("no_eligible_accounts", signal_id=signal.signal_id)
            return 0

        # Randomize execution order
        random.shuffle(eligible)

        executed = 0
        tasks = []

        for account_id in eligible:
            # Skip probability — some accounts randomly skip signals
            if random.random() < self.copy_config.skip_probability:
                logger.debug("account_skip_random",
                             account_id=account_id,
                             signal_id=signal.signal_id)
                continue

            tasks.append(self._execute_for_account(signal, account_id))

        # Execute with staggered timing (not all at once)
        results = await self._staggered_execution(tasks)
        executed = sum(1 for r in results if r is True)

        # Track rotation
        self._signals_since_rotation += 1
        if self._signals_since_rotation >= self.copy_config.group_rotation_trades:
            self._rotate_group()

        # Log execution
        self._execution_log.append({
            "signal_id": signal.signal_id,
            "strategy": signal.strategy.value,
            "eligible": len(eligible),
            "executed": executed,
            "timestamp": datetime.utcnow().isoformat(),
        })

        logger.info("signal_distributed",
                     signal_id=signal.signal_id,
                     eligible=len(eligible),
                     executed=executed)

        return executed

    def _get_eligible_accounts(self, signal: TradingSignal) -> list[str]:
        """Determine which accounts should receive this signal."""
        eligible = []

        # Get current active group
        if not self._groups:
            return list(self._accounts.keys())

        active_group = self._groups[self._current_group_index]

        for account_id in active_group:
            account = self._accounts.get(account_id)
            if not account:
                continue

            # Account must be active
            if account.status != AccountStatus.ACTIVE:
                continue

            # Account must not be halted
            if account.risk_level == RiskLevel.HALTED:
                continue

            # Strategy must be assigned to this account
            allowed_strategies = self._strategy_assignments.get(account_id, [])
            if signal.strategy not in allowed_strategies:
                continue

            eligible.append(account_id)

        return eligible

    async def _execute_for_account(self, signal: TradingSignal,
                                   account_id: str) -> bool:
        """
        Execute a signal for a single account with variance applied.
        Returns True if successfully submitted.
        """
        account = self._accounts.get(account_id)
        if not account:
            return False

        # Apply position size variance
        varied_signal = self._apply_signal_variance(signal, account)

        # Risk check
        if self.risk_manager:
            allowed, reason = await self.risk_manager.validate_trade(
                varied_signal, account
            )
            if not allowed:
                logger.debug("copy_risk_rejected",
                             account_id=account_id,
                             reason=reason)
                return False

        # Compliance check
        if self.compliance:
            compliant, reason = await self.compliance.check_trade_compliance(
                varied_signal, account
            )
            if not compliant:
                logger.debug("copy_compliance_rejected",
                             account_id=account_id,
                             reason=reason)
                return False

        # Submit order
        if self.order_router:
            try:
                await self.order_router.submit_order(varied_signal, account)
                return True
            except Exception as e:
                logger.error("copy_order_failed",
                             account_id=account_id,
                             error=str(e))
                return False

        # Dry run mode
        logger.info("copy_dry_run_order",
                     account_id=account_id,
                     signal_id=varied_signal.signal_id,
                     instrument=varied_signal.instrument,
                     action=varied_signal.action.value,
                     contracts=varied_signal.contracts)
        return True

    def _apply_signal_variance(self, signal: TradingSignal,
                               account: AccountState) -> TradingSignal:
        """
        Create a varied copy of the signal for this specific account.
        Modifies: position size, entry price (for limits), stop/target distances.
        """
        import copy
        varied = copy.deepcopy(signal)

        # Size variance: ±20% of original size
        variance_pct = self.copy_config.size_variance_pct
        size_factor = 1.0 + random.uniform(-variance_pct, variance_pct)
        # Let risk manager compute final size, but influence via confidence
        varied.confidence = signal.confidence * size_factor

        # Price variance for limit orders: ±N ticks
        tick_variance = self.copy_config.entry_price_variance_ticks
        tick_size = self._get_tick_size(signal.instrument)
        price_offset = random.randint(-tick_variance, tick_variance) * tick_size
        varied.price = signal.price + price_offset

        # Slightly vary stop/target distances (±1 tick)
        if varied.stop_loss:
            stop_offset = random.choice([-1, 0, 1]) * tick_size
            varied.stop_loss = signal.stop_loss + stop_offset
        if varied.take_profit:
            target_offset = random.choice([-1, 0, 1]) * tick_size
            varied.take_profit = signal.take_profit + target_offset

        return varied

    async def _staggered_execution(self, tasks: list) -> list:
        """
        Execute tasks with random delays between them.
        This prevents all 20 accounts from hitting Tradovate simultaneously.
        """
        results = []
        for task in tasks:
            # Random delay between accounts
            delay_ms = random.randint(
                self.copy_config.min_delay_ms,
                self.copy_config.max_delay_ms
            )
            if self.copy_config.jitter_distribution == "gaussian":
                # Gaussian jitter — most delays cluster near the mean
                mean = (self.copy_config.min_delay_ms + self.copy_config.max_delay_ms) / 2
                std = (self.copy_config.max_delay_ms - self.copy_config.min_delay_ms) / 4
                delay_ms = max(
                    self.copy_config.min_delay_ms,
                    min(self.copy_config.max_delay_ms, int(random.gauss(mean, std)))
                )
            elif self.copy_config.jitter_distribution == "exponential":
                delay_ms = min(
                    self.copy_config.max_delay_ms,
                    int(random.expovariate(1 / mean) * 1000)
                )

            await asyncio.sleep(delay_ms / 1000.0)

            try:
                result = await task
                results.append(result)
            except Exception as e:
                logger.error("staggered_execution_error", error=str(e))
                results.append(False)

        return results

    def _rotate_group(self):
        """Rotate to the next account group."""
        self._current_group_index = (
            (self._current_group_index + 1) % len(self._groups)
        )
        self._signals_since_rotation = 0
        logger.info("group_rotated",
                     new_group=self._current_group_index,
                     accounts=self._groups[self._current_group_index])

    def _get_tick_size(self, instrument: str) -> float:
        sizes = {"ES": 0.25, "NQ": 0.25, "MES": 0.25, "MNQ": 0.25,
                 "BTC": 0.50, "ETH": 0.05}
        return sizes.get(instrument.upper(), 0.25)

    # -------------------------------------------------------------------------
    # Analytics
    # -------------------------------------------------------------------------

    def get_distribution_stats(self) -> dict:
        return {
            "total_signals_distributed": len(self._execution_log),
            "current_active_group": self._current_group_index,
            "signals_until_rotation": (
                self.copy_config.group_rotation_trades -
                self._signals_since_rotation
            ),
            "groups": [
                {"group": i, "accounts": g, "active": i == self._current_group_index}
                for i, g in enumerate(self._groups)
            ],
            "strategy_assignments": {
                aid: [s.value for s in strats]
                for aid, strats in self._strategy_assignments.items()
            },
            "recent_executions": self._execution_log[-20:],
        }
