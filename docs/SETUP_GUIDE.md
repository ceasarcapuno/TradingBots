# Step-by-Step Setup Guide

Complete instructions for deploying the Autonomous Trading System across 20 Apex Trader Funding accounts with TradingView webhook integration.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Server Environment Setup](#2-server-environment-setup)
3. [Application Installation](#3-application-installation)
4. [Apex Trader Funding Account Configuration](#4-apex-trader-funding-account-configuration)
5. [Tradovate API Credentials Setup](#5-tradovate-api-credentials-setup)
6. [Environment Variables Configuration](#6-environment-variables-configuration)
7. [TradingView Pine Script Deployment](#7-tradingview-pine-script-deployment)
8. [TradingView Webhook Alert Configuration](#8-tradingview-webhook-alert-configuration)
9. [SSL/HTTPS Setup for Webhook Server](#9-sslhttps-setup-for-webhook-server)
10. [Dry Run Testing](#10-dry-run-testing)
11. [Running the Test Suite](#11-running-the-test-suite)
12. [Live Deployment](#12-live-deployment)
13. [Monitoring & Maintenance](#13-monitoring--maintenance)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Prerequisites

### Required Accounts

| Account | Purpose | Quantity |
|---------|---------|----------|
| Apex Trader Funding | Trading accounts ($50K EVAL, Tradovate platform) | 20 |
| Tradovate | Brokerage platform (included with Apex) | 20 (one per Apex account) |
| TradingView | Charting + Pine Script alerts (Pro/Pro+/Premium required for webhooks) | 1 (Premium recommended for multiple alerts) |

### TradingView Plan Requirements

TradingView **Pro plan or higher** is required for webhook alerts. Plan comparison for this system:

| Feature | Pro ($14.95/mo) | Pro+ ($29.95/mo) | Premium ($59.95/mo) |
|---------|-----------------|-------------------|---------------------|
| Webhook alerts | Yes | Yes | Yes |
| Active alerts | 20 | 100 | 400 |
| Charts/layout | 2 | 4 | 8 |
| Indicators/chart | 5 | 10 | 25 |

**Recommendation**: Start with **Pro+** (100 alerts covers 3 strategies x 2 instruments x multiple alert types). Upgrade to Premium if you need more simultaneous alerts.

### Server Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Ubuntu 20.04+ / Debian 11+ | Ubuntu 22.04 LTS |
| CPU | 2 cores | 4 cores |
| RAM | 2 GB | 4 GB |
| Storage | 10 GB | 20 GB SSD |
| Network | Static IP or domain name | Domain with SSL certificate |
| Python | 3.11+ | 3.12 |
| Uptime | 99.5%+ | 99.9%+ (use a cloud provider) |

**Recommended Cloud Providers** (for low-latency to CME/Tradovate):
- AWS (us-east-1 region — closest to CME data centers in Aurora, IL)
- DigitalOcean (NYC or Chicago datacenter)
- Vultr (Chicago location)
- Hetzner (if budget-focused — US East)

### Software Dependencies

- Python 3.11 or 3.12
- pip (Python package manager)
- git
- openssl (for SSL certificate generation)
- systemd (for running as a service) or Docker

---

## 2. Server Environment Setup

### 2.1 Provision a Cloud Server

Choose a cloud provider and create a server with the specs above. Example with DigitalOcean:

```bash
# After creating a Droplet (Ubuntu 22.04, 4GB RAM, NYC1)
# SSH into the server
ssh root@your-server-ip
```

### 2.2 Create a Non-Root User

```bash
# Create a dedicated user for the trading system
adduser tradingbot
usermod -aG sudo tradingbot
su - tradingbot
```

### 2.3 Install System Dependencies

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.12 and build tools
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
    python3-pip git curl openssl build-essential

# Verify Python version
python3.12 --version
# Expected: Python 3.12.x

# Install pip for Python 3.12
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12
```

### 2.4 Configure Firewall

```bash
# Allow SSH and webhook port only
sudo ufw allow 22/tcp        # SSH
sudo ufw allow 8443/tcp      # Webhook server (HTTPS)
sudo ufw enable
sudo ufw status
```

### 2.5 Set Timezone to Central Time

The system uses Central Time (CT) for Apex Trader Funding session management:

```bash
sudo timedatectl set-timezone America/Chicago
timedatectl
# Should show: Time zone: America/Chicago (CST/CDT)
```

---

## 3. Application Installation

### 3.1 Clone the Repository

```bash
cd /home/tradingbot
git clone https://github.com/ceasarcapuno/TradingBots.git
cd TradingBots
```

### 3.2 Create Python Virtual Environment

```bash
python3.12 -m venv venv
source venv/bin/activate

# Verify you're using the virtual environment
which python
# Expected: /home/tradingbot/TradingBots/venv/bin/python
```

### 3.3 Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt

# Verify key packages installed
python -c "import fastapi, httpx, structlog; print('All packages OK')"
```

### 3.4 Create Required Directories

```bash
mkdir -p data logs credentials
```

### 3.5 Verify Project Structure

```bash
# Should show all required directories
ls -la src/ config/ pinescript/ tests/
```

---

## 4. Apex Trader Funding Account Configuration

### 4.1 Create 20 Apex Accounts

1. Go to [Apex Trader Funding](https://apextraderfunding.com)
2. Purchase 20 x $50K EVAL accounts (select **Tradovate** as platform)
3. Wait for each account to be provisioned (usually within 24 hours)
4. Record the following for **each** account:

| Field | Example | Notes |
|-------|---------|-------|
| Apex Account # | APEX-12345 | From Apex dashboard |
| Tradovate Username | apex_user_01 | From Tradovate credentials email |
| Tradovate Password | xxxxxxxxxx | From Tradovate credentials email |
| Account Phase | EVAL | All start as EVAL |

### 4.2 Log Into Each Tradovate Account

For each of the 20 accounts:

1. Go to [Tradovate](https://trader.tradovateapi.com)
2. Log in with the credentials provided by Apex
3. Verify the account appears and shows $50,000 starting balance
4. Note the numeric Account ID visible in the Tradovate dashboard
5. **Important**: Do NOT change any account settings — Apex monitors these

### 4.3 Enable API Access on Tradovate

For each account, you need API access:

1. Log into Tradovate
2. Navigate to **Settings** > **API Access**
3. If API access requires an application registration:
   - Register a new application (one registration can be used across accounts)
   - Record the **App ID**, **CID (Client ID)**, and **Secret**
4. These credentials will go into your account configuration file

### 4.4 Create the Account Configuration File

```bash
# Copy the example config
cp config/accounts.example.json config/accounts.json

# Edit with your actual credentials
nano config/accounts.json
```

Fill in the real credentials for all 20 accounts:

```json
[
  {
    "account_id": "APEX_01",
    "phase": "EVAL",
    "starting_balance": 50000.0,
    "credentials": {
      "username": "your_actual_tradovate_username_01",
      "password": "your_actual_tradovate_password_01"
    }
  },
  {
    "account_id": "APEX_02",
    "phase": "EVAL",
    "starting_balance": 50000.0,
    "credentials": {
      "username": "your_actual_tradovate_username_02",
      "password": "your_actual_tradovate_password_02"
    }
  }
]
```

**Repeat for all 20 accounts.**

### 4.5 Secure the Credentials File

```bash
# Restrict permissions — only your user can read
chmod 600 config/accounts.json

# Verify it's in .gitignore (it should NOT be committed)
grep "accounts.json" .gitignore || echo "config/accounts.json" >> .gitignore
```

---

## 5. Tradovate API Credentials Setup

### 5.1 Register a Tradovate API Application

1. Visit the [Tradovate API portal](https://trader.tradovateapi.com)
2. Navigate to **Developer** > **API Applications**
3. Click **Register New Application**
4. Fill in:
   - **App Name**: "Autonomous Trading System" (or any name)
   - **App Version**: "1.0"
   - **Redirect URI**: Leave blank (not needed for server-to-server)
5. After registration, you'll receive:
   - **App ID**: A string like `SampleApp`
   - **CID**: A numeric client ID
   - **Secret**: A long alphanumeric string

### 5.2 Test API Authentication

```bash
# Activate virtual environment if not active
source venv/bin/activate

# Quick auth test with one account
python -c "
import asyncio
from src.accounts.tradovate_client import TradovateClient
from config.settings import TradovateConfig

config = TradovateConfig(
    use_demo=True,  # Use demo endpoint first
    app_id='YOUR_APP_ID',
    cid=YOUR_CID,
    sec='YOUR_SECRET',
)

client = TradovateClient('TEST', config, {
    'username': 'your_tradovate_username',
    'password': 'your_tradovate_password',
})

result = asyncio.run(client.authenticate())
print(f'Authentication: {\"SUCCESS\" if result else \"FAILED\"}')
"
```

If authentication succeeds, your API credentials are correct.

---

## 6. Environment Variables Configuration

### 6.1 Create the .env File

```bash
cp .env.example .env
nano .env
```

### 6.2 Configure All Settings

Edit `.env` with your actual values:

```bash
# =============================================================================
# SYSTEM CONFIGURATION
# =============================================================================

# Start with dry_run=true to test without placing real orders
SYS_DRY_RUN=true
SYS_LOG_LEVEL=INFO
SYS_TOTAL_ACCOUNTS=20

# =============================================================================
# WEBHOOK SERVER
# =============================================================================

# Generate a strong random token (this must match your TradingView alerts)
# Run: python -c "import secrets; print(secrets.token_urlsafe(32))"
WEBHOOK_SECRET_TOKEN=your_generated_secret_token_here
WEBHOOK_PORT=8443
WEBHOOK_SSL_CERT_PATH=/home/tradingbot/TradingBots/credentials/cert.pem
WEBHOOK_SSL_KEY_PATH=/home/tradingbot/TradingBots/credentials/key.pem

# =============================================================================
# TRADOVATE API
# =============================================================================

# Start with demo=true for testing, switch to false for live
TRADOVATE_USE_DEMO=true
TRADOVATE_APP_ID=YourAppId
TRADOVATE_CID=1234
TRADOVATE_SEC=your_api_secret_here

# =============================================================================
# COPY TRADING
# =============================================================================

COPY_MIN_DELAY_MS=500
COPY_MAX_DELAY_MS=5000
COPY_SIZE_VARIANCE_PCT=0.20
COPY_SKIP_PROBABILITY=0.10
```

### 6.3 Generate Your Webhook Secret Token

```bash
# Generate a cryptographically secure token
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Example output: dKx9F2mPqR1tJvN7wL4sZ8aHcY6bEu3g0iXoQj5k

# Copy this value into both:
# 1. WEBHOOK_SECRET_TOKEN in .env
# 2. The webhookToken input in each TradingView Pine Script strategy
```

### 6.4 Secure the .env File

```bash
chmod 600 .env
```

---

## 7. TradingView Pine Script Deployment

### 7.1 Access Pine Script Files

The three strategy scripts are in the `pinescript/` directory:

```
pinescript/
├── vwap_reversion_strategy.pine
├── opening_range_breakout_strategy.pine
└── momentum_scalp_strategy.pine
```

### 7.2 Deploy Each Strategy to TradingView

**Repeat these steps for each of the 3 strategy files:**

1. Open [TradingView](https://www.tradingview.com) and log in
2. Open a chart for the target instrument:
   - **ES** (E-mini S&P 500 Futures) — use the continuous contract `ES1!`
   - **NQ** (E-mini Nasdaq Futures) — use `NQ1!`
3. Set the timeframe:
   - VWAP Reversion: **5-minute** chart
   - Opening Range Breakout: **5-minute** chart (can also use 1-minute)
   - Momentum Scalp: **5-minute** chart
4. Open the Pine Script Editor (bottom panel, click "Pine Editor")
5. Click **"Open"** > **"New indicator"**
6. Delete the default code
7. Copy the entire contents of the `.pine` file and paste it into the editor
8. **Critical**: Change the `webhookToken` default value:
   - Find the line: `webhookToken = input.string("YOUR_SECRET_TOKEN", "Webhook Auth Token")`
   - Replace `YOUR_SECRET_TOKEN` with the same token from your `.env` file
9. Click **"Save"** and give it a name (e.g., "VWAP Reversion Webhook")
10. Click **"Add to Chart"**
11. Verify the strategy appears on the chart with visual signals

### 7.3 Strategy-Specific Chart Setup

#### VWAP Reversion (ES 5-min chart)
- Confirm VWAP line (blue) appears on chart
- Confirm upper/lower deviation bands appear
- Green triangles (long signals) should appear below price
- Red triangles (short signals) should appear above price

#### Opening Range Breakout (ES 5-min chart)
- Confirm yellow background during 8:30-8:45 AM CT (opening range period)
- Confirm green/red horizontal lines appear after 8:45 AM (range boundaries)
- Arrow signals should appear on breakout bars

#### Momentum Scalp (ES or NQ 5-min chart)
- Confirm orange (fast EMA) and blue (slow EMA) lines on chart
- Confirm green background during favorable conditions
- Triangle signals on EMA crossover bars

### 7.4 Verify Pine Script Strategy Settings

For each deployed strategy, click the gear icon to open strategy settings:

| Setting | Recommended Value |
|---------|------------------|
| Order Size | 1 (contract) |
| Commission | 2.50 (per side) |
| Slippage | 1 (tick) |
| Initial Capital | 50000 |

---

## 8. TradingView Webhook Alert Configuration

### 8.1 Understand the Alert Architecture

Each Pine Script strategy generates JSON payloads when signals fire. You need to create TradingView alerts that send these payloads to your webhook server.

**Total alerts needed**: 3 strategies x 2 instruments (ES, NQ) = **6 alerts minimum**

### 8.2 Create Webhook Alerts

**For each strategy on each instrument, repeat these steps:**

1. On the TradingView chart with the strategy active, click **"Alert"** (clock icon) or press `Alt+A`

2. Configure the alert:

   | Field | Value |
   |-------|-------|
   | Condition | The strategy name (e.g., "VWAP Reversion [Webhook]") |
   | Trigger | "Order fills only" |
   | Expiration | "Open-ended alert" |
   | Alert name | e.g., "VWAP_ES_Webhook" |

3. In the **Notifications** tab:
   - Check **"Webhook URL"**
   - Enter your webhook URL: `https://your-server-ip:8443/webhook`
     (or `https://your-domain.com:8443/webhook` if using a domain)

4. In the **Message** field:
   - **Leave it as the default** — the Pine Script `alert()` function provides the JSON payload automatically
   - If TradingView shows a custom message box, ensure it contains `{{strategy.order.alert_message}}`

5. Click **"Create"**

### 8.3 Alert Naming Convention

Use consistent names so you can manage 6+ alerts:

```
VWAP_ES_Webhook
VWAP_NQ_Webhook
ORB_ES_Webhook
ORB_NQ_Webhook
MOMENTUM_ES_Webhook
MOMENTUM_NQ_Webhook
```

### 8.4 Verify Alerts Are Active

1. Go to **TradingView** > **Alerts** panel
2. Confirm all 6 alerts show as **"Active"** (green dot)
3. Each alert should show "Webhook" as a notification method

### 8.5 Test a Webhook Alert

Before going live, verify the webhook chain works:

```bash
# On your server, start the system in dry-run mode
cd /home/tradingbot/TradingBots
source venv/bin/activate
python main.py

# In another terminal, send a test webhook
curl -X POST https://localhost:8443/webhook \
  -H "Content-Type: application/json" \
  -k \
  -d '{
    "token": "your_webhook_secret_token",
    "strategy": "vwap_reversion",
    "action": "long_entry",
    "instrument": "ES",
    "price": 5000.00,
    "stop_loss": 4996.00,
    "take_profit": 5006.00,
    "confidence": 0.72,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'

# Expected response:
# {"status":"accepted","signal_id":"wh_xxxxxxxx","message":"Signal routed to 5 accounts","accounts_targeted":5}
```

---

## 9. SSL/HTTPS Setup for Webhook Server

TradingView sends webhooks over HTTPS. Your server must have a valid SSL certificate.

### Option A: Self-Signed Certificate (for testing)

```bash
# Generate a self-signed certificate
mkdir -p credentials
openssl req -x509 -newkey rsa:4096 -keyout credentials/key.pem \
  -out credentials/cert.pem -days 365 -nodes \
  -subj "/CN=your-server-ip"

# Update .env
# WEBHOOK_SSL_CERT_PATH=/home/tradingbot/TradingBots/credentials/cert.pem
# WEBHOOK_SSL_KEY_PATH=/home/tradingbot/TradingBots/credentials/key.pem
```

**Note**: TradingView may reject self-signed certificates. Use Option B for production.

### Option B: Let's Encrypt Certificate (recommended for production)

```bash
# Install certbot
sudo apt install -y certbot

# Point a domain to your server IP first (e.g., trading.yourdomain.com)
# Then get a certificate
sudo certbot certonly --standalone -d trading.yourdomain.com

# Certificates will be at:
# /etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/trading.yourdomain.com/privkey.pem

# Update .env
# WEBHOOK_SSL_CERT_PATH=/etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem
# WEBHOOK_SSL_KEY_PATH=/etc/letsencrypt/live/trading.yourdomain.com/privkey.pem

# Set up auto-renewal
sudo certbot renew --dry-run
```

### Option C: Reverse Proxy with Nginx (most robust)

```bash
# Install Nginx
sudo apt install -y nginx

# Configure as reverse proxy
sudo nano /etc/nginx/sites-available/trading-webhook
```

Nginx config:

```nginx
server {
    listen 443 ssl;
    server_name trading.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/trading.yourdomain.com/privkey.pem;

    location /webhook {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8443;
    }
}
```

```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/trading-webhook /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

With this setup, TradingView sends to `https://trading.yourdomain.com/webhook` (port 443), and Nginx proxies to the internal FastAPI server on port 8443.

---

## 10. Dry Run Testing

### 10.1 Start in Dry Run Mode

```bash
cd /home/tradingbot/TradingBots
source venv/bin/activate

# Start with default dry-run configuration
python main.py

# You should see:
# ============================================================
#   AUTONOMOUS TRADING SYSTEM
#   Mode: DRY RUN
#   Accounts: 20
#   Webhook: 0.0.0.0:8443
#   News Filter: ON
#   Copy Trading: ON
# ============================================================
```

### 10.2 Verify Webhook Reception

In a separate terminal:

```bash
# Check if the webhook server is responding
curl -k https://localhost:8443/health

# Expected:
# {"status":"ok","signals_received":0,"signals_accepted":0,"uptime":"running"}
```

### 10.3 Send Test Signals

```bash
# Send a long entry signal
curl -X POST https://localhost:8443/webhook \
  -H "Content-Type: application/json" -k \
  -d '{
    "token": "YOUR_WEBHOOK_SECRET",
    "strategy": "vwap_reversion",
    "action": "long_entry",
    "instrument": "ES",
    "price": 5012.50,
    "stop_loss": 5008.50,
    "take_profit": 5018.50,
    "confidence": 0.72,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'

# Send a flatten signal
curl -X POST https://localhost:8443/webhook \
  -H "Content-Type: application/json" -k \
  -d '{
    "token": "YOUR_WEBHOOK_SECRET",
    "strategy": "vwap_reversion",
    "action": "flatten",
    "instrument": "ES",
    "price": 5015.00,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

### 10.4 Check Logs

```bash
# View live logs
tail -f logs/trading.log

# Look for:
# - "webhook_signal_accepted" — signal received and processed
# - "copy_dry_run_order" — orders would have been placed (dry run)
# - "trade_validated" — risk checks passed
```

### 10.5 Dry Run Checklist

Verify each item before proceeding to live:

- [ ] Webhook server starts without errors
- [ ] Health endpoint responds (`/health`)
- [ ] Test signals are accepted (valid token)
- [ ] Test signals are rejected (invalid token → 401)
- [ ] Rate limiting works (send 61 requests in 1 minute → 429)
- [ ] Stale signals are rejected (send a signal with old timestamp)
- [ ] Copy engine distributes to correct number of accounts
- [ ] Logs show risk validation for each account
- [ ] Compliance checks run (check for trading window messages)
- [ ] No exceptions or crashes in logs

---

## 11. Running the Test Suite

### 11.1 Run All Tests

```bash
cd /home/tradingbot/TradingBots
source venv/bin/activate

# Run the full test suite
python -m pytest tests/ -v

# Expected output:
# tests/test_risk_manager.py::TestPreTradeValidation::test_valid_trade_passes PASSED
# tests/test_risk_manager.py::TestPreTradeValidation::test_halted_account_rejected PASSED
# tests/test_risk_manager.py::TestPreTradeValidation::test_daily_loss_limit_blocks_trade PASSED
# ... (all tests should pass)
```

### 11.2 Run Tests with Coverage

```bash
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```

### 11.3 Run Specific Test Modules

```bash
# Risk manager tests only
python -m pytest tests/test_risk_manager.py -v

# Compliance tests only
python -m pytest tests/test_compliance.py -v
```

---

## 12. Live Deployment

### 12.1 Pre-Launch Checklist

Before switching to live mode, confirm:

- [ ] All 20 Tradovate accounts are authenticated (`accounts.json` configured)
- [ ] API credentials are correct (tested with one account)
- [ ] Webhook server has valid SSL certificate
- [ ] TradingView alerts are active and pointing to correct URL
- [ ] Webhook token matches between `.env` and Pine Script strategies
- [ ] Dry run testing completed successfully (Section 10)
- [ ] All tests pass (Section 11)
- [ ] Server timezone is America/Chicago
- [ ] Firewall is configured (only ports 22 and 8443 open)
- [ ] Current time is NOT during close window (4:59-6:00 PM CT)

### 12.2 Switch to Live Mode

```bash
# Edit .env
nano .env

# Change these values:
# SYS_DRY_RUN=false
# TRADOVATE_USE_DEMO=false
```

### 12.3 Start the Live System

```bash
# Start with explicit live flag and account config
python main.py --live --accounts config/accounts.json

# CRITICAL WARNING will appear:
# "LIVE_MODE_ENABLED — real orders will be placed"
```

### 12.4 Set Up as a systemd Service (Recommended)

Create a service file so the system starts automatically and restarts on failure:

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

```ini
[Unit]
Description=Autonomous Trading System
After=network.target

[Service]
Type=simple
User=tradingbot
WorkingDirectory=/home/tradingbot/TradingBots
Environment=PATH=/home/tradingbot/TradingBots/venv/bin:/usr/bin
ExecStart=/home/tradingbot/TradingBots/venv/bin/python main.py --live --accounts config/accounts.json
Restart=on-failure
RestartSec=10
StandardOutput=append:/home/tradingbot/TradingBots/logs/stdout.log
StandardError=append:/home/tradingbot/TradingBots/logs/stderr.log

# Safety: stop cleanly (triggers graceful shutdown → flatten all)
TimeoutStopSec=60
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot

# Check status
sudo systemctl status trading-bot

# View live logs
sudo journalctl -u trading-bot -f
```

### 12.5 First Trading Day Protocol

On the first live trading day:

1. **Start the system at 5:30 PM CT** (30 min before Sunday open at 6:00 PM CT)
2. **Monitor logs actively** for the first 2 hours
3. **Verify first webhook signal** is received and distributed correctly
4. **Check Tradovate dashboard** for each account to confirm orders appear
5. **Watch the first trade** through its full lifecycle (entry → stop/target → exit)
6. **Verify risk levels** are updating correctly
7. **Confirm positions flatten** before close window (by 4:57 PM CT)

---

## 13. Monitoring & Maintenance

### 13.1 Daily Monitoring

```bash
# Check system health
curl -k https://localhost:8443/health

# Check system logs for errors
grep -i "error\|critical\|warning" logs/trading.log | tail -20

# Check account statuses
python -c "
from config.settings import SystemConfig
from src.core.orchestrator import Orchestrator
import json
o = Orchestrator(SystemConfig())
print(json.dumps(o.get_system_status(), indent=2, default=str))
"
```

### 13.2 Weekly Maintenance

1. **Review performance metrics**: Check win rate, profit factor, EVAL progress
2. **Check account balances**: Verify all accounts are healthy
3. **Review strategy performance**: Identify if any strategy should be paused
4. **Update economic calendar**: Add upcoming FOMC dates, NFP dates to custom events
5. **Check TradingView alerts**: Ensure all alerts are still active
6. **Renew SSL certificate**: If using Let's Encrypt, `sudo certbot renew`

### 13.3 Log Rotation

```bash
# Set up logrotate to prevent disk space issues
sudo nano /etc/logrotate.d/trading-bot
```

```
/home/tradingbot/TradingBots/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
}
```

### 13.4 Updating the System

```bash
# Stop the service
sudo systemctl stop trading-bot

# Pull updates
cd /home/tradingbot/TradingBots
git pull origin main

# Install any new dependencies
source venv/bin/activate
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Restart
sudo systemctl start trading-bot
```

---

## 14. Troubleshooting

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Webhook returns 401 | Token mismatch | Verify `WEBHOOK_SECRET_TOKEN` in `.env` matches `webhookToken` in Pine Script |
| Webhook returns 429 | Rate limit exceeded | Check for misconfigured TradingView alerts firing too frequently |
| TradingView "Webhook error" | SSL certificate issue | Use Let's Encrypt or Nginx reverse proxy (Section 9) |
| No signals received | Alerts not active | Check TradingView alerts panel — ensure all show green "Active" status |
| "Account auth failed" in logs | Wrong Tradovate credentials | Re-verify username/password in `accounts.json`; check if Apex reset the password |
| Orders not filling | Using demo endpoint | Set `TRADOVATE_USE_DEMO=false` in `.env` |
| "Account terminated" in logs | Drawdown threshold breached | Account lost — remove from `accounts.json` and purchase a new one |
| All accounts paused | Portfolio daily loss limit hit | Wait until next trading day (auto-resets) or review if strategy is broken |
| "Stale signal" rejections | Server clock drift | Run `sudo ntpd -gq` or install `chrony` to keep clock synced |
| Pine Script not generating alerts | Strategy parameters too strict | Loosen filters (reduce ADX max, reduce ATR deviation threshold) in strategy settings |

### Emergency Procedures

**Flatten all positions immediately:**
```bash
curl -X POST https://localhost:8443/flatten-all \
  -H "Authorization: Bearer YOUR_WEBHOOK_SECRET"
```

**Stop the system gracefully:**
```bash
sudo systemctl stop trading-bot
# This sends SIGTERM → triggers graceful shutdown → flattens all → exits
```

**Force stop (if graceful fails):**
```bash
sudo systemctl kill trading-bot
# THEN manually check Tradovate for any remaining positions
```

### Getting Help

- Review logs: `tail -100 logs/trading.log`
- Check the `ARCHITECTURE.md` for system design details
- Review the `STRATEGY_GUIDE.md` for strategy tuning guidance
