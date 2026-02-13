"""
Risk Management Engine

Defense-first risk management with multi-layer circuit breakers.
This is the most critical component — it prevents account termination.

Architecture:
  Layer 1: Pre-trade validation (before any order)
  Layer 2: Real-time position monitoring (while trades are open)
  Layer 3: Account-level circuit breakers (daily loss, drawdown)
  Layer 4: Portfolio-level risk aggregation (cross-account limits)
"""

import asyncio
import structlog
from datetime import datetime, timedelta
from typing import Optional

from src.core.models import (
    AccountState, AccountPhase, AccountStatus, RiskLevel,
    TradingSignal, Order, Position, OrderSide, PortfolioState,
)
from src.core.events import event_bus, Event, EventType
from config.settings import SystemConfig

logger = structlog.get_logger()


class RiskManager:
    """
    Central risk management engine.

    Every order must pass through validate_trade() before submission.
    The monitor loop continuously checks positions and account health.
    """

    def __init__(self, config: SystemConfig):
        self.config = config
        self.risk_config = config.risk
        self.apex_rules = config.apex
        self._portfolio_state = PortfolioState()
        self._daily_reset_time: Optional[datetime] = None

        # Subscribe to events
        event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)
        event_bus.subscribe(EventType.POSITION_CLOSED, self._on_position_closed)

    # -------------------------------------------------------------------------
    # Layer 1: Pre-Trade Validation
    # -------------------------------------------------------------------------

    async def validate_trade(self, signal: TradingSignal,
                             account: AccountState) -> tuple[bool, str]:
        """
        Gate check before any order is submitted.
        Returns (allowed, reason).
        """
        checks = [
            self._check_account_status(account),
            self._check_risk_level(account, signal),
            self._check_daily_loss_limit(account),
            self._check_drawdown_remaining(account),
            self._check_position_limits(account),
            self._check_contract_limits(account, signal),
            self._check_single_trade_risk(signal, account),
            self._check_portfolio_limits(signal),
            self._check_correlated_exposure(signal),
        ]

        for check in checks:
            allowed, reason = check
            if not allowed:
                logger.warning("trade_rejected",
                               account_id=account.account_id,
                               signal_id=signal.signal_id,
                               reason=reason)
                await event_bus.publish(Event(
                    event_type=EventType.SIGNAL_REJECTED,
                    data={"reason": reason, "signal_id": signal.signal_id},
                    account_id=account.account_id,
                    source="risk_manager"
                ))
                return False, reason

        logger.info("trade_validated",
                     account_id=account.account_id,
                     signal_id=signal.signal_id)
        return True, "passed"

    def _check_account_status(self, account: AccountState) -> tuple[bool, str]:
        if account.status != AccountStatus.ACTIVE:
            return False, f"Account status is {account.status.value}"
        return True, ""

    def _check_risk_level(self, account: AccountState,
                          signal: TradingSignal) -> tuple[bool, str]:
        if account.risk_level == RiskLevel.HALTED:
            return False, "Account risk level is HALTED — no trading allowed"
        if account.risk_level == RiskLevel.MINIMAL:
            # Only allow if signal has high confidence and minimal size
            if signal.confidence < 0.8 or signal.contracts > 1:
                return False, "MINIMAL risk level — only high-confidence 1-lot trades"
        return True, ""

    def _check_daily_loss_limit(self, account: AccountState) -> tuple[bool, str]:
        limit = self.risk_config.max_daily_loss_absolute
        if account.daily_pnl <= -limit:
            return False, f"Daily loss limit reached: ${account.daily_pnl:.2f}"
        # Warning threshold at 70% of limit
        if account.daily_pnl <= -(limit * 0.7):
            logger.warning("daily_loss_warning",
                           account_id=account.account_id,
                           daily_pnl=account.daily_pnl)
        return True, ""

    def _check_drawdown_remaining(self, account: AccountState) -> tuple[bool, str]:
        max_dd = (self.apex_rules.eval_max_drawdown
                  if account.phase == AccountPhase.EVAL
                  else self.apex_rules.perf_max_drawdown)

        used_pct = account.drawdown_used_pct

        if used_pct >= self.risk_config.drawdown_critical_pct:
            return False, (f"Drawdown critical: {used_pct:.1%} of max used "
                           f"(threshold: {self.risk_config.drawdown_critical_pct:.1%})")
        return True, ""

    def _check_position_limits(self, account: AccountState) -> tuple[bool, str]:
        open_count = len(account.open_positions)
        if open_count >= self.risk_config.max_open_positions:
            return False, f"Max open positions reached: {open_count}"
        return True, ""

    def _check_contract_limits(self, account: AccountState,
                               signal: TradingSignal) -> tuple[bool, str]:
        instrument = signal.instrument.upper()
        max_contracts = self._get_max_contracts(account, instrument)
        current_exposure = sum(
            p.quantity for p in account.open_positions
            if p.instrument.upper() == instrument
        )
        if current_exposure + signal.contracts > max_contracts:
            return False, (f"Contract limit: {current_exposure} open + "
                           f"{signal.contracts} requested > {max_contracts} max")
        return True, ""

    def _get_max_contracts(self, account: AccountState, instrument: str) -> int:
        rules = self.apex_rules
        # Use the more conservative of Apex limit and our self-imposed limit
        limits = {
            "ES": rules.eval_max_contracts_es,
            "NQ": rules.eval_max_contracts_nq,
            "MES": rules.eval_max_contracts_mes,
            "MNQ": rules.eval_max_contracts_mnq,
        }
        apex_limit = limits.get(instrument, 4)
        # Self-imposed limit is always tighter
        self_limit = rules.eval_max_position_size_per_trade
        return min(apex_limit, self_limit)

    def _check_single_trade_risk(self, signal: TradingSignal,
                                 account: AccountState) -> tuple[bool, str]:
        if signal.stop_loss and signal.price:
            tick_value = self._get_tick_value(signal.instrument)
            risk_per_contract = abs(signal.price - signal.stop_loss) * tick_value
            total_risk = risk_per_contract * signal.contracts
            if total_risk > self.risk_config.max_single_trade_risk:
                return False, (f"Single trade risk ${total_risk:.2f} exceeds "
                               f"limit ${self.risk_config.max_single_trade_risk:.2f}")
        return True, ""

    def _check_portfolio_limits(self, signal: TradingSignal) -> tuple[bool, str]:
        total_positions = self._portfolio_state.total_open_positions
        if total_positions >= self.risk_config.portfolio_max_simultaneous_trades:
            return False, (f"Portfolio position limit: {total_positions} open "
                           f"(max {self.risk_config.portfolio_max_simultaneous_trades})")

        if self._portfolio_state.total_daily_pnl <= -self.risk_config.portfolio_max_daily_loss:
            return False, (f"Portfolio daily loss limit: "
                           f"${self._portfolio_state.total_daily_pnl:.2f}")
        return True, ""

    def _check_correlated_exposure(self, signal: TradingSignal) -> tuple[bool, str]:
        instrument = signal.instrument.upper()
        correlated_count = 0
        for acct in self._portfolio_state.accounts.values():
            for pos in acct.open_positions:
                if pos.instrument.upper() == instrument:
                    correlated_count += 1
        if correlated_count >= self.risk_config.max_correlated_positions:
            return False, (f"Correlated exposure limit: {correlated_count} "
                           f"accounts already have {instrument} positions")
        return True, ""

    # -------------------------------------------------------------------------
    # Layer 2: Position Sizing
    # -------------------------------------------------------------------------

    def calculate_position_size(self, signal: TradingSignal,
                                account: AccountState) -> int:
        """
        Dynamic position sizing based on account health and signal quality.

        Rules:
        - Start with base size (1 contract for ES/NQ)
        - Scale up only if profit buffer exists
        - Scale down if drawdown is eating into threshold
        - Never exceed Apex contract limits
        """
        instrument = signal.instrument.upper()
        base = self._get_base_contracts(instrument)

        # Risk level multipliers
        risk_multipliers = {
            RiskLevel.NORMAL: 1.0,
            RiskLevel.REDUCED: 0.5,
            RiskLevel.MINIMAL: 0.25,
            RiskLevel.HALTED: 0.0,
        }
        multiplier = risk_multipliers[account.risk_level]

        # Profit buffer scaling: only scale up if we have cushion
        profit_buffer = account.current_balance - account.starting_balance
        if profit_buffer > self.risk_config.scale_up_threshold_profit:
            buffer_ratio = min(
                profit_buffer / (self.risk_config.scale_up_threshold_profit * 2),
                self.risk_config.scale_up_max_multiplier - 1.0
            )
            multiplier *= (1.0 + buffer_ratio)

        # Confidence scaling
        confidence_factor = 0.5 + (signal.confidence * 0.5)  # Range: 0.5 - 1.0
        multiplier *= confidence_factor

        size = max(1, int(base * multiplier))

        # Hard cap at Apex limits
        max_allowed = self._get_max_contracts(account, instrument)
        size = min(size, max_allowed)

        return size

    def _get_base_contracts(self, instrument: str) -> int:
        bases = {
            "ES": self.risk_config.base_contracts_es,
            "NQ": self.risk_config.base_contracts_nq,
            "MES": self.risk_config.base_contracts_mes,
            "MNQ": self.risk_config.base_contracts_mnq,
        }
        return bases.get(instrument, 1)

    def _get_tick_value(self, instrument: str) -> float:
        """Dollar value per point for each instrument."""
        values = {
            "ES": 50.0,     # $50 per point
            "NQ": 20.0,     # $20 per point
            "MES": 5.0,     # $5 per point
            "MNQ": 2.0,     # $2 per point
            "BTC": 5.0,     # Varies by exchange
            "ETH": 50.0,
        }
        return values.get(instrument.upper(), 50.0)

    # -------------------------------------------------------------------------
    # Layer 3: Account-Level Circuit Breakers
    # -------------------------------------------------------------------------

    async def update_account_risk(self, account: AccountState):
        """
        Evaluate account health and adjust risk level.
        Called after every trade and on periodic monitoring ticks.
        """
        max_dd = (self.apex_rules.eval_max_drawdown
                  if account.phase == AccountPhase.EVAL
                  else self.apex_rules.perf_max_drawdown)

        # Calculate drawdown usage
        drawdown_used = account.high_water_mark - account.current_balance
        account.drawdown_used_pct = drawdown_used / max_dd if max_dd > 0 else 0
        account.trailing_drawdown_remaining = max_dd - drawdown_used

        previous_level = account.risk_level

        # Determine risk level from drawdown
        if account.drawdown_used_pct >= self.risk_config.drawdown_critical_pct:
            account.risk_level = RiskLevel.HALTED
            account.status = AccountStatus.CRITICAL
            await self._trigger_emergency_flatten(account, "drawdown_critical")
        elif account.drawdown_used_pct >= self.risk_config.drawdown_danger_pct:
            account.risk_level = RiskLevel.MINIMAL
            await event_bus.publish(Event(
                event_type=EventType.RISK_DANGER,
                data={"drawdown_used_pct": account.drawdown_used_pct},
                account_id=account.account_id,
                source="risk_manager"
            ))
        elif account.drawdown_used_pct >= self.risk_config.drawdown_warning_pct:
            account.risk_level = RiskLevel.REDUCED
            await event_bus.publish(Event(
                event_type=EventType.RISK_WARNING,
                data={"drawdown_used_pct": account.drawdown_used_pct},
                account_id=account.account_id,
                source="risk_manager"
            ))
        else:
            account.risk_level = RiskLevel.NORMAL

        # Daily loss circuit breaker
        if account.daily_pnl <= -self.risk_config.max_daily_loss_absolute:
            account.status = AccountStatus.DAILY_LIMIT
            account.risk_level = RiskLevel.HALTED
            await self._trigger_emergency_flatten(account, "daily_loss_limit")
            await event_bus.publish(Event(
                event_type=EventType.DAILY_LIMIT_HIT,
                data={"daily_pnl": account.daily_pnl},
                account_id=account.account_id,
                source="risk_manager"
            ))

        if account.risk_level != previous_level:
            logger.info("risk_level_changed",
                        account_id=account.account_id,
                        previous=previous_level.value,
                        current=account.risk_level.value,
                        drawdown_used=f"{account.drawdown_used_pct:.1%}")

    async def _trigger_emergency_flatten(self, account: AccountState, reason: str):
        """Flatten all positions for an account immediately."""
        logger.critical("emergency_flatten",
                        account_id=account.account_id,
                        reason=reason,
                        open_positions=len(account.open_positions))
        await event_bus.publish(Event(
            event_type=EventType.EMERGENCY_FLATTEN,
            data={"reason": reason},
            account_id=account.account_id,
            source="risk_manager"
        ))

    # -------------------------------------------------------------------------
    # Layer 4: Portfolio-Level Monitoring
    # -------------------------------------------------------------------------

    async def update_portfolio_state(self, accounts: dict[str, AccountState]):
        """Aggregate risk across all accounts."""
        self._portfolio_state.accounts = accounts
        self._portfolio_state.total_daily_pnl = sum(
            a.daily_pnl for a in accounts.values()
        )
        self._portfolio_state.total_open_positions = sum(
            len(a.open_positions) for a in accounts.values()
        )
        self._portfolio_state.accounts_active = sum(
            1 for a in accounts.values() if a.status == AccountStatus.ACTIVE
        )
        self._portfolio_state.accounts_paused = sum(
            1 for a in accounts.values()
            if a.status in (AccountStatus.PAUSED, AccountStatus.DAILY_LIMIT)
        )
        self._portfolio_state.accounts_passed = sum(
            1 for a in accounts.values() if a.status == AccountStatus.PASSED
        )
        self._portfolio_state.accounts_terminated = sum(
            1 for a in accounts.values() if a.status == AccountStatus.TERMINATED
        )
        self._portfolio_state.last_update = datetime.utcnow()

        # Portfolio-level circuit breaker
        if self._portfolio_state.total_daily_pnl <= -self.risk_config.portfolio_max_daily_loss:
            logger.critical("portfolio_daily_loss_limit",
                            total_pnl=self._portfolio_state.total_daily_pnl)
            for acct in accounts.values():
                if acct.status == AccountStatus.ACTIVE:
                    await self._trigger_emergency_flatten(acct, "portfolio_daily_limit")

    def get_portfolio_state(self) -> PortfolioState:
        return self._portfolio_state

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    async def _on_order_filled(self, event: Event):
        account_id = event.account_id
        if account_id in self._portfolio_state.accounts:
            await self.update_account_risk(
                self._portfolio_state.accounts[account_id]
            )

    async def _on_position_closed(self, event: Event):
        account_id = event.account_id
        pnl = event.data.get("pnl", 0)
        if account_id in self._portfolio_state.accounts:
            account = self._portfolio_state.accounts[account_id]
            account.daily_pnl += pnl
            account.total_pnl += pnl
            if pnl > 0:
                account.winning_trades += 1
            else:
                account.losing_trades += 1
            account.total_trades += 1
            account.trades_today += 1
            # Update high water mark (end-of-day in production)
            if account.current_balance > account.high_water_mark:
                account.high_water_mark = account.current_balance
            await self.update_account_risk(account)

    # -------------------------------------------------------------------------
    # Daily Reset
    # -------------------------------------------------------------------------

    async def daily_reset(self, accounts: dict[str, AccountState]):
        """Called at start of each trading day to reset daily counters."""
        for account in accounts.values():
            account.daily_pnl = 0.0
            account.trades_today = 0
            account.max_contracts_used_today = 0
            if account.status == AccountStatus.DAILY_LIMIT:
                account.status = AccountStatus.ACTIVE
            # Re-evaluate risk level with fresh daily state
            await self.update_account_risk(account)
            # Increment trading days if they traded yesterday
            if account.last_trade_time:
                yesterday = datetime.utcnow() - timedelta(days=1)
                if account.last_trade_time.date() == yesterday.date():
                    account.trading_days += 1
        logger.info("daily_reset_complete", accounts=len(accounts))
