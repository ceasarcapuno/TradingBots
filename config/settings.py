"""
Central configuration for the Autonomous Trading System.
All parameters are tunable via environment variables or .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from enum import Enum


class AccountPhase(str, Enum):
    EVAL = "EVAL"
    PERFORMANCE = "PERFORMANCE"


class TradingInstrument(str, Enum):
    ES = "ES"      # E-mini S&P 500
    NQ = "NQ"      # E-mini Nasdaq 100
    MES = "MES"    # Micro E-mini S&P 500
    MNQ = "MNQ"    # Micro E-mini Nasdaq 100
    BTC = "BTC"    # Bitcoin futures
    ETH = "ETH"    # Ethereum futures


class ApexRules(BaseSettings):
    """Apex Trader Funding rule parameters — hard constraints."""

    # EVAL account rules ($50K)
    eval_profit_target: float = 3000.0
    eval_max_drawdown: float = 2500.0       # Trailing threshold (end-of-day)
    eval_daily_loss_limit: float = -1500.0   # Not enforced by Apex but self-imposed safety
    eval_max_contracts_es: int = 10
    eval_max_contracts_nq: int = 10
    eval_max_contracts_mes: int = 50
    eval_max_contracts_mnq: int = 50
    eval_min_trading_days: int = 7
    eval_max_position_size_per_trade: int = 4  # Conservative self-limit

    # PERFORMANCE account rules ($50K)
    perf_max_drawdown: float = 2500.0        # Trailing threshold
    perf_daily_loss_limit: float = -1500.0   # Self-imposed
    perf_max_contracts_es: int = 10
    perf_max_contracts_nq: int = 10
    perf_payout_threshold: float = 100.0     # Min balance above start for payout

    # Universal rules
    no_trading_window_start: str = "16:59"   # CT — flatten before close
    no_trading_window_end: str = "18:00"     # CT — session break
    flatten_before_close_minutes: int = 5
    news_blackout_minutes_before: int = 5
    news_blackout_minutes_after: int = 5

    class Config:
        env_prefix = "APEX_"


class RiskConfig(BaseSettings):
    """Risk management parameters."""

    # Per-account limits (conservative defaults)
    max_daily_loss_pct: float = 0.015         # 1.5% of account
    max_daily_loss_absolute: float = 500.0    # Hard dollar cap per day
    max_single_trade_risk: float = 150.0      # Max loss per trade in dollars
    max_open_positions: int = 2               # Per account
    max_correlated_positions: int = 3         # Across portfolio for same instrument

    # Drawdown circuit breakers (as % of trailing max)
    drawdown_warning_pct: float = 0.30        # 30% of max DD used → reduce size
    drawdown_danger_pct: float = 0.50         # 50% of max DD used → min size only
    drawdown_critical_pct: float = 0.70       # 70% of max DD used → stop trading

    # Portfolio-level limits
    portfolio_max_simultaneous_trades: int = 10  # Across all 20 accounts
    portfolio_max_daily_loss: float = 5000.0     # Across all accounts combined
    portfolio_correlation_limit: float = 0.7      # Max correlation between account P&L

    # Position sizing
    base_contracts_es: int = 1
    base_contracts_nq: int = 1
    base_contracts_mes: int = 2
    base_contracts_mnq: int = 2
    scale_up_threshold_profit: float = 1500.0  # Profit buffer before sizing up
    scale_up_max_multiplier: float = 2.0

    # Stop loss parameters
    es_stop_ticks: int = 16                   # 4 points = $200
    nq_stop_ticks: int = 16                   # 4 points = $80
    es_target_ticks: int = 24                 # 6 points = $300  (1.5:1 R:R)
    nq_target_ticks: int = 24                 # 6 points = $120  (1.5:1 R:R)

    class Config:
        env_prefix = "RISK_"


class WebhookConfig(BaseSettings):
    """Webhook server and TradingView integration."""

    host: str = "0.0.0.0"
    port: int = 8443
    secret_token: str = Field(default="CHANGE_ME_IN_ENV", description="Shared secret for webhook auth")
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    max_signal_age_seconds: int = 30          # Reject stale signals
    rate_limit_per_minute: int = 60

    class Config:
        env_prefix = "WEBHOOK_"


class TradovateConfig(BaseSettings):
    """Tradovate API connection settings."""

    api_url: str = "https://live.tradovateapi.com/v1"
    demo_api_url: str = "https://demo.tradovateapi.com/v1"
    ws_url: str = "wss://live.tradovateapi.com/v1/websocket"
    demo_ws_url: str = "wss://demo.tradovateapi.com/v1/websocket"
    use_demo: bool = True                     # Start with demo for testing

    # Auth — set per-account in account configs
    username: str = ""
    password: str = ""
    app_id: Optional[str] = None
    app_version: str = "1.0"
    cid: Optional[int] = None
    sec: Optional[str] = None

    request_timeout: int = 10
    max_retries: int = 3
    retry_delay: float = 1.0

    class Config:
        env_prefix = "TRADOVATE_"


class CopyTradingConfig(BaseSettings):
    """Copy trading and detection avoidance settings."""

    # Timing jitter to avoid synchronized execution
    min_delay_ms: int = 500                   # Min delay between account executions
    max_delay_ms: int = 5000                  # Max delay between account executions
    jitter_distribution: str = "gaussian"      # gaussian, uniform, or exponential

    # Position sizing variance
    size_variance_pct: float = 0.20           # ±20% size variation between accounts
    skip_probability: float = 0.10            # 10% chance any account skips a signal

    # Account grouping (trade in rotating subsets)
    group_size: int = 5                       # Accounts per active group
    group_rotation_trades: int = 10           # Rotate groups every N signals

    # Strategy distribution
    strategy_shuffle: bool = True             # Assign different strategies to different groups
    entry_price_variance_ticks: int = 2       # Vary limit prices by ±2 ticks

    class Config:
        env_prefix = "COPY_"


class SystemConfig(BaseSettings):
    """Top-level system configuration."""

    total_accounts: int = 20
    db_path: str = "data/trading.db"
    log_level: str = "INFO"
    log_file: str = "logs/trading.log"

    # Trading hours (CT = Central Time, Apex standard)
    trading_start_ct: str = "18:00"           # Sunday evening open
    trading_end_ct: str = "16:59"             # Friday close
    preferred_session_start_ct: str = "08:30"  # Regular session open
    preferred_session_end_ct: str = "15:00"    # Wind down before close

    # Feature flags
    enable_copy_trading: bool = True
    enable_news_filter: bool = True
    enable_volatility_filter: bool = True
    enable_portfolio_correlation: bool = True
    dry_run: bool = True                      # Paper trade mode — no live orders

    apex: ApexRules = ApexRules()
    risk: RiskConfig = RiskConfig()
    webhook: WebhookConfig = WebhookConfig()
    tradovate: TradovateConfig = TradovateConfig()
    copy_trading: CopyTradingConfig = CopyTradingConfig()

    class Config:
        env_prefix = "SYS_"
        env_file = ".env"
        env_file_encoding = "utf-8"
