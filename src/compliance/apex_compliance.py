"""
Apex Trader Funding Compliance Framework

Monitors all Apex rules in real-time and prevents violations.
This module encodes the complete Apex rule set for both EVAL and PERFORMANCE phases.

Key Apex Rules (as of system design):
  EVAL ($50K Tradovate):
    - Profit target: $3,000
    - Trailing threshold (drawdown): $2,500 (end-of-day trailing)
    - Max contracts: 10 ES/NQ, 50 MES/MNQ
    - Min trading days: 7
    - No trading during daily close (4:59 PM - 6:00 PM CT)
    - All positions must be flat during close window
    - No news trading restrictions (Apex removed this for EVAL)

  PERFORMANCE ($50K):
    - Trailing threshold: $2,500 (end-of-day trailing)
    - Max contracts same as EVAL
    - Payout rules: Must maintain positive balance above starting
    - Same close window restrictions
    - More scrutiny on trading patterns

IMPORTANT: Verify current Apex rules before deploying — rules change periodically.
"""

import structlog
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.models import (
    AccountState, AccountPhase, AccountStatus, TradingSignal,
    Position, OrderSide,
)
from src.core.events import event_bus, Event, EventType
from config.settings import SystemConfig

logger = structlog.get_logger()

CT = ZoneInfo("America/Chicago")


