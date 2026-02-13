# Autonomous Trading System — Architecture & Strategic Blueprint

## System Overview

```
TradingView Pine Script (3 strategies)
        │
        ▼ Webhook (HTTPS POST, JSON)
┌───────────────────────────────────────────┐
│           Webhook Server (FastAPI)        │
│  - Token auth, rate limiting, age check   │
└────────────────┬──────────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────────┐
│         Copy Trading Engine               │
│  - Account grouping (4 groups of 5)       │
│  - Timing jitter (0.5-5s gaussian)        │
│  - Size variance (±20%)                   │
│  - Skip probability (10%)                 │
│  - Strategy rotation per group            │
│  - Price variance (±2 ticks)              │
└────────────────┬──────────────────────────┘
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│  Risk    │ │Compliance│ │  Market  │
│  Manager │ │ Monitor  │ │  Intel   │
│ (4-layer)│ │  (Apex)  │ │(News/Vol)│
└────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │             │
     └────────────┼─────────────┘
                  │
                  ▼
┌───────────────────────────────────────────┐
│          Account Manager                  │
│  20x TradovateClient instances            │
│  Order routing, state sync, flatten       │
└────────────────┬──────────────────────────┘
                 │
                 ▼
         Tradovate API (20 accounts)
```

## 1. Risk Architecture

### Four-Layer Defense

**Layer 1 — Pre-Trade Validation** (`risk_manager.py:validate_trade()`)
Every order passes 9 independent checks before submission:
- Account status (active only)
- Risk level (halted = no trades)
- Daily loss limit ($500/account, self-imposed)
- Drawdown remaining vs. critical threshold (70%)
- Open position count (max 2 per account)
- Contract limits (Apex limits AND self-imposed 4-contract cap)
- Single trade risk ($150 max per trade)
- Portfolio position limit (10 simultaneous across all accounts)
- Correlated exposure (max 3 accounts in same instrument)

**Layer 2 — Position Sizing** (`risk_manager.py:calculate_position_size()`)
Dynamic sizing based on:
- Base size: 1 ES/NQ, 2 MES/MNQ
- Risk level multiplier: NORMAL=1.0, REDUCED=0.5, MINIMAL=0.25
- Profit buffer: Scale up only after $1,500+ profit cushion
- Confidence weighting from signal quality
- Hard cap at Apex contract limits

**Layer 3 — Account Circuit Breakers** (`risk_manager.py:update_account_risk()`)
Three drawdown thresholds trigger escalating responses:
- 30% of max DD used → REDUCED risk level (half size)
- 50% of max DD used → MINIMAL risk level (quarter size, high-confidence only)
- 70% of max DD used → HALTED + emergency flatten
- Daily loss ≥ $500 → account paused until next day

**Layer 4 — Portfolio Aggregation** (`risk_manager.py:update_portfolio_state()`)
Cross-account protection:
- Total portfolio daily loss limit: $5,000
- Max 10 simultaneous positions across all accounts
- Correlated instrument exposure limit

### Key Risk Parameters ($50K EVAL)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max daily loss | $500 | 20% of $2,500 DD limit |
| Max single trade risk | $150 | 3 consecutive losers = $450 < daily limit |
| Max open positions | 2/account | Limits concentration risk |
| ES stop loss | 4 points ($200) | Covers normal noise |
| ES target | 6 points ($300) | 1.5:1 reward-to-risk |
| Drawdown critical | 70% | Leaves $750 buffer |

## 2. Strategy Selection & Logic

### Strategy 1: VWAP Mean Reversion
- **Edge**: Price reverts to VWAP in range-bound sessions (60-70% of days)
- **Entry**: Price > 1.5 ATR from VWAP + reversal candle pattern
- **Exit**: Price reaches VWAP (target) or stop hit
- **Filter**: ADX < 30 (skip trends), volume > 0.8x average
- **Best for**: Regular hours (8:30-3:00 CT), choppy markets
- **Win rate target**: 60-70%

### Strategy 2: Opening Range Breakout (ORB)
- **Edge**: Institutional order flow at RTH open creates momentum
- **Entry**: Price breaks above/below first 15-min range with volume surge
- **Exit**: Trailing stop (1.5 ATR) or time-based (before 2:45 PM CT)
- **Filter**: Range width 0.5-3.0 ATR, volume ratio ≥ 1.3x
- **Best for**: Trend days, news catalysts
- **Win rate target**: 45-55% (larger wins compensate)

