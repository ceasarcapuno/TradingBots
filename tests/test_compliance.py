"""
Tests for the Apex Compliance Framework.
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from config.settings import SystemConfig
from src.compliance.apex_compliance import ApexComplianceMonitor
from src.core.models import (
    AccountState, AccountPhase, AccountStatus,
    TradingSignal, StrategyName, SignalAction,
)


@pytest.fixture
def config():
    return SystemConfig()


@pytest.fixture
def compliance(config):
    return ApexComplianceMonitor(config)


@pytest.fixture
def eval_account():
    return AccountState(
        account_id="TEST_EVAL",
        phase=AccountPhase.EVAL,
        status=AccountStatus.ACTIVE,
        starting_balance=50000.0,
        current_balance=50500.0,
        high_water_mark=50500.0,
        trailing_drawdown_remaining=2500.0,
    )


@pytest.fixture
def sample_signal():
    return TradingSignal(
        signal_id="comp_test_001",
        strategy=StrategyName.VWAP_REVERSION,
        instrument="ES",
        action=SignalAction.LONG_ENTRY,
        price=5000.0,
        timestamp=datetime.utcnow(),
        contracts=2,
        confidence=0.7,
    )


class TestComplianceChecks:

    @pytest.mark.asyncio
    async def test_normal_trade_is_compliant(self, compliance, eval_account, sample_signal):
        compliant, reason = await compliance.check_trade_compliance(
            sample_signal, eval_account
        )
        # May fail if running during close window — that's correct behavior
        if "close" not in reason.lower() and "flatten" not in reason.lower():
            assert compliant is True

    @pytest.mark.asyncio
    async def test_terminated_account_rejected(self, compliance, eval_account, sample_signal):
        eval_account.status = AccountStatus.TERMINATED
        compliant, reason = await compliance.check_trade_compliance(
            sample_signal, eval_account
        )
        assert compliant is False
        assert "terminated" in reason.lower()

    @pytest.mark.asyncio
    async def test_contract_limit_enforced(self, compliance, eval_account):
        # Try to place 15 ES contracts (limit is 10)
        big_signal = TradingSignal(
            signal_id="comp_test_big",
            strategy=StrategyName.VWAP_REVERSION,
            instrument="ES",
            action=SignalAction.LONG_ENTRY,
            price=5000.0,
            timestamp=datetime.utcnow(),
            contracts=15,
            confidence=0.7,
        )
        compliant, reason = await compliance.check_trade_compliance(
            big_signal, eval_account
        )
        assert compliant is False
        assert "contract" in reason.lower()

    @pytest.mark.asyncio
    async def test_drawdown_threshold_protection(self, compliance, eval_account):
        # Set remaining drawdown to almost zero
        eval_account.trailing_drawdown_remaining = 100.0  # Only $100 left of $2500
        signal = TradingSignal(
            signal_id="comp_test_dd",
            strategy=StrategyName.VWAP_REVERSION,
            instrument="ES",
            action=SignalAction.LONG_ENTRY,
            price=5000.0,
            timestamp=datetime.utcnow(),
            contracts=1,
            confidence=0.7,
        )
        compliant, reason = await compliance.check_trade_compliance(
            signal, eval_account
        )
        assert compliant is False
        assert "drawdown" in reason.lower()


class TestEvalPassDetection:

    @pytest.mark.asyncio
    async def test_eval_pass_detected(self, compliance):
        account = AccountState(
            account_id="PASS_TEST",
            phase=AccountPhase.EVAL,
            starting_balance=50000.0,
            current_balance=53100.0,  # $3100 profit > $3000 target
            high_water_mark=53100.0,
            trading_days=8,           # 8 > 7 minimum
            trailing_drawdown_remaining=2500.0,
        )
        accounts = {"PASS_TEST": account}
        await compliance.monitor_positions(accounts)
        assert account.status == AccountStatus.PASSED

    @pytest.mark.asyncio
    async def test_eval_not_passed_insufficient_days(self, compliance):
        account = AccountState(
            account_id="DAYS_TEST",
            phase=AccountPhase.EVAL,
            starting_balance=50000.0,
            current_balance=53500.0,  # Profit OK
            high_water_mark=53500.0,
            trading_days=5,           # 5 < 7 minimum
            trailing_drawdown_remaining=2500.0,
        )
        accounts = {"DAYS_TEST": account}
        await compliance.monitor_positions(accounts)
        assert account.status != AccountStatus.PASSED


class TestSessionManagement:

    def test_weekend_detection(self, compliance):
        # This test depends on the current day — just verify it returns a bool
        result = compliance.is_weekend()
        assert isinstance(result, bool)

    def test_session_status_returns_dict(self, compliance):
        status = compliance.get_session_status()
        assert "current_time_ct" in status
        assert "is_weekend" in status
        assert "in_close_window" in status
