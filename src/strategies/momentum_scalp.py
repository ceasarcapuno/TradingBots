"""
Strategy 3: Momentum Scalp

Edge: Short-term momentum persistence in high-volume conditions.
      Captures 2-6 point moves in ES/NQ using momentum confirmation.
Best conditions: Trending sessions, post-news moves, high volume.
Instruments: ES, NQ, and optionally crypto futures (BTC, ETH)

Logic:
  - ENTRY: EMA crossover (8/21) confirmed by RSI direction and volume spike
  - EXIT: Quick target (1-2 ATR) with tight trailing stop
  - FILTER: Only trade when ADX > 20 and volume > 1.2x average

Why it works for prop firm:
  - Fast in-and-out → limited time exposure
  - Works in trending conditions (complements VWAP reversion)
  - Can generate multiple small wins per day
  - Tight stops keep individual trade risk low
"""

import structlog
from typing import Optional

from src.strategies.base_strategy import BaseStrategy
from src.core.models import TradingSignal, StrategyName, SignalAction

logger = structlog.get_logger()


class MomentumScalpStrategy(BaseStrategy):

    def __init__(self, instruments: list[str] = None):
        super().__init__(
            name=StrategyName.MOMENTUM_SCALP,
            instruments=instruments or ["ES", "NQ"],
        )
        # Parameters
        self.fast_ema_period = 8
        self.slow_ema_period = 21
        self.rsi_period = 14
        self.rsi_long_threshold = 55          # RSI must be above for longs
        self.rsi_short_threshold = 45          # RSI must be below for shorts
        self.adx_min = 20                      # Minimum trend strength
        self.volume_min_ratio = 1.2            # Volume surge required
        self.target_atr_multiplier = 1.5       # Quick target
        self.stop_atr_multiplier = 1.0         # Tight stop
        self.max_trades_per_day = 4            # Limit overtrading
        self.min_bar_momentum_pct = 0.001      # Minimum bar size as % of price

        # Daily state
        self._trades_today: dict[str, int] = {}
        self._last_ema_cross: dict[str, str] = {}  # instrument → "bullish"/"bearish"

    async def evaluate(self, market_data: dict) -> Optional[TradingSignal]:
        instrument = market_data.get("instrument", "")
        if instrument not in self.instruments:
            return None

        bars = market_data.get("bars", [])
        if len(bars) < self.slow_ema_period + 5:
            return None

        # Check daily trade limit
        if self._trades_today.get(instrument, 0) >= self.max_trades_per_day:
            return None

        current_price = market_data["current_price"]
        atr = market_data.get("atr")
        adx = market_data.get("adx", 0)
        rsi = market_data.get("rsi", 50)
        volume = market_data.get("volume", 0)
        avg_volume = market_data.get("avg_volume", 1)

        if not atr or atr <= 0:
            return None

        # FILTER: Need trending conditions
        if adx < self.adx_min:
            return None

        # FILTER: Need volume confirmation
        if avg_volume > 0 and volume / avg_volume < self.volume_min_ratio:
            return None

        # Calculate EMAs from bars
        closes = [b["close"] for b in bars]
        fast_ema = self._ema(closes, self.fast_ema_period)
        slow_ema = self._ema(closes, self.slow_ema_period)

        if fast_ema is None or slow_ema is None:
            return None

        # Detect EMA crossover
        prev_closes = closes[:-1]
        prev_fast = self._ema(prev_closes, self.fast_ema_period)
        prev_slow = self._ema(prev_closes, self.slow_ema_period)

        if prev_fast is None or prev_slow is None:
            return None

        # Check for minimum bar momentum
        last_bar = bars[-1]
        bar_range = abs(last_bar["close"] - last_bar["open"])
        if current_price > 0 and bar_range / current_price < self.min_bar_momentum_pct:
            return None

        # BULLISH CROSSOVER: fast crosses above slow
        if prev_fast <= prev_slow and fast_ema > slow_ema:
            if rsi > self.rsi_long_threshold:
                stop_loss = current_price - (atr * self.stop_atr_multiplier)
                take_profit = current_price + (atr * self.target_atr_multiplier)

                confidence = self._calculate_confidence(
                    adx, rsi, volume / avg_volume if avg_volume > 0 else 1, "long"
                )

                self._trades_today[instrument] = (
                    self._trades_today.get(instrument, 0) + 1
                )
                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.LONG_ENTRY,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=confidence,
                    metadata={
                        "fast_ema": fast_ema,
                        "slow_ema": slow_ema,
                        "rsi": rsi,
                        "adx": adx,
                        "volume_ratio": volume / avg_volume if avg_volume > 0 else 0,
                    }
                )

        # BEARISH CROSSOVER: fast crosses below slow
        if prev_fast >= prev_slow and fast_ema < slow_ema:
            if rsi < self.rsi_short_threshold:
                stop_loss = current_price + (atr * self.stop_atr_multiplier)
                take_profit = current_price - (atr * self.target_atr_multiplier)

                confidence = self._calculate_confidence(
                    adx, rsi, volume / avg_volume if avg_volume > 0 else 1, "short"
                )

                self._trades_today[instrument] = (
                    self._trades_today.get(instrument, 0) + 1
                )
                return self.create_signal(
                    instrument=instrument,
                    action=SignalAction.SHORT_ENTRY,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=confidence,
                    metadata={
                        "fast_ema": fast_ema,
                        "slow_ema": slow_ema,
                        "rsi": rsi,
                        "adx": adx,
                        "volume_ratio": volume / avg_volume if avg_volume > 0 else 0,
                    }
                )

        return None

    async def should_exit(self, position: dict,
                          market_data: dict) -> Optional[TradingSignal]:
        """Quick exit: reverse EMA cross or momentum fading."""
        instrument = market_data.get("instrument", "")
        bars = market_data.get("bars", [])
        current_price = market_data["current_price"]
        rsi = market_data.get("rsi", 50)

        if len(bars) < self.slow_ema_period + 2:
            return None

        side = position.get("side", "")

        closes = [b["close"] for b in bars]
        fast_ema = self._ema(closes, self.fast_ema_period)
        slow_ema = self._ema(closes, self.slow_ema_period)

        if fast_ema is None or slow_ema is None:
            return None

        # Exit longs if fast EMA drops below slow EMA (momentum lost)
        if side == "Buy" and fast_ema < slow_ema:
            return self.create_signal(
                instrument=instrument,
                action=SignalAction.EXIT_LONG,
                price=current_price,
                confidence=0.8,
                metadata={"exit_reason": "ema_reverse_cross"}
            )

        # Exit shorts if fast EMA rises above slow EMA
        if side == "Sell" and fast_ema > slow_ema:
            return self.create_signal(
                instrument=instrument,
                action=SignalAction.EXIT_SHORT,
                price=current_price,
                confidence=0.8,
                metadata={"exit_reason": "ema_reverse_cross"}
            )

        # Exit longs if RSI drops to overbought reversal zone
        if side == "Buy" and rsi > 75:
            return self.create_signal(
                instrument=instrument,
                action=SignalAction.EXIT_LONG,
                price=current_price,
                confidence=0.7,
                metadata={"exit_reason": "rsi_overbought"}
            )

        # Exit shorts if RSI rises to oversold reversal zone
        if side == "Sell" and rsi < 25:
            return self.create_signal(
                instrument=instrument,
                action=SignalAction.EXIT_SHORT,
                price=current_price,
                confidence=0.7,
                metadata={"exit_reason": "rsi_oversold"}
            )

        return None

    def _ema(self, data: list[float], period: int) -> Optional[float]:
        """Calculate EMA of the last `period` values."""
        if len(data) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period  # SMA seed
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_confidence(self, adx: float, rsi: float,
                              volume_ratio: float, direction: str) -> float:
        """Multi-factor confidence score."""
        score = 0.5

        # ADX contribution (stronger trend → higher confidence)
        if adx > 30:
            score += 0.1
        if adx > 40:
            score += 0.05

        # RSI contribution
        if direction == "long" and rsi > 60:
            score += 0.1
        elif direction == "short" and rsi < 40:
            score += 0.1

        # Volume contribution
        if volume_ratio > 1.5:
            score += 0.1
        if volume_ratio > 2.0:
            score += 0.05

        return min(0.9, score)

    def reset_daily(self):
        """Reset daily trade counters."""
        self._trades_today.clear()
        self._last_ema_cross.clear()
