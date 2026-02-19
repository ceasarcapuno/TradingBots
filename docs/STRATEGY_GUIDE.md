# Research Strategy Guide

A complete reference for the three trading strategies, their theoretical foundations, parameter tuning, market condition filters, backtesting methodology, and ongoing optimization within the Apex Trader Funding prop firm framework.

---

## Table of Contents

1. [Strategy Design Philosophy](#1-strategy-design-philosophy)
2. [Strategy 1: VWAP Mean Reversion](#2-strategy-1-vwap-mean-reversion)
3. [Strategy 2: Opening Range Breakout](#3-strategy-2-opening-range-breakout)
4. [Strategy 3: Momentum Scalp](#4-strategy-3-momentum-scalp)
5. [Strategy Interplay & Portfolio Construction](#5-strategy-interplay--portfolio-construction)
6. [Market Condition Classification](#6-market-condition-classification)
7. [Risk Parameters Deep Dive](#7-risk-parameters-deep-dive)
8. [Backtesting Methodology](#8-backtesting-methodology)
9. [Walk-Forward Optimization](#9-walk-forward-optimization)
10. [Economic Event Impact Analysis](#10-economic-event-impact-analysis)
11. [Instrument-Specific Characteristics](#11-instrument-specific-characteristics)
12. [Performance Benchmarks & Targets](#12-performance-benchmarks--targets)
13. [Strategy Degradation & Adaptation](#13-strategy-degradation--adaptation)
14. [Alternative Strategies to Explore](#14-alternative-strategies-to-explore)
15. [Research Resources & Data Sources](#15-research-resources--data-sources)

---

## 1. Strategy Design Philosophy

### Why These Three Strategies

The strategy portfolio is designed around three principles specific to prop firm trading:

**Principle 1: Regime Diversification**
Markets alternate between trending and mean-reverting regimes. No single strategy works in all conditions. By running three strategies that thrive in different regimes, the portfolio maintains edge across market states:

| Market Regime | Best Strategy | Worst Strategy |
|---------------|--------------|----------------|
| Range-bound / Choppy | VWAP Reversion | Momentum Scalp |
| Trending / Directional | Momentum Scalp, ORB | VWAP Reversion |
| Volatile / News-driven | ORB (if range forms before news) | All (news blackout) |
| Low volatility / Quiet | VWAP Reversion (tight range) | ORB (range too narrow) |

**Principle 2: Prop Firm Optimization**
Strategies are optimized for the specific constraints of Apex EVAL accounts:
- **Consistent small wins** > occasional large wins (avoid drawdown spikes)
- **Limited daily exposure** (1-4 trades/day keeps risk controlled)
- **Accumulate trading days** (need 7 minimum — VWAP generates frequent signals)
- **Asymmetric risk-reward** (cap losses at $150/trade, targets at $225+)

**Principle 3: Automation Suitability**
Each strategy uses:
- Rule-based entries with zero discretion
- Objective indicator conditions (no pattern subjectivity)
- Defined stop loss and take profit at entry time
- Time-based exits as a backstop
- Volume confirmation to avoid false signals

### Key Distinction: Prop Firm vs. Retail Trading

| Aspect | Retail Approach | Prop Firm Approach (This System) |
|--------|----------------|----------------------------------|
| Goal | Maximize returns | Pass EVAL first, then sustainable profit |
| Risk tolerance | Varies | Zero tolerance for rule violation |
| Position sizing | % of account | Fixed small size, scale up only with buffer |
| Daily loss | Soft limit | Hard circuit breaker ($500) |
| Trade frequency | Unlimited | Self-limited (1-4/day per strategy) |
| Drawdown response | "Hold and hope" | Automated size reduction → halt |

---

## 2. Strategy 1: VWAP Mean Reversion

### Theoretical Foundation

**Volume-Weighted Average Price (VWAP)** represents the fair value price at which institutions have transacted throughout the day. When price deviates significantly from VWAP, it creates a statistical edge for reversion:

- **Institutional anchoring**: Large funds use VWAP as execution benchmarks. When price moves far from VWAP, these funds often step in to buy below or sell above, pulling price back.
- **Statistical mean reversion**: In non-trending conditions (60-70% of trading sessions), price oscillates around VWAP with predictable standard deviations.
- **Self-fulfilling prophecy**: Enough traders watch VWAP that it acts as a magnet.

### Entry Conditions (All Must Be True)

```
1. |Price - VWAP| > 1.5 * ATR(14)           # Significant deviation
2. ADX(14) < 30                               # Not a strong trend day
3. Volume > 0.8 * SMA(Volume, 20)            # Sufficient liquidity
4. Reversal candle pattern present             # Price showing rejection
5. Within RTH session (8:30 AM - 3:00 PM CT)  # Best liquidity
```

**Long Entry**: Price below VWAP by 1.5+ ATR AND bullish reversal candle
**Short Entry**: Price above VWAP by 1.5+ ATR AND bearish reversal candle

### Reversal Candle Definition

**Bullish Reversal (Hammer)**:
```
- Lower wick > 40% of total candle range
- Body < 40% of total candle range
- Close >= Open (green/bullish candle)
```

**Bearish Reversal (Shooting Star)**:
```
- Upper wick > 40% of total candle range
- Body < 40% of total candle range
- Close <= Open (red/bearish candle)
```

### Exit Conditions

| Exit Type | Condition | Priority |
|-----------|-----------|----------|
| Target | Price reaches VWAP | Primary |
| Stop loss | Below entry - min(2.0 * ATR, swing low) | Protective |
| Deviation exit | Price moves 2x further from VWAP (3.0 ATR deviation) | Cut losses |
| Time exit | 3:00 PM CT (end of preferred session) | Backstop |
| Compliance | Close window approaching (4:57 PM CT) | Mandatory |

### Parameter Sensitivity Analysis

| Parameter | Conservative | Default | Aggressive | Impact |
|-----------|-------------|---------|------------|--------|
| ATR Deviation Threshold | 2.0 | 1.5 | 1.0 | Higher = fewer trades, higher quality |
| ADX Max | 25 | 30 | 35 | Higher = allows weaker trends, more trades |
| Volume Min Ratio | 1.0 | 0.8 | 0.6 | Higher = stricter volume filter |
| Max Stop ATR | 1.5 | 2.0 | 2.5 | Higher = wider stops, fewer stop-outs |
| Reversal Wick Ratio | 0.5 | 0.4 | 0.3 | Higher = stricter candle pattern |

**Recommended tuning order**: ATR Deviation (most impact) → ADX Max → Volume Ratio

### Expected Performance Profile

| Metric | Target Range |
|--------|-------------|
| Win rate | 58-68% |
| Avg winner | $200-350 |
| Avg loser | $125-175 |
| Profit factor | 1.6-2.2 |
| Trades per day | 0-3 |
| Max consecutive losses | 3-5 |
| Best market condition | Low ADX, normal volume, regular hours |

### When This Strategy Fails

- **Trend days**: Price moves away from VWAP all day. The ADX filter should catch this, but some trend days develop slowly.
- **Gap days**: Large overnight gaps create an artificial VWAP level. First 30 minutes of VWAP data on gap days is unreliable.
- **Pre-market news**: VWAP calculated from overnight session may not be meaningful if a major event occurs pre-RTH.

**Mitigation**: The ADX < 30 filter eliminates most trend days. For gap days, consider increasing the ATR deviation threshold to 2.0 on days with > 1% gap.

---

## 3. Strategy 2: Opening Range Breakout

### Theoretical Foundation

The **Opening Range Breakout (ORB)** is one of the oldest institutional trading strategies. The first 15-30 minutes of regular trading hours concentrate the majority of institutional order flow as overnight orders, portfolio rebalances, and reactive trades all compress into a narrow window.

**Why it works**:
- **Institutional order flow**: Mutual funds, pension funds, and ETF rebalances execute at RTH open. This creates the day's directional bias.
- **Range as support/resistance**: The opening range high/low become the day's first reference points. Breakout through these levels often triggers stop orders and trend-following entries from other participants.
- **Volume confirmation**: True breakouts are accompanied by volume surges. False breakouts occur on declining volume.

### The Opening Range

```
Opening Range Period: 8:30 AM - 8:45 AM CT (first 15 minutes of RTH)
Range High: Highest price during this period
Range Low: Lowest price during this period
Range Width: Range High - Range Low
```

### Entry Conditions (All Must Be True)

```
1. Opening range is established (after 8:45 AM CT)
2. Range width is between 0.5 ATR and 3.0 ATR      # Not too tight, not too wide
3. Price breaks above Range High + 0.50 points       # Breakout with buffer
   OR breaks below Range Low - 0.50 points
4. Volume on breakout bar > 1.3 * SMA(Volume, 20)   # Volume confirmation
5. Time is before 11:00 AM CT                         # Early-session only
6. No trade taken yet today for this instrument       # One shot per day
```

**Long Breakout**: Close > Range High + buffer, with volume surge
**Short Breakout**: Close < Range Low - buffer, with volume surge

### Exit Conditions

| Exit Type | Condition | Priority |
|-----------|-----------|----------|
| Target | Entry + min(2 * Range Width, 4 * ATR) | Primary |
| Stop loss | Opposite range boundary (long stop = Range Low, short stop = Range High) | Protective |
| Trailing stop | 1.5 * ATR trailing from highest/lowest since entry | Locks in profit |
| Time exit | 2:45 PM CT | Backstop |
| Compliance | Close window approaching (4:57 PM CT) | Mandatory |

### Parameter Sensitivity Analysis

| Parameter | Conservative | Default | Aggressive | Impact |
|-----------|-------------|---------|------------|--------|
| Range Period (min) | 30 | 15 | 5 | Longer = more defined range, fewer trades |
| Min Range ATR | 0.7 | 0.5 | 0.3 | Higher = skips narrow, low-potential ranges |
| Max Range ATR | 2.5 | 3.0 | 4.0 | Higher = allows wider ranges (more risk) |
| Breakout Buffer | 1.00 | 0.50 | 0.25 | Higher = fewer false breakouts, later entry |
| Volume Surge Ratio | 1.5 | 1.3 | 1.1 | Higher = stricter volume confirmation |
| Trailing Stop ATR | 2.0 | 1.5 | 1.0 | Tighter = locks in profit faster, exits sooner |
| Last Entry Time | 10:00 AM | 11:00 AM | 12:00 PM | Later = allows more time but lower quality |

**Recommended tuning order**: Volume Surge Ratio (most important filter) → Breakout Buffer → Range Period

### Expected Performance Profile

| Metric | Target Range |
|--------|-------------|
| Win rate | 42-55% |
| Avg winner | $350-600 |
| Avg loser | $200-350 |
| Profit factor | 1.4-1.9 |
| Trades per day | 0-1 (max 1 per instrument) |
| Max consecutive losses | 4-7 |
| Best market condition | Trend days, high volume opens, catalysts |

### When This Strategy Fails

- **Narrow range days**: Range width < 0.5 ATR means low directional conviction. The filter catches this.
- **Chop-and-reverse**: Price breaks out, reverses, breaks out the other way. This is the hardest scenario — the volume filter helps but doesn't eliminate it.
- **Wide range days**: Range > 3.0 ATR means the stop (opposite boundary) is too far. Risk-reward becomes unfavorable.
- **Late-session breakouts**: Breakouts after 11 AM are less reliable. The time filter prevents these.

**Mitigation**: The "one trade per day" rule prevents chasing false breakouts. If the first breakout fails and stops out, the strategy does not re-enter.

### ORB Variants to Explore

| Variant | Modification | Trade-off |
|---------|-------------|-----------|
| 5-minute ORB | First 5 min range | More signals, more false breakouts |
| 30-minute ORB | First 30 min range | Fewer signals, more reliable |
| ORB with gap filter | Skip if gap > 1% | Avoids volatile gap days |
| ORB with prior day range | Combine OR with prior day high/low | Multi-timeframe confirmation |
| ORB pullback | Wait for breakout then pullback to range | Better entries, might miss runners |

---

## 4. Strategy 3: Momentum Scalp

### Theoretical Foundation

**Short-term momentum persistence** is a well-documented market microstructure effect. When a price move is confirmed by multiple momentum indicators simultaneously, the probability of continuation over the next 5-30 minutes is elevated.

**Why it works**:
- **Order flow clustering**: Momentum attracts trend-followers, creating a self-reinforcing cycle over short timeframes.
- **EMA crossover**: The 8/21 EMA crossover captures the transition from consolidation to directional movement. The fast EMA responds to recent price action; when it crosses the slow EMA, the short-term trend has shifted.
- **Multi-indicator confirmation**: Requiring RSI, ADX, AND volume to align simultaneously creates a high-quality signal filter. Each indicator measures a different dimension of momentum.

### Indicator Definitions

```
Fast EMA: EMA(Close, 8)       — Responsive to recent price changes
Slow EMA: EMA(Close, 21)      — Represents intermediate trend direction
RSI:      RSI(Close, 14)      — Momentum oscillator (0-100)
ADX:      ADX(14)             — Trend strength (0-100), direction-agnostic
Volume:   Volume / SMA(Volume, 20) — Relative volume ratio
```

### Entry Conditions (All Must Be True)

**Long Entry**:
```
1. Fast EMA crosses ABOVE Slow EMA (bullish crossover on current bar)
2. RSI(14) > 55                           # Momentum confirms upward
3. ADX(14) > 20                           # Sufficient trend strength
4. Volume > 1.2 * SMA(Volume, 20)         # Volume surge
5. |Close - Open| / Close > 0.001         # Minimum bar momentum (0.1%)
6. Trades today < 4                        # Overtrading limit
7. Within RTH (8:30 AM - 3:00 PM CT)
```

**Short Entry**:
```
1. Fast EMA crosses BELOW Slow EMA (bearish crossover on current bar)
2. RSI(14) < 45                           # Momentum confirms downward
3. ADX(14) > 20                           # Sufficient trend strength
4. Volume > 1.2 * SMA(Volume, 20)         # Volume surge
5. |Close - Open| / Close > 0.001         # Minimum bar momentum
6. Trades today < 4
7. Within RTH
```

### Exit Conditions

| Exit Type | Condition | Priority |
|-----------|-----------|----------|
| Target | Entry + 1.5 * ATR (long) or Entry - 1.5 * ATR (short) | Primary |
| Stop loss | Entry - 1.0 * ATR (long) or Entry + 1.0 * ATR (short) | Protective |
| Reverse cross | Fast EMA crosses back below/above Slow EMA | Momentum lost |
| RSI extreme | RSI > 75 (close longs) or RSI < 25 (close shorts) | Overbought/oversold |
| Time exit | 3:00 PM CT | Backstop |
| Compliance | Close window approaching (4:57 PM CT) | Mandatory |

### Confidence Scoring

Each signal receives a confidence score (0.0 to 0.9) based on multiple factors:

```python
confidence = 0.50                              # Base

# ADX contribution
if ADX > 30: confidence += 0.10                # Moderate trend
if ADX > 40: confidence += 0.05                # Strong trend

# RSI contribution (for longs: higher = better; for shorts: lower = better)
if direction == "long" and RSI > 60: confidence += 0.10
if direction == "short" and RSI < 40: confidence += 0.10

# Volume contribution
if volume_ratio > 1.5: confidence += 0.10      # Strong volume
if volume_ratio > 2.0: confidence += 0.05      # Very strong volume

# Cap at 0.90
confidence = min(confidence, 0.90)
```

This confidence score feeds into position sizing: higher confidence = larger position (up to limits).

### Parameter Sensitivity Analysis

| Parameter | Conservative | Default | Aggressive | Impact |
|-----------|-------------|---------|------------|--------|
| Fast EMA | 10 | 8 | 5 | Shorter = more responsive, more noise |
| Slow EMA | 25 | 21 | 15 | Shorter = more crosses, lower quality |
| RSI Long Threshold | 60 | 55 | 50 | Higher = stricter momentum filter |
| RSI Short Threshold | 40 | 45 | 50 | Lower = stricter momentum filter |
| ADX Min | 25 | 20 | 15 | Higher = only trades strong trends |
| Volume Min Ratio | 1.5 | 1.2 | 1.0 | Higher = fewer but higher quality signals |
| Target ATR Mult | 2.0 | 1.5 | 1.0 | Higher = bigger targets, lower hit rate |
| Stop ATR Mult | 0.75 | 1.0 | 1.5 | Tighter = more stop-outs but smaller losses |
| Max Trades/Day | 3 | 4 | 6 | Higher = more exposure but overtrading risk |

**Recommended tuning order**: Volume Min Ratio → ADX Min → EMA periods

### Expected Performance Profile

| Metric | Target Range |
|--------|-------------|
| Win rate | 48-58% |
| Avg winner | $200-350 |
| Avg loser | $150-225 |
| Profit factor | 1.3-1.7 |
| Trades per day | 0-4 |
| Max consecutive losses | 4-6 |
| Best market condition | Trending sessions, high ADX, elevated volume |

### When This Strategy Fails

- **Choppy/range-bound days**: EMA crossovers fire repeatedly in both directions. The ADX filter (> 20) prevents most false signals, but transitional periods are tricky.
- **News whipsaws**: Sudden reversals after initial momentum. The news blackout window addresses scheduled events, but unscheduled news (geopolitical, breaking) cannot be filtered.
- **Low volume sessions**: Holidays, summer Fridays. Volume filter catches these.

---

## 5. Strategy Interplay & Portfolio Construction

### How the Three Strategies Complement Each Other

```
Session Type Distribution (approximate):

  Range-bound days:  55-65% of sessions
  → VWAP Reversion excels, Momentum Scalp quiet, ORB mixed

  Trend days:        20-30% of sessions
  → ORB excels, Momentum Scalp excels, VWAP Reversion quiet

  High volatility:   10-15% of sessions
  → All strategies cautious (news blackout, volatility filter)
```

### Correlation Between Strategies

| Pair | Expected Correlation | Implication |
|------|---------------------|-------------|
| VWAP + ORB | Low (-0.1 to 0.2) | Rarely active same day (different regimes) |
| VWAP + Momentum | Low (-0.2 to 0.1) | Opposite conditions (range vs trend) |
| ORB + Momentum | Moderate (0.2 to 0.4) | Both work on trend days (but different timing) |

Low cross-strategy correlation means the portfolio's equity curve is smoother than any single strategy. This is critical for prop firm trading where drawdown must be minimized.

### Account Group Strategy Assignments

The copy trading engine distributes strategies to create natural variation:

```
Group 0 (Accounts 1-5):   VWAP Reversion + Momentum Scalp
Group 1 (Accounts 6-10):  Opening Range Breakout + VWAP Reversion
Group 2 (Accounts 11-15): Momentum Scalp + Opening Range Breakout
Group 3 (Accounts 16-20): All three strategies (diversified)
```

**Why this distribution**:
- No two groups have identical strategy sets
- Each group has at least one mean-reversion and/or one momentum strategy
- Group 3 (all three) acts as the benchmark — diversified across all regimes
- If one strategy degrades, only 2 of 4 groups are affected

### Daily Strategy Selection Logic

The system doesn't choose strategies — all assigned strategies run simultaneously and generate signals independently. The market itself selects which strategy fires:

1. Choppy morning → VWAP signals fire → ORB range too narrow (filtered out) → Momentum EMA whipsaws (filtered by ADX)
2. Strong trend open → ORB breakout fires → Momentum crossover confirms → VWAP deviation grows (no reversion yet)
3. Mixed day → VWAP fires early, Momentum fires mid-day, ORB doesn't trigger

---

## 6. Market Condition Classification

### Regime Detection

The system implicitly classifies market conditions through indicator filters:

| Indicator | Range-Bound Signal | Trending Signal |
|-----------|-------------------|-----------------|
| ADX(14) | < 20 (no trend) | > 25 (trending) |
| ATR(14) / ATR(50) | < 1.0 (contracting) | > 1.3 (expanding) |
| Volume / Avg Volume | < 0.8 (quiet) | > 1.3 (active) |
| Price vs VWAP | Oscillating around | Trending away from |
| EMA(8) vs EMA(21) | Tangled/crossing frequently | Diverging/separated |

### Volatility Regimes and Strategy Adjustment

| VIX Equivalent | ATR Multiplier | System Response |
|---------------|----------------|-----------------|
| Low (< 15) | < 0.8x | Normal sizing, prefer VWAP reversion |
| Normal (15-22) | 0.8-1.2x | All strategies active at full parameters |
| Elevated (22-30) | 1.2-1.5x | Reduce size by 30%, widen stops slightly |
| High (30+) | > 1.5x | Reduce size by 50%, halve trade count |
| Extreme (> 40) | > 2.0x | Halt new entries, only manage existing positions |

### Session Timing Characteristics

| Time Window (CT) | Characteristics | Best Strategy | Notes |
|-------------------|----------------|---------------|-------|
| 6:00 PM - 8:30 AM | Overnight/pre-market | None (avoid) | Low liquidity, wide spreads |
| 8:30 - 9:00 AM | RTH open | ORB | Highest volume, range forms |
| 9:00 - 11:00 AM | Morning session | ORB breakout, Momentum | Trending moves develop |
| 11:00 AM - 1:00 PM | Midday lull | VWAP Reversion | Volume drops, range-bound |
| 1:00 - 3:00 PM | Afternoon session | Momentum, VWAP | Volume picks up, trend or revert |
| 3:00 - 4:00 PM | Power hour | Caution (flattening time) | Institutional closing activity |
| 4:00 - 4:59 PM | Post-RTH | None (flatten by 4:57) | Mandatory flat before 4:59 |

---

## 7. Risk Parameters Deep Dive

### Position Sizing Model

The system uses a **fixed-fractional with dynamic adjustment** approach:

```
Base Size = 1 contract (ES/NQ)

Adjusted Size = Base * Risk_Multiplier * Confidence_Factor * Buffer_Scaling

Where:
  Risk_Multiplier:
    NORMAL  = 1.00 (0-30% drawdown used)
    REDUCED = 0.50 (30-50% drawdown used)
    MINIMAL = 0.25 (50-70% drawdown used)
    HALTED  = 0.00 (70%+ drawdown used)

  Confidence_Factor:
    Range: 0.50 to 1.00
    Derived from signal quality (see Strategy confidence scoring)

  Buffer_Scaling:
    If profit > $1,500: multiply by up to 2.0x
    If profit < $0: stay at 1.0x (no scaling down below base)

Final Size = max(1, round(Adjusted Size))
Hard Cap = min(Final Size, 4)  # Never exceed 4 contracts
```

### Stop Loss Placement Philosophy

Every trade has a stop loss placed at entry time. The stop is:

1. **Based on market structure** (swing high/low when visible)
2. **Capped by ATR** (max 2.0 ATR distance to control dollar risk)
3. **Validated against dollar risk limit** ($150 max per trade)

```
Dollar Risk = Stop Distance (points) * Point Value * Contracts

For ES: $150 max → Stop Distance < 150 / 50 / 1 = 3.0 points (12 ticks)
For NQ: $150 max → Stop Distance < 150 / 20 / 1 = 7.5 points (30 ticks)
For MES: $150 max → Stop Distance < 150 / 5 / 2 = 15.0 points (60 ticks)
```

### Daily Loss Budgeting

```
Account DD limit:    $2,500 (Apex rule)
Daily loss limit:    $500   (self-imposed = 20% of DD limit)
Per-trade risk:      $150   (max = 30% of daily limit)

Worst case scenario:
  3 consecutive full-loss trades = 3 x $150 = $450 < $500 daily limit
  4th trade would be blocked by daily limit circuit breaker

This means even the worst single day cannot consume more than 20% of
the total drawdown allowance, leaving 80% as a buffer.
```

### Drawdown Recovery Mathematics

```
If drawdown reaches 50% ($1,250 used of $2,500):
  - Risk level: MINIMAL (0.25x size)
  - Max daily loss now: ~$125 (due to smaller positions)
  - Days to recover $1,250 at $200/day avg: ~6 days
  - Days to recover $1,250 at $100/day avg: ~13 days

Key insight: Reducing size during drawdown EXTENDS the time to recover
but PREVENTS the catastrophic scenario where a drawdown spirals to
account termination. Slower recovery is always preferable to account death.
```

---

## 8. Backtesting Methodology

### Data Requirements

| Data Type | Source | Period | Purpose |
|-----------|--------|--------|---------|
| ES 5-min OHLCV | TradingView / CME | 2 years minimum | Strategy backtest |
| NQ 5-min OHLCV | TradingView / CME | 2 years minimum | Strategy backtest |
| Volume data | TradingView | Concurrent with OHLCV | Volume filters |
| Economic calendar | Investing.com / ForexFactory | 2 years | News filter validation |
| VIX daily | CBOE | 2 years | Volatility regime analysis |

### TradingView Strategy Tester

Each Pine Script strategy includes built-in backtesting via TradingView's Strategy Tester:

1. Add the strategy to the appropriate chart and timeframe
2. Open the **Strategy Tester** tab (bottom panel)
3. Review the **Performance Summary**:
   - Net Profit
   - Max Drawdown
   - Win Rate
   - Profit Factor
   - Total Trades
4. Click **"List of Trades"** to review individual entries/exits
5. Adjust strategy inputs and observe impact on performance

### Backtesting Pitfalls to Avoid

| Pitfall | Description | Mitigation |
|---------|-------------|------------|
| Overfitting | Optimizing parameters to fit historical data perfectly | Use walk-forward (Section 9) |
| Survivorship bias | Testing only on instruments that exist today | ES/NQ have long histories — not a major concern |
| Look-ahead bias | Using future data in current decisions | Pine Script processes bar-by-bar, mitigating this |
| Slippage underestimation | Assuming perfect fills | Set slippage to 1 tick in strategy settings |
| Commission omission | Ignoring trading costs | Set commission to $2.50/side ($5 round trip) |
| Session hours | Testing on 24-hour data when system trades RTH only | Use session filters in Pine Script |

### Minimum Acceptable Backtest Results

Before deploying any strategy to live accounts:

| Metric | Minimum Threshold | Desirable |
|--------|------------------|-----------|
| Net profit (1 year) | > $0 | > $5,000 |
| Max drawdown | < $2,000 | < $1,200 |
| Profit factor | > 1.2 | > 1.5 |
| Win rate | > 40% | > 50% |
| Total trades | > 100 | > 200 |
| Avg trade | > $10 | > $30 |
| Max consecutive losses | < 8 | < 5 |

---

## 9. Walk-Forward Optimization

### Why Walk-Forward Matters

Walk-forward optimization prevents overfitting by:
1. Optimizing parameters on a historical **in-sample** period
2. Testing those parameters on a subsequent **out-of-sample** period
3. Repeating across multiple windows

### Procedure

```
Total data: 24 months

Window 1:
  In-sample:  Months 1-12 (optimize parameters)
  Out-of-sample: Months 13-15 (test with frozen params)

Window 2:
  In-sample:  Months 4-15 (optimize)
  Out-of-sample: Months 16-18 (test)

Window 3:
  In-sample:  Months 7-18 (optimize)
  Out-of-sample: Months 19-21 (test)

Window 4:
  In-sample:  Months 10-21 (optimize)
  Out-of-sample: Months 22-24 (test)
```

### Walk-Forward Validation Criteria

The strategy passes walk-forward validation if:
- Out-of-sample profit factor > 1.0 in **at least 3 of 4 windows**
- Out-of-sample max drawdown < in-sample max drawdown in **all windows**
- Parameter values don't change dramatically between windows (stable edge)

---

## 10. Economic Event Impact Analysis

### High-Impact Events: Historical Volatility

| Event | Avg ES Move (30 min after) | Avg NQ Move | System Action |
|-------|---------------------------|-------------|---------------|
| FOMC Rate Decision | 15-40 points | 60-150 points | Flatten + 30 min blackout |
| Non-Farm Payrolls | 10-25 points | 40-100 points | Flatten + 15 min blackout |
| CPI Release | 12-30 points | 50-120 points | Flatten + 10 min blackout |
| GDP Release | 8-20 points | 30-80 points | Flatten + 10 min blackout |
| Jobless Claims | 3-8 points | 10-30 points | 3 min blackout (brief) |
| ISM Manufacturing | 5-12 points | 20-50 points | 5 min blackout |

### FOMC Schedule Awareness

FOMC meetings occur 8 times per year. The system's `MarketIntelligence` module needs specific dates loaded:

```python
# Example: Loading 2025 FOMC dates
from datetime import datetime
from src.market_intel.news_filter import MarketIntelligence, NewsImpact

intel = MarketIntelligence(config)

fomc_dates_2025 = [
    "2025-01-29 14:00", "2025-03-19 14:00", "2025-05-07 14:00",
    "2025-06-18 14:00", "2025-07-30 14:00", "2025-09-17 14:00",
    "2025-11-05 14:00", "2025-12-17 14:00",
]

for date_str in fomc_dates_2025:
    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    intel.add_custom_event("FOMC Rate Decision", dt,
                          NewsImpact.HIGH,
                          blackout_before=15, blackout_after=30)
```

---

## 11. Instrument-Specific Characteristics

### ES (E-mini S&P 500)

| Attribute | Value |
|-----------|-------|
| Exchange | CME |
| Tick size | 0.25 points |
| Tick value | $12.50 |
| Point value | $50.00 |
| Daily range (avg) | 40-60 points |
| RTH volume (avg) | 1.2-1.5M contracts |
| Margin (Apex) | Included in $50K account |
| Best strategy | VWAP Reversion (deep liquidity) |

### NQ (E-mini Nasdaq 100)

| Attribute | Value |
|-----------|-------|
| Exchange | CME |
| Tick size | 0.25 points |
| Tick value | $5.00 |
| Point value | $20.00 |
| Daily range (avg) | 150-250 points |
| RTH volume (avg) | 500K-700K contracts |
| Margin (Apex) | Included in $50K account |
| Best strategy | Momentum Scalp (higher volatility) |

### ES vs NQ: Which to Prioritize

| Factor | ES Advantage | NQ Advantage |
|--------|-------------|-------------|
| Liquidity | Higher volume, tighter spreads | — |
| Volatility | — | More movement per day |
| Mean reversion | More predictable VWAP reversion | — |
| Trend following | — | Stronger trend persistence |
| Overnight gaps | Smaller gaps | — |
| Dollar risk per tick | $12.50 (more precise sizing) | $5.00 (more granular) |

**Recommendation**: Use ES as the primary instrument for VWAP Reversion (deep liquidity, clean mean reversion). Use NQ for Momentum Scalp (bigger moves, better for scalping). Run ORB on both.

---

## 12. Performance Benchmarks & Targets

### EVAL Phase Targets (Per Account)

```
Goal: Pass EVAL ($3,000 profit in 7+ trading days)

Conservative path:
  Daily target: $150/day average
  Trading days to pass: 20 days
  Daily win requirement: 1-2 winning trades

Moderate path:
  Daily target: $250/day average
  Trading days to pass: 12 days

Aggressive path:
  Daily target: $430/day average
  Trading days to pass: 7 days (minimum)
  Higher risk — NOT recommended
```

**Recommended approach**: Conservative path. Aim for $150-200/day. Passing in 15-20 days is more reliable than rushing in 7 days.

### PERFORMANCE Phase Targets (Per Account)

```
Goal: Consistent payout-eligible profits

Monthly target: $2,000-4,000 per account
Daily target: $100-200/day average
Payout cycle: Follow Apex payout schedule

20 accounts x $2,000/month = $40,000/month portfolio target
(Assumes 15/20 accounts active at any time)
```

### Portfolio-Level Benchmarks

| Metric | Monthly Target | Quarterly Review |
|--------|---------------|-----------------|
| Accounts passed EVAL | 3-5 per month | 15+ by quarter end |
| Net portfolio profit | $30,000-60,000 | $100,000+ |
| Account termination rate | < 10% (2/20) | Replace terminated accounts |
| System uptime | > 99% | Address any downtime incidents |
| Strategy profit factor | > 1.3 per strategy | Pause strategies below 1.0 |

---

## 13. Strategy Degradation & Adaptation

### Signs a Strategy Is Degrading

| Signal | Measurement | Threshold |
|--------|------------|-----------|
| Declining win rate | Rolling 30-trade win rate | Below 35% |
| Shrinking avg win | Rolling avg of winning trades | Declining 3 weeks straight |
| Growing avg loss | Rolling avg of losing trades | Increasing 3 weeks straight |
| Profit factor collapse | Rolling 30-trade PF | Below 1.0 |
| Consecutive losses | Current streak | 7+ trades |

### Automated Response Ladder

```
Level 1 — Monitor (system detects early warning):
  → Log warning, no action
  → Trigger: Win rate < 45% over 20 trades

Level 2 — Reduce (confirmed underperformance):
  → Reduce position sizing to 50% for this strategy
  → Trigger: Win rate < 35% over 30 trades OR PF < 1.0

Level 3 — Pause (strategy failure):
  → Stop generating signals from this strategy
  → Trigger: Net P&L < -$500 over 15+ trades AND WR < 30%
  → Duration: 5 trading days minimum

Level 4 — Retire (fundamental edge lost):
  → Remove strategy from all account groups
  → Trigger: Strategy paused 3 times in 60 days
  → Action: Review strategy logic, re-backtest, modify or replace
```

### When to Replace a Strategy

Replace a strategy (not just pause) when:
- Walk-forward re-test on recent 6 months shows PF < 1.0
- Market structure has fundamentally changed (e.g., new trading hours, changed tick size)
- A clearly superior alternative has been identified and tested

---

## 14. Alternative Strategies to Explore

### Near-Term Candidates

| Strategy | Description | Pros | Cons | Difficulty |
|----------|------------|------|------|------------|
| RSI Divergence | Price makes new high/low but RSI doesn't | Strong reversal signal | Requires pattern detection | Medium |
| Volume Profile POC Reversion | Trade back to Point of Control | Institutional-level analysis | Complex data requirements | High |
| Previous Day High/Low Breakout | Break of yesterday's range | Simple, well-defined levels | Can be crowded trade | Low |
| VWAP Standard Deviation Bands | Trade from +2σ/-2σ VWAP bands | Statistical edge | Similar to current VWAP strategy | Low |
| Gap Fill Strategy | Fade overnight gaps on RTH open | High historical success rate | Requires gap detection | Medium |
| Liquidity Sweep | Trade reversals after stop hunts | Smart money concept | Subjective without automation | High |

### Crypto Futures Strategies

If adding BTC/ETH futures:

| Consideration | BTC Futures | ETH Futures |
|--------------|------------|-------------|
| Trading hours | Near 24/7 | Near 24/7 |
| Volatility | 2-5x ES | 3-6x ES |
| Liquidity | Moderate | Lower than BTC |
| Mean reversion | Less reliable (strong trends) | Less reliable |
| Momentum | Strong continuation tendency | Very strong |
| Best strategy | Momentum Scalp (adapted) | Momentum Scalp (adapted) |
| Stop width | Must be wider (higher ATR) | Must be wider |

**Warning**: Crypto futures have different risk characteristics than index futures. Test thoroughly before deploying with real capital. Consider using micro contracts if available.

---

## 15. Research Resources & Data Sources

### Market Data

| Resource | Purpose | Cost |
|----------|---------|------|
| TradingView | Charting, backtesting, Pine Script | $14.95-59.95/mo |
| CME DataMine | Official futures data | Varies |
| Quandl/Nasdaq Data Link | Historical futures data | Free tier available |
| Polygon.io | Real-time and historical data API | $29-199/mo |

### Economic Calendars

| Resource | Purpose | Cost |
|----------|---------|------|
| ForexFactory | Economic event calendar | Free |
| Investing.com | Economic calendar with forecasts | Free |
| TradingEconomics | Historical economic data | Free tier available |
| CME FedWatch | FOMC probability tracker | Free |

### Research & Education

| Resource | Focus | Type |
|----------|-------|------|
| "Advances in Financial Machine Learning" (de Prado) | Quantitative strategy development | Book |
| "Trading and Exchanges" (Harris) | Market microstructure | Book |
| QuantConnect / Lean | Open-source backtesting framework | Platform (free) |
| Tastytrade Research | Options/futures volatility research | Videos (free) |
| CME Institute | Futures education | Courses (free) |

### Apex Trader Funding Resources

| Resource | Purpose |
|----------|---------|
| Apex Trader Funding Rules Page | Current rule verification |
| Apex Discord/Community | Rule clarifications, updates |
| Tradovate API Documentation | API endpoint reference |
| Tradovate WebSocket Guide | Real-time data integration |
