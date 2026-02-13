"""
Tests for the Risk Management Engine.
"""

import pytest
import asyncio
from datetime import datetime

from config.settings import SystemConfig
from src.risk.risk_manager import RiskManager
from src.core.models import (
    AccountState, AccountPhase, AccountStatus, RiskLevel,
    TradingSignal, StrategyName, SignalAction, Position, OrderSide,
)


@pytest.fixture
def config():
    return SystemConfig()


@pytest.fixture
def risk_manager(config):
    return RiskManager(config)


@pytest.fixture
def active_account():
    return AccountState(
        account_id="TEST_01",
        phase=AccountPhase.EVAL,
        status=AccountStatus.ACTIVE,
        starting_balance=50000.0,
        current_balance=50000.0,
        high_water_mark=50000.0,
        trailing_drawdown_remaining=2500.0,
    )


@pytest.fixture
def sample_signal():
    return TradingSignal(
        signal_id="test_001",
        strategy=StrategyName.VWAP_REVERSION,
        instrument="ES",
        action=SignalAction.LONG_ENTRY,
        price=5000.0,
        timestamp=datetime.utcnow(),
        stop_loss=4996.0,
        take_profit=5006.0,
        contracts=1,
        confidence=0.7,
    )


class TestPreTradeValidation:
    """Test Layer 1: Pre-trade validation."""

    @pytest.mark.asyncio
    async def test_valid_trade_passes(self, risk_manager, active_account, sample_signal):
        allowed, reason = await risk_manager.validate_trade(sample_signal, active_account)
        assert allowed is True
        assert reason == "passed"

    @pytest.mark.asyncio
    async def test_halted_account_rejected(self, risk_manager, active_account, sample_signal):
        active_account.status = AccountStatus.PAUSED
        allowed, reason = await risk_manager.validate_trade(sample_signal, active_account)
        assert allowed is False
        assert "status" in reason.lower()

    @pytest.mark.asyncio
    async def test_daily_loss_limit_blocks_trade(self, risk_manager, active_account, sample_signal):
        active_account.daily_pnl = -600.0  # Exceeds $500 limit
        allowed, reason = await risk_manager.validate_trade(sample_signal, active_account)
        assert allowed is False
        assert "daily loss" in reason.lower()

    @pytest.mark.asyncio
    async def test_drawdown_critical_blocks_trade(self, risk_manager, active_account, sample_signal):
        active_account.drawdown_used_pct = 0.75  # 75% > 70% critical threshold
        allowed, reason = await risk_manager.validate_trade(sample_signal, active_account)
        assert allowed is False
        assert "drawdown" in reason.lower()

    @pytest.mark.asyncio
    async def test_max_positions_blocks_trade(self, risk_manager, active_account, sample_signal):
        # Fill up positions
        active_account.open_positions = [
            Position("TEST_01", "ES", OrderSide.BUY, 1, 5000.0),
            Position("TEST_01", "NQ", OrderSide.BUY, 1, 18000.0),
        ]
        allowed, reason = await risk_manager.validate_trade(sample_signal, active_account)
        assert allowed is False
        assert "position" in reason.lower()

    @pytest.mark.asyncio
    async def test_excessive_single_trade_risk_blocked(self, risk_manager, active_account):
        # Signal with huge stop distance
        risky_signal = TradingSignal(
            signal_id="test_risky",
            strategy=StrategyName.VWAP_REVERSION,
            instrument="ES",
            action=SignalAction.LONG_ENTRY,
            price=5000.0,
            timestamp=datetime.utcnow(),
            stop_loss=4990.0,  # 10 points * $50 = $500 > $150 limit
            contracts=1,
            confidence=0.7,
        )
        allowed, reason = await risk_manager.validate_trade(risky_signal, active_account)
        assert allowed is False
        assert "single trade risk" in reason.lower()


class TestPositionSizing:
    """Test Layer 2: Position sizing."""

    def test_base_size_for_es(self, risk_manager, sample_signal, active_account):
        size = risk_manager.calculate_position_size(sample_signal, active_account)
        assert size >= 1
        assert size <= 4  # Self-imposed limit

    def test_reduced_risk_level_reduces_size(self, risk_manager, sample_signal, active_account):
        active_account.risk_level = RiskLevel.REDUCED
        size = risk_manager.calculate_position_size(sample_signal, active_account)
        normal_account = AccountState(
            account_id="TEST_02", phase=AccountPhase.EVAL,
            starting_balance=50000.0, current_balance=50000.0,
            high_water_mark=50000.0,
        )
        normal_size = risk_manager.calculate_position_size(sample_signal, normal_account)
        assert size <= normal_size

    def test_profit_buffer_enables_scale_up(self, risk_manager, sample_signal, active_account):
        # Account with significant profit buffer
        active_account.current_balance = 52000.0  # $2000 profit
        size_with_buffer = risk_manager.calculate_position_size(sample_signal, active_account)

        # Account at starting balance
        fresh_account = AccountState(
            account_id="TEST_03", phase=AccountPhase.EVAL,
            starting_balance=50000.0, current_balance=50000.0,
            high_water_mark=50000.0,
        )
        size_fresh = risk_manager.calculate_position_size(sample_signal, fresh_account)

        assert size_with_buffer >= size_fresh


class TestCircuitBreakers:
    """Test Layer 3: Account-level circuit breakers."""

    @pytest.mark.asyncio
    async def test_drawdown_warning_sets_reduced(self, risk_manager, active_account):
        active_account.high_water_mark = 50000.0
        active_account.current_balance = 49250.0  # $750 drawdown = 30% of $2500
        await risk_manager.update_account_risk(active_account)
        assert active_account.risk_level == RiskLevel.REDUCED

    @pytest.mark.asyncio
    async def test_drawdown_danger_sets_minimal(self, risk_manager, active_account):
        active_account.high_water_mark = 50000.0
        active_account.current_balance = 48750.0  # $1250 drawdown = 50%
        await risk_manager.update_account_risk(active_account)
        assert active_account.risk_level == RiskLevel.MINIMAL

    @pytest.mark.asyncio
    async def test_drawdown_critical_halts_and_flattens(self, risk_manager, active_account):
        active_account.high_water_mark = 50000.0
        active_account.current_balance = 48250.0  # $1750 drawdown = 70%
        await risk_manager.update_account_risk(active_account)
        assert active_account.risk_level == RiskLevel.HALTED
        assert active_account.status == AccountStatus.CRITICAL

    @pytest.mark.asyncio
    async def test_daily_loss_halts_account(self, risk_manager, active_account):
        active_account.daily_pnl = -550.0  # Exceeds $500 daily limit
        await risk_manager.update_account_risk(active_account)
        assert active_account.status == AccountStatus.DAILY_LIMIT
        assert active_account.risk_level == RiskLevel.HALTED
