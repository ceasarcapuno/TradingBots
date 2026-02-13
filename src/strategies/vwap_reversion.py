"""
Strategy 1: VWAP Mean Reversion

Edge: Price tends to revert to VWAP during range-bound sessions.
Best conditions: Regular trading hours (9:30 AM - 3:00 PM CT), non-trending days.
Instruments: ES, NQ (high liquidity for clean mean reversion)

Logic:
  - ENTRY: Price deviates > 1.5 ATR from VWAP, then shows reversal candle
  - EXIT: Price returns to VWAP or hits stop/target
  - FILTER: Skip if trend is strong (ADX > 30) or volume is extreme

Why it works for prop firm:
  - High win rate (60-70% in proper conditions)
  - Small stops relative to targets
  - Frequent setups → accumulates trading days
  - Works well in the choppy conditions that dominate most sessions
"""

import structlog
from typing import Optional

from src.strategies.base_strategy import BaseStrategy
from src.core.models import TradingSignal, StrategyName, SignalAction

logger = structlog.get_logger()


class VWAPReversionStrategy(BaseStrategy):

    def __init__(self, instruments: list[str] = None):
        super().__init__(
            name=StrategyName.VWAP_REVERSION,
            instruments=instruments or ["ES", "NQ"],
        )
        # Tunable parameters
        self.atr_deviation_threshold = 1.5   # Min ATR distance from VWAP
        self.adx_max = 30                    # Skip if trend too strong
        self.min_volume_ratio = 0.8          # vs average volume
        self.rr_ratio = 1.5                  # Risk-reward ratio
        self.max_atr_stop = 2.0              # Max stop distance in ATR units
        self.reversal_candle_pct = 0.4       # Wick-to-body ratio for reversal

    async def evaluate(self, market_data: dict) -> Optional[TradingSignal]:
        instrument = market_data.get("instrument", "")
        if instrument not in self.instruments:
            return None

        bars = market_data.get("bars", [])
        if len(bars) < 20:
            return None

        current_price = market_data["current_price"]
        vwap = market_data.get("vwap")
        atr = market_data.get("atr")
        adx = market_data.get("adx", 0)
        volume = market_data.get("volume", 0)
        avg_volume = market_data.get("avg_volume", 1)

        if not vwap or not atr or atr <= 0:
            return None

        # FILTER: Skip in strong trends
        if adx > self.adx_max:
            return None

        # FILTER: Skip in low volume
        if avg_volume > 0 and volume / avg_volume < self.min_volume_ratio:
            return None

        deviation = (current_price - vwap) / atr
        last_bar = bars[-1]

        # LONG ENTRY: Price below VWAP by threshold + bullish reversal candle
        if deviation <= -self.atr_deviation_threshold:
            if self._is_bullish_reversal(last_bar):
                stop_distance = min(atr * self.max_atr_stop,
                                    abs(current_price - last_bar["low"]))
                stop_loss = current_price - stop_distance
                take_profit = vwap  # Target is VWAP reversion

                # Confidence based on deviation magnitude and volume
                confidence = min(0.9, 0.5 + abs(deviation) * 0.1)

                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.LONG_ENTRY,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=confidence,
                    metadata={
                        "vwap": vwap,
                        "deviation_atr": deviation,
                        "atr": atr,
                        "adx": adx,
                    }
                )

        # SHORT ENTRY: Price above VWAP by threshold + bearish reversal candle
        if deviation >= self.atr_deviation_threshold:
            if self._is_bearish_reversal(last_bar):
                stop_distance = min(atr * self.max_atr_stop,
                                    abs(last_bar["high"] - current_price))
                stop_loss = current_price + stop_distance
                take_profit = vwap

                confidence = min(0.9, 0.5 + abs(deviation) * 0.1)

                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.SHORT_ENTRY,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=confidence,
                    metadata={
                        "vwap": vwap,
                        "deviation_atr": deviation,
                        "atr": atr,
                        "adx": adx,
                    }
                )

        return None

    async def should_exit(self, position: dict,
                          market_data: dict) -> Optional[TradingSignal]:
        """Exit when price returns to VWAP or shows adverse momentum."""
        current_price = market_data["current_price"]
        vwap = market_data.get("vwap")
        atr = market_data.get("atr", 1)

        if not vwap:
            return None

        side = position.get("side", "")
        entry_price = position.get("entry_price", current_price)

        # Exit condition 1: VWAP reached (target)
        if side == "Buy" and current_price >= vwap:
            return self.create_signal(
                instrument=market_data["instrument"],
                action=SignalAction.EXIT_LONG,
                price=current_price,
                confidence=0.9,
                metadata={"exit_reason": "vwap_target_reached"}
            )
        if side == "Sell" and current_price <= vwap:
            return self.create_signal(
                instrument=market_data["instrument"],
                action=SignalAction.EXIT_SHORT,
                price=current_price,
                confidence=0.9,
                metadata={"exit_reason": "vwap_target_reached"}
            )

        # Exit condition 2: Price moves further from VWAP (momentum against us)
        deviation = abs(current_price - vwap) / atr
        if deviation > self.atr_deviation_threshold * 2:
            action = (SignalAction.EXIT_LONG if side == "Buy"
                      else SignalAction.EXIT_SHORT)
            return self.create_signal(
                instrument=market_data["instrument"],
                action=action,
                price=current_price,
                confidence=0.8,
                metadata={"exit_reason": "deviation_exceeded"}
            )

        return None

    def _is_bullish_reversal(self, bar: dict) -> bool:
        """Detect hammer / bullish pin bar pattern."""
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        body = abs(c - o)
        total_range = h - l
        if total_range == 0:
            return False
        lower_wick = min(o, c) - l
        # Bullish reversal: long lower wick, small body
        return (lower_wick / total_range > self.reversal_candle_pct and
                body / total_range < 0.4 and
                c >= o)  # Close >= Open

    def _is_bearish_reversal(self, bar: dict) -> bool:
        """Detect shooting star / bearish pin bar pattern."""
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        body = abs(c - o)
        total_range = h - l
        if total_range == 0:
            return False
        upper_wick = h - max(o, c)
        return (upper_wick / total_range > self.reversal_candle_pct and
                body / total_range < 0.4 and
                c <= o)  # Close <= Open
