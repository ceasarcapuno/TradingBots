"""
Webhook Server

Receives signals from TradingView Pine Script alerts and routes them
through the copy trading engine to multiple Tradovate accounts.

Architecture:
  TradingView Alert → HTTPS POST → This Server → Validation →
  Copy Trading Engine → Risk Check → Order Router → Tradovate Accounts

Security:
  - Token-based authentication (shared secret in webhook payload)
  - Rate limiting per source IP
  - Signal age validation (reject stale signals)
  - HTTPS only in production
"""

import asyncio
import hmac
import structlog
import time as time_module
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.core.models import (
    WebhookPayload, TradingSignal, SignalAction, StrategyName,
)
from src.core.events import event_bus, Event, EventType
from config.settings import SystemConfig

logger = structlog.get_logger()


# ─── Request/Response Models ─────────────────────────────────────────────────

class WebhookRequest(BaseModel):
    token: str
    strategy: str
    action: str
    instrument: str
    price: float
    timestamp: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: Optional[float] = 0.5
    contracts: Optional[int] = None
    metadata: Optional[dict] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    status: str
    signal_id: Optional[str] = None
    message: str = ""
    accounts_targeted: int = 0


# ─── Rate Limiter ────────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, max_per_minute: int = 60):
        self.max_per_minute = max_per_minute
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, client_ip: str) -> bool:
        now = time_module.time()
        window = now - 60
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > window
        ]
        if len(self._requests[client_ip]) >= self.max_per_minute:
            return False
        self._requests[client_ip].append(now)
        return True


# ─── Webhook Server ──────────────────────────────────────────────────────────

class WebhookServer:
    """
    FastAPI-based webhook receiver for TradingView alerts.
    """

    def __init__(self, config: SystemConfig, signal_handler=None):
        self.config = config
        self.webhook_config = config.webhook
        self.signal_handler = signal_handler  # Callback: async fn(TradingSignal)
        self.rate_limiter = RateLimiter(config.webhook.rate_limit_per_minute)
        self.app = self._create_app()

        # Metrics
        self._signals_received = 0
        self._signals_accepted = 0
        self._signals_rejected = 0

    def _create_app(self) -> FastAPI:
        app = FastAPI(
            title="Trading Webhook Server",
            docs_url=None,      # Disable docs in production
            redoc_url=None,
        )

        @app.post("/webhook", response_model=WebhookResponse)
        async def receive_webhook(request: Request, payload: WebhookRequest):
            return await self._handle_webhook(request, payload)

        @app.get("/health")
        async def health_check():
            return {
                "status": "ok",
                "signals_received": self._signals_received,
                "signals_accepted": self._signals_accepted,
                "uptime": "running",
            }

        @app.post("/flatten-all")
        async def emergency_flatten(request: Request):
            """Emergency endpoint to flatten all positions across all accounts."""
            return await self._handle_emergency_flatten(request)

        return app

    async def _handle_webhook(self, request: Request,
                              payload: WebhookRequest) -> WebhookResponse:
        """Process an incoming webhook from TradingView."""
        self._signals_received += 1
        client_ip = request.client.host if request.client else "unknown"

        # Rate limiting
        if not self.rate_limiter.check(client_ip):
            self._signals_rejected += 1
            raise HTTPException(429, "Rate limit exceeded")

        # Authentication
        if not self._validate_token(payload.token):
            self._signals_rejected += 1
            logger.warning("webhook_auth_failed", ip=client_ip)
            raise HTTPException(401, "Invalid token")

        # Signal age check
        if not self._validate_signal_age(payload.timestamp):
            self._signals_rejected += 1
            logger.warning("webhook_stale_signal",
                           timestamp=payload.timestamp)
            return WebhookResponse(
                status="rejected",
                message="Signal too old — exceeds max age"
            )

        # Parse and validate signal
        try:
            signal = self._parse_signal(payload)
        except ValueError as e:
            self._signals_rejected += 1
            logger.warning("webhook_parse_error", error=str(e))
            return WebhookResponse(status="rejected", message=str(e))

        # Publish signal event
        await event_bus.publish(Event(
            event_type=EventType.SIGNAL_GENERATED,
            data={
                "signal": signal,
                "source": "webhook",
                "client_ip": client_ip,
            },
            source="webhook_server"
        ))

        # Forward to signal handler (copy trading engine)
        accounts_targeted = 0
        if self.signal_handler:
            accounts_targeted = await self.signal_handler(signal)

        self._signals_accepted += 1
        logger.info("webhook_signal_accepted",
                     signal_id=signal.signal_id,
                     strategy=signal.strategy.value,
                     action=signal.action.value,
                     instrument=signal.instrument,
                     accounts=accounts_targeted)

        return WebhookResponse(
            status="accepted",
            signal_id=signal.signal_id,
            message=f"Signal routed to {accounts_targeted} accounts",
            accounts_targeted=accounts_targeted,
        )

    def _validate_token(self, token: str) -> bool:
        """Constant-time token comparison."""
        expected = self.webhook_config.secret_token
        return hmac.compare_digest(token, expected)

    def _validate_signal_age(self, timestamp_str: str) -> bool:
        """Reject signals older than max_signal_age_seconds."""
        try:
            # TradingView sends ISO format timestamps
            signal_time = datetime.fromisoformat(
                timestamp_str.replace("Z", "+00:00")
            )
            now = datetime.now(timezone.utc)
            age = (now - signal_time).total_seconds()
            return abs(age) <= self.webhook_config.max_signal_age_seconds
        except (ValueError, TypeError):
            # If we can't parse the timestamp, allow it (TradingView format varies)
            return True

    def _parse_signal(self, payload: WebhookRequest) -> TradingSignal:
        """Convert webhook payload to internal TradingSignal."""
        try:
            strategy = StrategyName(payload.strategy)
        except ValueError:
            raise ValueError(f"Unknown strategy: {payload.strategy}")

        try:
            action = SignalAction(payload.action)
        except ValueError:
            raise ValueError(f"Unknown action: {payload.action}")

        import uuid
        return TradingSignal(
            signal_id=f"wh_{uuid.uuid4().hex[:8]}",
            strategy=strategy,
            instrument=payload.instrument,
            action=action,
            price=payload.price,
            timestamp=datetime.utcnow(),
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            contracts=payload.contracts or 1,
            confidence=payload.confidence or 0.5,
            metadata=payload.metadata or {},
        )

    async def _handle_emergency_flatten(self, request: Request) -> dict:
        """Emergency flatten all — requires token in header."""
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {self.webhook_config.secret_token}"):
            raise HTTPException(401, "Invalid authorization")

        await event_bus.publish(Event(
            event_type=EventType.EMERGENCY_FLATTEN,
            data={"reason": "manual_emergency", "scope": "all"},
            source="webhook_server"
        ))
        logger.critical("emergency_flatten_triggered", source="webhook_endpoint")
        return {"status": "flatten_all_triggered"}

    def get_metrics(self) -> dict:
        return {
            "signals_received": self._signals_received,
            "signals_accepted": self._signals_accepted,
            "signals_rejected": self._signals_rejected,
            "acceptance_rate": (
                self._signals_accepted / self._signals_received
                if self._signals_received > 0 else 0
            ),
        }