### Strategy 3: Momentum Scalp
- **Edge**: Short-term momentum persistence confirmed by multiple indicators
- **Entry**: 8/21 EMA crossover + RSI direction + volume spike
- **Exit**: Reverse EMA cross, RSI extreme, or quick target (1.5 ATR)
- **Filter**: ADX > 20 (needs trend), volume > 1.2x average
- **Best for**: Trending sessions with high volume
- **Win rate target**: 50-60%

### Strategy Distribution Across Account Groups

| Group | Accounts | Strategies |
|-------|----------|------------|
| Group 0 | APEX_01-05 | VWAP Reversion + Momentum Scalp |
| Group 1 | APEX_06-10 | ORB + VWAP Reversion |
| Group 2 | APEX_11-15 | Momentum Scalp + ORB |
| Group 3 | APEX_16-20 | All three (diversified) |

Groups rotate every 10 signals. Only the active group trades any given signal.

## 3. Apex Compliance Framework

### EVAL Rules ($50K Tradovate)

| Rule | Value | System Enforcement |
|------|-------|--------------------|
| Profit target | $3,000 | Auto-detect pass condition |
| Trailing threshold | $2,500 (EOD) | Multi-layer circuit breakers |
| Max contracts ES/NQ | 10 | Hard cap + 4-contract self-limit |
| Max contracts MES/MNQ | 50 | Hard cap |
| Min trading days | 7 | Tracked per account |
| Close window | 4:59-6:00 PM CT | Auto-flatten at 4:57 PM |
| Weekend positions | Not allowed | Auto-flatten Friday 4:55 PM |

### Compliance Monitoring Cycle (every 30 seconds)
1. Check trading window (reject orders during close)
2. Check flatten deadline (force flatten 2 min before close)
3. Check EVAL pass condition (profit + days)
4. Verify drawdown threshold (defensive recalculation)
5. Check weekend status (flatten if positions found)

### Edge Cases Handled
- **Near-limit drawdown**: Trading halted at 70% DD usage ($1,750 used of $2,500)
- **Weekend positions**: Auto-flatten on Friday before close window
- **Session break**: No new orders during 4:59-6:00 PM CT
- **EVAL already passed**: Block new trades, transition to PERFORMANCE

## 4. Copy Trading via TradingView Webhooks

### Detection Avoidance Architecture

The copy engine uses 7 techniques to make 20 accounts appear independent:

1. **Timing Jitter**: Gaussian-distributed delays of 0.5-5.0 seconds between account executions. Most cluster around 2.75s mean, creating natural variation.

2. **Position Size Variance**: ±20% size variation. A 2-contract signal might execute as 1, 2, or 3 contracts across different accounts.

3. **Skip Probability**: 10% chance any account skips a given signal entirely. Over time, each account has a different trade history.

4. **Account Grouping**: Only 5 accounts (1 group) trade any given signal. Groups rotate every 10 signals. At any point, 15 accounts are idle.

5. **Strategy Rotation**: Different groups trade different strategy combinations. Group 0 never trades ORB; Group 2 never trades VWAP reversion alone.

6. **Price Variance**: Limit order prices vary by ±2 ticks ($0.50 for ES). Stops and targets also vary by ±1 tick.

7. **Randomized Order**: Account execution order is shuffled each signal.

### Webhook Signal Flow

```
TradingView (Pine Script alert fires)
    │
    ▼ HTTPS POST (JSON payload)
    │
    │  {
    │    "token": "secret",
    │    "strategy": "vwap_reversion",
    │    "action": "long_entry",
    │    "instrument": "ES",
    │    "price": 5012.50,
    │    "stop_loss": 5008.50,
    │    "take_profit": 5018.50,
    │    "confidence": 0.72,
    │    "timestamp": "2025-01-15T14:30:00Z"
    │  }
    │
    ▼
Webhook Server
    │ 1. Validate token
    │ 2. Check signal age (< 30s)
    │ 3. Rate limit (60/min)
    │ 4. Parse to TradingSignal
    │
    ▼
Copy Trading Engine
    │ 1. Select active group (5 accounts)
    │ 2. Filter eligible (status, strategy match)
    │ 3. Shuffle execution order
    │ 4. For each account:
    │    a. Random skip check (10%)
    │    b. Apply variance (size, price, stop)
    │    c. Risk validation
    │    d. Compliance check
    │    e. Staggered delay (gaussian jitter)
    │    f. Submit to Tradovate
    │
    ▼
Tradovate API (individual account orders)
```

### TradingView Setup (per strategy)

1. Add Pine Script strategy to chart (ES 5-min or NQ 5-min)
2. Create alert: Condition = strategy order filled
3. Webhook URL: `https://your-server:8443/webhook`
4. Alert message: Strategy auto-generates JSON payload
5. Set `webhookToken` input to match server's `WEBHOOK_SECRET_TOKEN`