class ApexComplianceMonitor:
    """
    Real-time compliance monitor for Apex Trader Funding rules.

    Every action is checked against the rule set before execution.
    Violations trigger immediate protective action (flatten + pause).
    """

    def __init__(self, config: SystemConfig):
        self.config = config
        self.rules = config.apex

        # Parse trading windows
        h, m = self.rules.no_trading_window_start.split(":")
        self._close_start = time(int(h), int(m))
        h, m = self.rules.no_trading_window_end.split(":")
        self._close_end = time(int(h), int(m))

        self._flatten_minutes = self.rules.flatten_before_close_minutes

        event_bus.subscribe(EventType.POSITION_OPENED, self._on_position_opened)

    # -------------------------------------------------------------------------
    # Pre-Trade Compliance Checks
    # -------------------------------------------------------------------------

    async def check_trade_compliance(self, signal: TradingSignal,
                                     account: AccountState) -> tuple[bool, str]:
        """
        Full compliance check before order submission.
        Returns (compliant, reason).
        """
        checks = [
            self._check_trading_window(),
            self._check_flatten_window(),
            self._check_account_not_terminated(account),
            self._check_contract_limits(signal, account),
            self._check_drawdown_threshold(account),
            self._check_eval_pass_status(account),
        ]

        for compliant, reason in checks:
            if not compliant:
                logger.warning("compliance_rejected",
                               account_id=account.account_id,
                               signal_id=signal.signal_id,
                               rule=reason)
                await event_bus.publish(Event(
                    event_type=EventType.COMPLIANCE_WARNING,
                    data={"reason": reason, "signal_id": signal.signal_id},
                    account_id=account.account_id,
                    source="compliance"
                ))
                return False, reason

        return True, "compliant"

    def _check_trading_window(self) -> tuple[bool, str]:
        """No trading during the daily close window (4:59 PM - 6:00 PM CT)."""
        now_ct = datetime.now(CT).time()
        if self._close_start <= now_ct or now_ct < self._close_end:
            # Handle midnight wraparound: close_start(16:59) to close_end(18:00)
            if self._close_start <= now_ct <= time(23, 59, 59):
                return False, "Trading window closed (daily close period)"
            if time(0, 0) <= now_ct < self._close_end:
                return False, "Trading window closed (daily close period)"
        return True, ""

    def _check_flatten_window(self) -> tuple[bool, str]:
        """Warn if approaching the mandatory flatten window."""
        now_ct = datetime.now(CT)
        close_dt = now_ct.replace(
            hour=self._close_start.hour,
            minute=self._close_start.minute,
            second=0
        )
        minutes_to_close = (close_dt - now_ct).total_seconds() / 60

        if 0 < minutes_to_close <= self._flatten_minutes:
            return False, (f"Within {self._flatten_minutes}-minute flatten window "
                           f"before close ({minutes_to_close:.1f} min remaining)")
        return True, ""

    def _check_account_not_terminated(self, account: AccountState) -> tuple[bool, str]:
        if account.status == AccountStatus.TERMINATED:
            return False, "Account is terminated"
        return True, ""

    def _check_contract_limits(self, signal: TradingSignal,
                               account: AccountState) -> tuple[bool, str]:
        """Verify contract count stays within Apex limits."""
        instrument = signal.instrument.upper()
        limits = {
            "ES": self.rules.eval_max_contracts_es,
            "NQ": self.rules.eval_max_contracts_nq,
            "MES": self.rules.eval_max_contracts_mes,
            "MNQ": self.rules.eval_max_contracts_mnq,
        }
        max_allowed = limits.get(instrument, 10)
        current = sum(
            p.quantity for p in account.open_positions
            if p.instrument.upper() == instrument
        )
        if current + signal.contracts > max_allowed:
            return False, (f"Apex contract limit: {current}+{signal.contracts} "
                           f"> {max_allowed} for {instrument}")
        return True, ""

    def _check_drawdown_threshold(self, account: AccountState) -> tuple[bool, str]:
        """Check if account is approaching the trailing threshold."""
        max_dd = (self.rules.eval_max_drawdown
                  if account.phase == AccountPhase.EVAL
                  else self.rules.perf_max_drawdown)

        remaining = account.trailing_drawdown_remaining
        # Hard stop at 95% of max drawdown consumed
        if remaining <= max_dd * 0.05:
            return False, (f"Drawdown threshold imminent: only "
                           f"${remaining:.2f} remaining of ${max_dd:.2f}")
        return True, ""

    def _check_eval_pass_status(self, account: AccountState) -> tuple[bool, str]:
        """Check if EVAL account has already passed (no more trading needed)."""
        if account.phase == AccountPhase.EVAL:
            profit = account.current_balance - account.starting_balance
            if (profit >= self.rules.eval_profit_target and
                    account.trading_days >= self.rules.eval_min_trading_days):
                # Account has passed — should be transitioning
                return False, "EVAL target reached — account should transition to PERFORMANCE"
        return True, ""

    # -------------------------------------------------------------------------
    # Real-Time Monitoring
    # -------------------------------------------------------------------------

    async def monitor_positions(self, accounts: dict[str, AccountState]):
        """
        Periodic check: ensure all accounts are compliant.
        Called on a timer (every 30 seconds during trading hours).
        """
        now_ct = datetime.now(CT)

        for account_id, account in accounts.items():
            if account.status == AccountStatus.TERMINATED:
                continue

            # Check if positions need flattening before close
            await self._check_flatten_deadline(account, now_ct)

            # Check for EVAL pass condition
            await self._check_eval_completion(account)

            # Check trailing drawdown (defensive recalculation)
            await self._verify_drawdown(account)

    async def _check_flatten_deadline(self, account: AccountState,
                                      now_ct: datetime):
        """Force flatten if close window is imminent and positions are open."""
        if not account.open_positions:
            return

        close_dt = now_ct.replace(
            hour=self._close_start.hour,
            minute=self._close_start.minute,
            second=0
        )
        minutes_to_close = (close_dt - now_ct).total_seconds() / 60

        if 0 < minutes_to_close <= 2:
            # Emergency: 2 minutes or less → force flatten
            logger.critical("force_flatten_close_window",
                            account_id=account.account_id,
                            minutes_remaining=minutes_to_close,
                            positions=len(account.open_positions))
            await event_bus.publish(Event(
                event_type=EventType.FLATTEN_REQUIRED,
                data={"reason": "close_window_imminent",
                      "minutes_remaining": minutes_to_close},
                account_id=account.account_id,
                source="compliance"
            ))
        elif 0 < minutes_to_close <= self._flatten_minutes:
            # Warning: approaching flatten time
            logger.warning("flatten_window_approaching",
                           account_id=account.account_id,
                           minutes_remaining=minutes_to_close)

    async def _check_eval_completion(self, account: AccountState):
        """Detect when an EVAL account has met all pass criteria."""
        if account.phase != AccountPhase.EVAL:
            return
        if account.status == AccountStatus.PASSED:
            return

        profit = account.current_balance - account.starting_balance
        has_profit = profit >= self.rules.eval_profit_target
        has_days = account.trading_days >= self.rules.eval_min_trading_days

        if has_profit and has_days:
            account.status = AccountStatus.PASSED
            logger.info("eval_passed",
                        account_id=account.account_id,
                        profit=profit,
                        trading_days=account.trading_days)
            await event_bus.publish(Event(
                event_type=EventType.ACCOUNT_PASSED_EVAL,
                data={"profit": profit, "trading_days": account.trading_days},
                account_id=account.account_id,
                source="compliance"
            ))

    async def _verify_drawdown(self, account: AccountState):
        """
        Defensive drawdown verification.
        Apex uses end-of-day trailing drawdown. The high water mark
        updates at the end of each trading day, not intraday.
        """
        max_dd = (self.rules.eval_max_drawdown
                  if account.phase == AccountPhase.EVAL
                  else self.rules.perf_max_drawdown)

        threshold = account.high_water_mark - max_dd
        if account.current_balance <= threshold:
            logger.critical("drawdown_threshold_breached",
                            account_id=account.account_id,
                            balance=account.current_balance,
                            threshold=threshold)
            account.status = AccountStatus.TERMINATED
            await event_bus.publish(Event(
                event_type=EventType.ACCOUNT_TERMINATED,
                data={
                    "reason": "drawdown_threshold_breached",
                    "balance": account.current_balance,
                    "threshold": threshold
                },
                account_id=account.account_id,
                source="compliance"
            ))

    # -------------------------------------------------------------------------
    # Weekend / Holiday Management
    # -------------------------------------------------------------------------

    def is_weekend(self) -> bool:
        now_ct = datetime.now(CT)
        # Futures close Friday 4:59 PM CT, reopen Sunday 5:00 PM CT
        weekday = now_ct.weekday()
        if weekday == 4 and now_ct.time() >= self._close_start:  # Friday after close
            return True
        if weekday == 5:  # Saturday
            return True
        if weekday == 6 and now_ct.time() < time(17, 0):  # Sunday before open
            return True
        return False

    def get_session_status(self) -> dict:
        """Get current trading session information."""
        now_ct = datetime.now(CT)
        return {
            "current_time_ct": now_ct.strftime("%Y-%m-%d %H:%M:%S CT"),
            "is_weekend": self.is_weekend(),
            "in_close_window": self._is_in_close_window(now_ct),
            "weekday": now_ct.strftime("%A"),
        }

    def _is_in_close_window(self, now_ct: datetime) -> bool:
        t = now_ct.time()
        return self._close_start <= t or t < self._close_end

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    async def _on_position_opened(self, event: Event):
        """Log position opens for audit trail."""
        logger.info("compliance_position_opened",
                    account_id=event.account_id,
                    data=event.data)
