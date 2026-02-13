"""
Event bus for decoupled communication between system components.
"""

import asyncio
import structlog
from collections import defaultdict
from typing import Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = structlog.get_logger()


class EventType(str, Enum):
    # Signal events
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_VALIDATED = "signal_validated"
    SIGNAL_REJECTED = "signal_rejected"

    # Order events
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"

    # Position events
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"

    # Risk events
    RISK_WARNING = "risk_warning"
    RISK_DANGER = "risk_danger"
    RISK_CRITICAL = "risk_critical"
    CIRCUIT_BREAKER_TRIGGERED = "circuit_breaker_triggered"
    DAILY_LIMIT_HIT = "daily_limit_hit"
    EMERGENCY_FLATTEN = "emergency_flatten"

    # Compliance events
    COMPLIANCE_VIOLATION = "compliance_violation"
    COMPLIANCE_WARNING = "compliance_warning"
    FLATTEN_REQUIRED = "flatten_required"

    # Account events
    ACCOUNT_PAUSED = "account_paused"
    ACCOUNT_RESUMED = "account_resumed"
    ACCOUNT_PASSED_EVAL = "account_passed_eval"
    ACCOUNT_TERMINATED = "account_terminated"

    # Market events
    NEWS_BLACKOUT_START = "news_blackout_start"
    NEWS_BLACKOUT_END = "news_blackout_end"
    VOLATILITY_SPIKE = "volatility_spike"
    SESSION_OPEN = "session_open"
    SESSION_CLOSE = "session_close"

    # System events
    SYSTEM_START = "system_start"
    SYSTEM_SHUTDOWN = "system_shutdown"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


@dataclass
class Event:
    event_type: EventType
    data: dict = field(default_factory=dict)
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    account_id: str = ""


class EventBus:
    """Async publish/subscribe event bus for system-wide communication."""

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable]] = defaultdict(list)
        self._event_history: list[Event] = []
        self._max_history = 10000

    def subscribe(self, event_type: EventType, handler: Callable):
        self._subscribers[event_type].append(handler)
        logger.debug("event_subscription_added", event_type=event_type.value,
                      handler=handler.__qualname__)

    def subscribe_many(self, event_types: list[EventType], handler: Callable):
        for et in event_types:
            self.subscribe(et, handler)

    async def publish(self, event: Event):
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        handlers = self._subscribers.get(event.event_type, [])
        if not handlers:
            return

        tasks = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(handler(event))
            else:
                # Wrap sync handlers
                tasks.append(asyncio.to_thread(handler, event))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("event_handler_error",
                             event_type=event.event_type.value,
                             handler=handlers[i].__qualname__,
                             error=str(result))

    def get_recent_events(self, event_type: EventType = None,
                          limit: int = 100) -> list[Event]:
        events = self._event_history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]


# Singleton event bus
event_bus = EventBus()
