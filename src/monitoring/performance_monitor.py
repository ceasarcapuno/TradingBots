"""
Performance Monitoring & Analytics

Tracks all trading activity across the 20-account portfolio and provides:
  - Real-time P&L tracking per account and aggregate
  - Win rate, profit factor, and other key metrics
  - EVAL progress tracking (profit target, trading days)
  - Strategy performance comparison
  - Alerts when performance degrades
  - Data for iterative strategy improvement
"""

import structlog
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from src.core.models import (
    AccountState, AccountPhase, AccountStatus,
    StrategyName, RiskLevel,
)
from src.core.events import event_bus, Event, EventType
from config.settings import SystemConfig

logger = structlog.get_logger()


class TradeRecord:
    """Record of a completed trade for analytics."""

    def __init__(self, account_id: str, strategy: StrategyName,
                 instrument: str, side: str, entry_price: float,
                 exit_price: float, contracts: int, pnl: float,
                 entry_time: datetime, exit_time: datetime,
                 exit_reason: str = ""):
        self.account_id = account_id
        self.strategy = strategy
        self.instrument = instrument
        self.side = side
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.contracts = contracts
        self.pnl = pnl
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.exit_reason = exit_reason
        self.hold_duration = (exit_time - entry_time).total_seconds()


class PerformanceMonitor:
    """
    Comprehensive performance tracking and analytics engine.
    """

    def __init__(self, config: SystemConfig):
        self.config = config
        self._trade_history: list[TradeRecord] = []
        self._daily_pnl_history: dict[str, list[float]] = defaultdict(list)

        # Performance thresholds for alerts
        self._max_consecutive_losses = 5
        self._min_win_rate_threshold = 0.40    # Alert if below 40%
        self._min_profit_factor = 1.0           # Alert if below 1.0

        # Subscribe to trade events
        event_bus.subscribe(EventType.POSITION_CLOSED, self._on_trade_closed)

    # -------------------------------------------------------------------------
    # Trade Recording
    # -------------------------------------------------------------------------

    def record_trade(self, trade: TradeRecord):
        """Add a completed trade to history."""
        self._trade_history.append(trade)
        date_key = trade.exit_time.strftime("%Y-%m-%d")
        self._daily_pnl_history[trade.account_id].append(trade.pnl)

        logger.info("trade_recorded",
                     account_id=trade.account_id,
                     strategy=trade.strategy.value,
                     instrument=trade.instrument,
                     pnl=f"${trade.pnl:.2f}",
                     side=trade.side)

    async def _on_trade_closed(self, event: Event):
        """Event handler for position close events."""
        data = event.data
        trade = TradeRecord(
            account_id=event.account_id,
            strategy=StrategyName(data.get("strategy", "vwap_reversion")),
            instrument=data.get("instrument", ""),
            side=data.get("side", ""),
            entry_price=data.get("entry_price", 0),
            exit_price=data.get("exit_price", 0),
            contracts=data.get("contracts", 1),
            pnl=data.get("pnl", 0),
            entry_time=data.get("entry_time", datetime.utcnow()),
            exit_time=datetime.utcnow(),
            exit_reason=data.get("exit_reason", ""),
        )
        self.record_trade(trade)
        await self._check_performance_alerts(trade)

    # -------------------------------------------------------------------------
    # Portfolio-Level Metrics
    # -------------------------------------------------------------------------

    def get_portfolio_metrics(self) -> dict:
        """Comprehensive portfolio performance metrics."""
        if not self._trade_history:
            return {"status": "no_trades_yet"}

        trades = self._trade_history
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        total_profit = sum(t.pnl for t in wins) if wins else 0
        total_loss = abs(sum(t.pnl for t in losses)) if losses else 0

        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(trades) if trades else 0,
            "total_pnl": sum(t.pnl for t in trades),
            "total_profit": total_profit,
            "total_loss": total_loss,
            "profit_factor": total_profit / total_loss if total_loss > 0 else float("inf"),
            "avg_win": total_profit / len(wins) if wins else 0,
            "avg_loss": total_loss / len(losses) if losses else 0,
            "largest_win": max((t.pnl for t in wins), default=0),
            "largest_loss": min((t.pnl for t in losses), default=0),
            "avg_hold_time_seconds": (
                sum(t.hold_duration for t in trades) / len(trades)
            ),
            "consecutive_losses": self._current_consecutive_losses(),
        }

    def get_strategy_metrics(self) -> dict:
        """Performance breakdown by strategy."""
        by_strategy = defaultdict(list)
        for trade in self._trade_history:
            by_strategy[trade.strategy.value].append(trade)

        metrics = {}
        for strategy_name, trades in by_strategy.items():
            wins = [t for t in trades if t.pnl > 0]
            losses = [t for t in trades if t.pnl <= 0]
            total_profit = sum(t.pnl for t in wins)
            total_loss = abs(sum(t.pnl for t in losses))

            metrics[strategy_name] = {
                "trades": len(trades),
                "win_rate": len(wins) / len(trades) if trades else 0,
                "total_pnl": sum(t.pnl for t in trades),
                "profit_factor": total_profit / total_loss if total_loss > 0 else float("inf"),
                "avg_pnl": sum(t.pnl for t in trades) / len(trades) if trades else 0,
            }

        return metrics

    def get_account_metrics(self, account_id: str) -> dict:
        """Performance for a specific account."""
        trades = [t for t in self._trade_history
                  if t.account_id == account_id]
        if not trades:
            return {"status": "no_trades"}

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        return {
            "account_id": account_id,
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades),
            "total_pnl": sum(t.pnl for t in trades),
            "avg_pnl_per_trade": sum(t.pnl for t in trades) / len(trades),
            "best_trade": max(t.pnl for t in trades),
            "worst_trade": min(t.pnl for t in trades),
        }

    # -------------------------------------------------------------------------
    # EVAL Progress Tracking
    # -------------------------------------------------------------------------

    def get_eval_progress(self, accounts: dict[str, AccountState]) -> list[dict]:
        """Track progress toward EVAL pass for each account."""
        progress = []
        for aid, acct in accounts.items():
            if acct.phase != AccountPhase.EVAL:
                continue

            profit = acct.current_balance - acct.starting_balance
            target = self.config.apex.eval_profit_target
            min_days = self.config.apex.eval_min_trading_days

            progress.append({
                "account_id": aid,
                "status": acct.status.value,
                "profit": profit,
                "profit_target": target,
                "profit_pct": profit / target * 100 if target > 0 else 0,
                "trading_days": acct.trading_days,
                "min_days": min_days,
                "days_pct": acct.trading_days / min_days * 100 if min_days > 0 else 0,
                "drawdown_used_pct": acct.drawdown_used_pct * 100,
                "risk_level": acct.risk_level.value,
                "ready_to_pass": (
                    profit >= target and acct.trading_days >= min_days
                ),
            })

        return sorted(progress, key=lambda x: x["profit_pct"], reverse=True)

    # -------------------------------------------------------------------------
    # Performance Alerts
    # -------------------------------------------------------------------------

    async def _check_performance_alerts(self, latest_trade: TradeRecord):
        """Check if performance is degrading and needs intervention."""
        consecutive = self._current_consecutive_losses()

        if consecutive >= self._max_consecutive_losses:
            logger.warning("consecutive_loss_alert",
                           losses=consecutive,
                           account_id=latest_trade.account_id)
            await event_bus.publish(Event(
                event_type=EventType.RISK_WARNING,
                data={
                    "reason": "consecutive_losses",
                    "count": consecutive,
                    "last_strategy": latest_trade.strategy.value,
                },
                account_id=latest_trade.account_id,
                source="performance_monitor"
            ))

        # Check recent win rate (last 20 trades)
        recent = self._trade_history[-20:]
        if len(recent) >= 20:
            win_rate = sum(1 for t in recent if t.pnl > 0) / len(recent)
            if win_rate < self._min_win_rate_threshold:
                logger.warning("low_win_rate_alert",
                               win_rate=f"{win_rate:.1%}",
                               threshold=f"{self._min_win_rate_threshold:.1%}")

    def _current_consecutive_losses(self) -> int:
        """Count current streak of consecutive losing trades."""
        count = 0
        for trade in reversed(self._trade_history):
            if trade.pnl <= 0:
                count += 1
            else:
                break
        return count

    # -------------------------------------------------------------------------
    # Reporting
    # -------------------------------------------------------------------------

    def generate_daily_report(self, accounts: dict[str, AccountState]) -> dict:
        """End-of-day performance report."""
        today = datetime.utcnow().date()
        today_trades = [
            t for t in self._trade_history
            if t.exit_time.date() == today
        ]

        return {
            "date": today.isoformat(),
            "portfolio": self.get_portfolio_metrics(),
            "strategies": self.get_strategy_metrics(),
            "eval_progress": self.get_eval_progress(accounts),
            "today_summary": {
                "trades": len(today_trades),
                "pnl": sum(t.pnl for t in today_trades),
                "wins": sum(1 for t in today_trades if t.pnl > 0),
                "losses": sum(1 for t in today_trades if t.pnl <= 0),
            },
            "account_summary": {
                aid: {
                    "daily_pnl": acct.daily_pnl,
                    "total_pnl": acct.total_pnl,
                    "status": acct.status.value,
                    "risk_level": acct.risk_level.value,
                }
                for aid, acct in accounts.items()
            },
        }

    def should_pause_strategy(self, strategy: StrategyName) -> bool:
        """Determine if a strategy should be temporarily paused."""
        recent = [
            t for t in self._trade_history[-30:]
            if t.strategy == strategy
        ]
        if len(recent) < 10:
            return False

        win_rate = sum(1 for t in recent if t.pnl > 0) / len(recent)
        total_pnl = sum(t.pnl for t in recent)

        # Pause if win rate drops below 30% or strategy is net negative over 10+ trades
        return win_rate < 0.30 or (total_pnl < -500 and len(recent) >= 15)

    def should_shutdown(self) -> bool:
        """
        Determine if the entire system should shut down.
        Triggers on catastrophic underperformance.
        """
        if len(self._trade_history) < 20:
            return False

        recent = self._trade_history[-20:]
        total_pnl = sum(t.pnl for t in recent)
        win_rate = sum(1 for t in recent if t.pnl > 0) / len(recent)

        # Shutdown if: net -$2000+ over last 20 trades AND win rate < 25%
        return total_pnl < -2000 and win_rate < 0.25
