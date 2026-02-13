"""
Base Strategy Interface

All strategies implement this interface. The system can run multiple
strategies simultaneously, each generating independent signals.
"""

import uuid
import structlog
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from src.core.models import TradingSignal, StrategyName, SignalAction

logger = structlog.get_logger()


class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.

    Each strategy:
    - Receives market data (OHLCV bars, tick data)
    - Evaluates entry/exit conditions
    - Generates TradingSignal objects
    - Does NOT manage orders or positions (that's the execution layer's job)
    """

    def __init__(self, name: StrategyName, instruments: list[str]):
        self.name = name
        self.instruments = instruments
        self.enabled = True
        self._signal_count = 0

    @abstractmethod
    async def evaluate(self, market_data: dict) -> Optional[TradingSignal]:
        """
        Evaluate current market conditions and return a signal if criteria are met.

        Args:
            market_data: Dict containing at minimum:
                - "instrument": str
                - "bars": list of OHLCV dicts (most recent last)
                - "current_price": float
                - "timestamp": datetime
                - "volume": float (current bar volume)
                - "vwap": float (if available)
                - "atr": float (if pre-calculated)

        Returns:
            TradingSignal if conditions are met, None otherwise.
        """
        pass

    @abstractmethod
    async def should_exit(self, position: dict,
                          market_data: dict) -> Optional[TradingSignal]:
        """
        Evaluate whether an existing position should be closed.

        Args:
            position: Current position info
            market_data: Current market data

        Returns:
            Exit signal if position should be closed, None otherwise.
        """
        pass

    def create_signal(self, instrument: str, action: SignalAction,
                      price: float, stop_loss: float = None,
                      take_profit: float = None, confidence: float = 0.5,
                      contracts: int = 1, metadata: dict = None) -> TradingSignal:
        """Helper to create properly formed signals."""
        self._signal_count += 1
        return TradingSignal(
            signal_id=f"{self.name.value}_{uuid.uuid4().hex[:8]}",
            strategy=self.name,
            instrument=instrument,
            action=action,
            price=price,
            timestamp=datetime.utcnow(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            contracts=contracts,
            confidence=confidence,
            metadata=metadata or {},
        )

    def get_stats(self) -> dict:
        return {
            "strategy": self.name.value,
            "instruments": self.instruments,
            "enabled": self.enabled,
            "signals_generated": self._signal_count,
        }
