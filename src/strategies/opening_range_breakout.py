"""
Strategy 2: Opening Range Breakout (ORB)

Edge: The first 15-30 minutes of regular session establish a range.
      Breakouts from this range carry momentum from institutional order flow.
Best conditions: High-volume opens, news catalysts, trend days.
Instruments: ES, NQ (best liquidity during RTH open)

Logic:
  - SETUP: Define opening range (high/low of first 15 min of RTH)
  - ENTRY: Price breaks above/below range with volume confirmation
  - EXIT: Opposite range boundary (target), or trailing stop
  - FILTER: Skip if range is too narrow (< 0.5 ATR) or too wide (> 3 ATR)

Why it works for prop firm:
  - Catches the biggest moves of the day (trend days)
  - Defined risk (range boundary as stop)
  - Trades only during highest liquidity period
  - One trade per day → disciplined, consistent
"""

import structlog
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from src.strategies.base_strategy import BaseStrategy
from src.core.models import TradingSignal, StrategyName, SignalAction

logger = structlog.get_logger()

CT = ZoneInfo("America/Chicago")


class OpeningRangeBreakoutStrategy(BaseStrategy):

    def __init__(self, instruments: list[str] = None):
        super().__init__(
            name=StrategyName.OPENING_RANGE_BREAKOUT,
            instruments=instruments or ["ES", "NQ"],
        )
        # Parameters
        self.range_period_minutes = 15       # First 15 min of RTH
        self.rth_open = time(8, 30)          # CT
        self.range_end = time(8, 45)         # CT (8:30 + 15 min)
        self.last_entry_time = time(11, 0)   # No new entries after 11 AM CT
        self.min_range_atr = 0.5             # Min range width in ATR
        self.max_range_atr = 3.0             # Max range width in ATR
        self.breakout_buffer_ticks = 2       # Price must exceed range by N ticks
        self.volume_surge_ratio = 1.3        # Volume on breakout bar vs average
        self.trailing_stop_atr = 1.5         # Trailing stop distance
        self.max_target_atr = 4.0            # Max target in ATR units

        # Daily state (reset each day)
        self._range_high: dict[str, float] = {}
        self._range_low: dict[str, float] = {}
        self._range_set: dict[str, bool] = {}
        self._traded_today: dict[str, bool] = {}
        self._last_reset_date: Optional[datetime] = None

    async def evaluate(self, market_data: dict) -> Optional[TradingSignal]:
        instrument = market_data.get("instrument", "")
        if instrument not in self.instruments:
            return None

        now_ct = datetime.now(CT)
        self._maybe_reset_daily(now_ct)

        bars = market_data.get("bars", [])
        current_price = market_data["current_price"]
        atr = market_data.get("atr")
        volume = market_data.get("volume", 0)
        avg_volume = market_data.get("avg_volume", 1)

        if not atr or atr <= 0:
            return None

        current_time = now_ct.time()

        # Phase 1: Build the opening range
        if self.rth_open <= current_time < self.range_end:
            self._update_range(instrument, bars, current_price)
            return None

        # Phase 2: Look for breakout after range is established
        if not self._range_set.get(instrument, False):
            return None

        # Already traded this instrument today → skip (one entry per day)
        if self._traded_today.get(instrument, False):
            return None

        # Too late in the day
        if current_time > self.last_entry_time:
            return None

        range_high = self._range_high[instrument]
        range_low = self._range_low[instrument]
        range_width = range_high - range_low

        # Filter: range must be within acceptable ATR bounds
        range_atr = range_width / atr
        if range_atr < self.min_range_atr or range_atr > self.max_range_atr:
            return None

        tick_size = self._get_tick_size(instrument)
        buffer = self.breakout_buffer_ticks * tick_size

        # LONG BREAKOUT: price above range high with volume
        if current_price > range_high + buffer:
            if avg_volume > 0 and volume / avg_volume >= self.volume_surge_ratio:
                stop_loss = range_low  # Stop at bottom of range
                target_distance = min(range_width * 2, atr * self.max_target_atr)
                take_profit = current_price + target_distance

                confidence = min(0.85, 0.5 + (volume / avg_volume - 1) * 0.2)

                self._traded_today[instrument] = True
                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.LONG_ENTRY,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=confidence,
                    metadata={
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_width": range_width,
                        "volume_ratio": volume / avg_volume,
                    }
                )

        # SHORT BREAKOUT: price below range low with volume
        if current_price < range_low - buffer:
            if avg_volume > 0 and volume / avg_volume >= self.volume_surge_ratio:
                stop_loss = range_high
                target_distance = min(range_width * 2, atr * self.max_target_atr)
                take_profit = current_price - target_distance

                confidence = min(0.85, 0.5 + (volume / avg_volume - 1) * 0.2)

                self._traded_today[instrument] = True
                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.SHORT_ENTRY,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=confidence,
                    metadata={
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_width": range_width,
                        "volume_ratio": volume / avg_volume,
                    }
                )

        return None

    async def should_exit(self, position: dict,
                          market_data: dict) -> Optional[TradingSignal]:
        """Trailing stop exit or time-based exit."""
        instrument = market_data.get("instrument", "")
        current_price = market_data["current_price"]
        atr = market_data.get("atr", 1)
        now_ct = datetime.now(CT)

        side = position.get("side", "")
        entry_price = position.get("entry_price", current_price)
        highest_since_entry = position.get("highest_price", current_price)
        lowest_since_entry = position.get("lowest_price", current_price)

        trailing_distance = atr * self.trailing_stop_atr

        # Time-based exit: close before 3 PM CT
        if now_ct.time() >= time(14, 45):
            action = (SignalAction.EXIT_LONG if side == "Buy"
                      else SignalAction.EXIT_SHORT)
            return self.create_signal(
                instrument=instrument,
                action=action,
                price=current_price,
                confidence=0.95,
                metadata={"exit_reason": "time_exit"}
            )

        # Trailing stop for longs
        if side == "Buy":
            trailing_stop = highest_since_entry - trailing_distance
            if current_price <= trailing_stop and current_price > entry_price:
                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.EXIT_LONG,
                    price=current_price,
                    confidence=0.85,
                    metadata={"exit_reason": "trailing_stop",
                              "trailing_stop": trailing_stop}
                )

        # Trailing stop for shorts
        if side == "Sell":
            trailing_stop = lowest_since_entry + trailing_distance
            if current_price >= trailing_stop and current_price < entry_price:
                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.EXIT_SHORT,
                    price=current_price,
                    confidence=0.85,
                    metadata={"exit_reason": "trailing_stop",
                              "trailing_stop": trailing_stop}
                )

        return None

    def _update_range(self, instrument: str, bars: list, current_price: float):
        """Build the opening range from the first N minutes of RTH."""
        if instrument not in self._range_high:
            self._range_high[instrument] = current_price
            self._range_low[instrument] = current_price
            self._range_set[instrument] = False
        else:
            self._range_high[instrument] = max(
                self._range_high[instrument], current_price
            )
            self._range_low[instrument] = min(
                self._range_low[instrument], current_price
            )

        # At range_end, mark as set
        now_ct = datetime.now(CT)
        if now_ct.time() >= self.range_end:
            self._range_set[instrument] = True
            logger.info("opening_range_set",
                        instrument=instrument,
                        high=self._range_high[instrument],
                        low=self._range_low[instrument])

    def _maybe_reset_daily(self, now_ct: datetime):
        """Reset daily state at start of each session."""
        today = now_ct.date()
        if self._last_reset_date != today:
            self._range_high.clear()
            self._range_low.clear()
            self._range_set.clear()
            self._traded_today.clear()
            self._last_reset_date = today

    def _get_tick_size(self, instrument: str) -> float:
        sizes = {"ES": 0.25, "NQ": 0.25, "MES": 0.25, "MNQ": 0.25}
        return sizes.get(instrument, 0.25)
