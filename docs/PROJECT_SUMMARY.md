# Project Summary

## Autonomous Trading System for Apex Trader Funding

### What This Project Is

This is a complete, production-ready framework for running an autonomous trading operation across 20 Apex Trader Funding evaluation accounts ($50K each, Tradovate platform). The system generates trading signals via TradingView Pine Script strategies, distributes them across accounts through a webhook server, and manages risk, compliance, and order execution without human intervention during market hours.

The primary objective is passing all 20 EVAL accounts to PERFORMANCE status, then scaling into sustainable profit generation.

---

### The Problem It Solves

Running 20 prop firm accounts manually is operationally impossible. Each account requires:
- Real-time monitoring of position risk
- Awareness of drawdown thresholds that terminate the account if breached
- Flattening all positions before daily close windows
- Maintaining minimum trading day counts
- Adapting position size based on account health
- Avoiding detection as coordinated copy trading

A single trader cannot execute consistent strategies across 20 accounts simultaneously while maintaining compliance with all rules. This system automates the entire workflow.

---

### System Architecture (High-Level)

```
TradingView Pine Script Strategies
         |
         v  (HTTPS Webhook)
    Webhook Server (FastAPI)
         |
         v
    Copy Trading Engine ──> 20 Account Groups
         |                  (timing jitter, size variance,
         |                   skip probability, strategy rotation)
         v
    Risk Manager + Compliance Monitor
         |
         v
    Account Manager ──> 20x Tradovate API Clients
         |
         v
    Tradovate (Order Execution)
```

---

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| **Configuration** | `config/settings.py` | All system parameters in one place, env-driven |
| **Data Models** | `src/core/models.py` | Signals, orders, positions, account state |
| **Event Bus** | `src/core/events.py` | Async pub/sub communication between components |
| **Orchestrator** | `src/core/orchestrator.py` | Central coordinator — starts/stops everything |
| **Risk Manager** | `src/risk/risk_manager.py` | 4-layer defense: pre-trade checks, sizing, circuit breakers, portfolio limits |
| **Compliance** | `src/compliance/apex_compliance.py` | Apex rule enforcement: drawdown, close window, contracts, EVAL pass detection |
| **VWAP Strategy** | `src/strategies/vwap_reversion.py` | Mean reversion to VWAP for range-bound days |
| **ORB Strategy** | `src/strategies/opening_range_breakout.py` | First 15-min range breakout with volume confirmation |
| **Momentum Strategy** | `src/strategies/momentum_scalp.py` | EMA crossover with RSI/ADX/volume filters |
| **Webhook Server** | `src/webhooks/webhook_server.py` | FastAPI server receiving TradingView alerts |
| **Copy Engine** | `src/copy_trading/copy_engine.py` | Multi-account distribution with 7 detection avoidance techniques |
| **Tradovate Client** | `src/accounts/tradovate_client.py` | API client for order placement and account data |
| **Account Manager** | `src/accounts/account_manager.py` | 20-account lifecycle, routing, state sync |
| **Market Intelligence** | `src/market_intel/news_filter.py` | Economic calendar blackouts, volatility monitoring |
| **Performance Monitor** | `src/monitoring/performance_monitor.py` | Win rate, profit factor, EVAL progress, auto-shutdown |
| **Pine Script (x3)** | `pinescript/*.pine` | TradingView strategies generating webhook JSON alerts |

---

### Trading Strategies

Three strategies cover different market regimes so at least one has edge on any given day:

**1. VWAP Mean Reversion** — Trades price returning to VWAP after 1.5+ ATR deviations during range-bound sessions. Filtered by ADX < 30, volume confirmation, and reversal candle patterns. Target win rate: 60-70%. Best for: Normal volume, choppy days (60% of sessions).

**2. Opening Range Breakout** — Captures the first 15 minutes of RTH to define a range, then trades the first breakout with volume surge confirmation. One trade per day per instrument. Target win rate: 45-55%. Best for: Trend days, high-volume opens.

**3. Momentum Scalp** — 8/21 EMA crossover confirmed by RSI direction, ADX trending filter, and volume spike. Quick targets at 1.5 ATR. Max 4 trades per day. Target win rate: 50-60%. Best for: Trending sessions with elevated volume.

---

### Risk Management

The system is designed **defense-first** — protecting accounts from termination is the top priority.

**Four layers of defense:**
1. **Pre-trade validation**: 9 checks must pass before any order (daily loss, drawdown, position limits, contract caps, trade risk, portfolio exposure, correlated positions)
2. **Dynamic position sizing**: 1 base contract, scaled by risk level (halved at 30% DD, quartered at 50%, halted at 70%)
3. **Account circuit breakers**: $500/day loss limit halts the account; 70% drawdown usage triggers emergency flatten
4. **Portfolio aggregation**: $5,000 cross-account daily loss limit, max 10 simultaneous positions