## 5. Technical Architecture

### Project Structure
```
TradingBots/
├── main.py                           # Entry point
├── config/
│   ├── settings.py                   # All configuration (env-driven)
│   └── accounts.example.json         # Account config template
├── src/
│   ├── core/
│   │   ├── models.py                 # Data models (signals, orders, state)
│   │   ├── events.py                 # Async event bus (pub/sub)
│   │   └── orchestrator.py           # Main system coordinator
│   ├── strategies/
│   │   ├── base_strategy.py          # Strategy interface
│   │   ├── vwap_reversion.py         # Strategy 1
│   │   ├── opening_range_breakout.py # Strategy 2
│   │   └── momentum_scalp.py         # Strategy 3
│   ├── risk/
│   │   └── risk_manager.py           # 4-layer risk engine
│   ├── compliance/
│   │   └── apex_compliance.py        # Apex rule enforcement
│   ├── webhooks/
│   │   └── webhook_server.py         # FastAPI webhook receiver
│   ├── copy_trading/
│   │   └── copy_engine.py            # Multi-account distribution
│   ├── accounts/
│   │   ├── tradovate_client.py       # Tradovate API client
│   │   └── account_manager.py        # 20-account lifecycle
│   ├── market_intel/
│   │   └── news_filter.py            # Economic calendar + volatility
│   └── monitoring/
│       └── performance_monitor.py    # Analytics + reporting
├── pinescript/
│   ├── vwap_reversion_strategy.pine
│   ├── opening_range_breakout_strategy.pine
│   └── momentum_scalp_strategy.pine
└── tests/
    ├── test_risk_manager.py
    └── test_compliance.py
```

### Technology Stack
- **Language**: Python 3.11+ (async/await throughout)
- **Web Framework**: FastAPI + Uvicorn (webhook server)
- **HTTP Client**: httpx (async Tradovate API calls)
- **Charting**: TradingView Pine Script v5 (signal generation)
- **Logging**: structlog (structured, context-rich)
- **Config**: pydantic-settings (env-driven, type-safe)
- **Events**: Custom async pub/sub event bus

### Reliability & Failsafes
- All API calls wrapped in retry logic with exponential backoff
- Webhook server validates signal age (rejects stale signals > 30s)
- Rate limiting prevents webhook abuse
- Event bus catches and logs handler exceptions without crashing
- Emergency flatten endpoint (`POST /flatten-all`) for manual intervention
- Graceful shutdown flattens all positions before exit
- SIGINT/SIGTERM handlers ensure clean shutdown

## 6. Market Intelligence

### Economic Event Calendar
High-impact events trigger automatic trading suspension:

| Event | Impact | Blackout Window |
|-------|--------|-----------------|
| FOMC Rate Decision | HIGH | -15 min / +30 min |
| Non-Farm Payrolls | HIGH | -10 min / +15 min |
| CPI Release | HIGH | -10 min / +10 min |
| GDP Release | HIGH | -10 min / +10 min |
| PPI Release | MEDIUM | -5 min / +5 min |
| Jobless Claims | MEDIUM | -3 min / +3 min |
| ISM Manufacturing | MEDIUM | -5 min / +5 min |

### Volatility Monitoring
- ATR tracked over rolling 20 and 100 periods
- Multiplier = recent ATR / long-term ATR
- 1.5x → reduce position sizes
- 2.0x → volatility spike alert
- 3.0x → halt all new entries

## 7. Performance Monitoring

### Key Metrics
- **Win rate**: Target 55%+ overall
- **Profit factor**: Target 1.5+ (total wins / total losses)
- **Max consecutive losses**: Alert at 5, review at 7
- **Daily P&L per account**: Track vs. $500 daily loss limit
- **EVAL progress**: Profit toward $3,000 target + trading days

### Shutdown Conditions
The system auto-shuts down if:
- Last 20 trades: net -$2,000 AND win rate < 25%
- This indicates fundamental strategy failure, not normal variance

### Strategy Pause Conditions
Individual strategy paused if (last 30 trades for that strategy):
- Win rate drops below 30%, OR
- Net P&L below -$500 over 15+ trades

## 8. Deployment Checklist

1. Copy `.env.example` to `.env` and configure credentials
2. Copy `config/accounts.example.json` to `config/accounts.json` with real accounts
3. Deploy Pine Script strategies to TradingView charts
4. Configure TradingView alerts with webhook URL
5. Start system in dry-run mode: `python main.py`
6. Monitor logs and webhook reception
7. Verify compliance checks are working
8. Run with `--live` flag when ready for real trading
9. Monitor EVAL progress via performance reports