**Key parameters:**
- Max per-trade risk: $150 (3 consecutive full-loss trades stay under daily limit)
- Daily loss limit: $500/account (20% of $2,500 drawdown threshold)
- Drawdown critical threshold: 70% of max DD → halt all trading
- Emergency flatten: Triggered by any critical event — no human intervention needed

---

### Copy Trading Architecture

The challenge: execute similar strategies across 20 accounts without appearing as coordinated activity.

**Seven detection avoidance techniques:**
1. **Timing jitter**: Gaussian-distributed delays (0.5-5.0 seconds) between account executions
2. **Size variance**: ±20% position size variation between accounts
3. **Skip probability**: 10% chance any account randomly skips a signal
4. **Account grouping**: 4 groups of 5 accounts; only one group trades per signal, rotating every 10 signals
5. **Strategy rotation**: Different groups assigned different strategy combinations
6. **Price variance**: Limit order prices vary by ±2 ticks; stop/target distances vary by ±1 tick
7. **Randomized execution order**: Account order shuffled for each signal

The result: each account's trade history looks different — different entry times, sizes, prices, and even which trades they took.

---

### Apex Compliance

The system enforces all Apex Trader Funding rules as hard constraints:

| Rule | Enforcement |
|------|-------------|
| Trailing drawdown ($2,500) | Multi-layer circuit breakers halt trading well before threshold |
| Contract limits (10 ES/NQ) | Hard cap + conservative 4-contract self-limit |
| Close window (4:59-6:00 PM CT) | Auto-flatten at 4:57 PM, reject orders during window |
| Minimum 7 trading days | Tracked per account; EVAL pass requires both profit AND days |
| No weekend positions | Friday flatten before close; Saturday/Sunday monitoring |

---

### Technology Stack

- **Python 3.11+** with async/await throughout
- **FastAPI + Uvicorn** for the webhook server
- **httpx** for async Tradovate API calls
- **TradingView Pine Script v5** for signal generation
- **structlog** for structured logging
- **pydantic-settings** for type-safe configuration
- **pytest** for testing

---

### File Count & Size

```
Total files:      42
Python modules:   20
Pine Script:       3
Configuration:     4
Tests:             3
Documentation:     5
Lines of code:  ~7,000+
```

---

### How to Run

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # Edit with your credentials
cp config/accounts.example.json config/accounts.json  # Add 20 accounts

# 3. Deploy Pine Scripts to TradingView and configure webhook alerts

# 4. Dry run (no real orders)
python main.py

# 5. Live trading
python main.py --live --accounts config/accounts.json
```

---

### Project Milestones

| Phase | Goal | Status |
|-------|------|--------|
| 1. Framework Build | Complete system architecture and all components | Done |
| 2. Dry Run Testing | Verify webhook chain, risk checks, compliance | Ready to test |
| 3. Paper Trading | Run with Tradovate demo accounts for 1-2 weeks | Next step |
| 4. EVAL Phase | Deploy to 20 live EVAL accounts | After paper trading |
| 5. PERFORMANCE Phase | Transition passed accounts to profit generation | After EVAL pass |
| 6. Optimization | Tune strategies based on live performance data | Ongoing |

---

### Key Design Decisions

| Decision | Choice Made | Rationale |
|----------|------------|-----------|
| Defense over profit | $500 daily limit (aggressive safety) | One bad day shouldn't kill an account |
| 3 strategies | VWAP + ORB + Momentum | Covers range-bound, trending, and momentum regimes |
| Group-based copy trading | 4 groups of 5 accounts | Balances diversification with detection avoidance |
| Pine Script for signals | TradingView-native | Leverages TradingView's data/charting; webhook integration built-in |
| Async Python | asyncio + FastAPI | 20 concurrent account operations require non-blocking I/O |
| Event-driven architecture | Pub/sub event bus | Decouples components; risk manager doesn't need to know about webhooks |

---

### Documentation

| Document | Location | Content |
|----------|----------|---------|
| Architecture Blueprint | `ARCHITECTURE.md` | System diagram, all component details, deployment checklist |
| Setup Guide | `docs/SETUP_GUIDE.md` | 14-section step-by-step from server setup to live trading |
| Strategy Guide | `docs/STRATEGY_GUIDE.md` | 15-section research reference for all strategies, backtesting, optimization |
| Project Summary | `docs/PROJECT_SUMMARY.md` | This document — high-level overview |
| Environment Config | `.env.example` | All configurable parameters with descriptions |
| Account Template | `config/accounts.example.json` | 20-account configuration template |
