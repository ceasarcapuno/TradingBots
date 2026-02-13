"""
Market Intelligence & Economic Event Handler

Monitors economic calendar and market conditions to:
  1. Suspend trading before high-impact news events
  2. Detect volatility spikes and adjust behavior
  3. Track session characteristics (trending vs. range-bound)
  4. Provide market context to strategy evaluation

Critical events requiring trading suspension:
  - FOMC rate decisions and minutes
  - Non-Farm Payrolls (NFP)
  - CPI / PPI releases
  - GDP announcements
  - Initial jobless claims (moderate impact)
  - Fed chair speeches

The news filter maintains a static calendar of recurring events
and can be extended with API-based dynamic calendar feeds.
"""

import asyncio
import structlog
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from enum import Enum

from src.core.events import event_bus, Event, EventType
from config.settings import SystemConfig

logger = structlog.get_logger()

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")


class NewsImpact(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EconomicEvent:
    def __init__(self, name: str, impact: NewsImpact,
                 typical_time_et: str, day_of_week: int = None,
                 week_of_month: int = None, day_of_month: int = None,
                 blackout_before_min: int = 5, blackout_after_min: int = 5):
        self.name = name
        self.impact = impact
        self.typical_time_et = typical_time_et  # "HH:MM" Eastern
        self.day_of_week = day_of_week          # 0=Mon, 4=Fri
        self.week_of_month = week_of_month      # 1=first week, etc.
        self.day_of_month = day_of_month
        self.blackout_before_min = blackout_before_min
        self.blackout_after_min = blackout_after_min


# ─── Static Calendar of Major US Economic Events ─────────────────────────────
# These are recurring events. For exact dates, integrate with an API.

RECURRING_EVENTS = [
    # FOMC — 8 meetings per year, 2:00 PM ET
    EconomicEvent("FOMC Rate Decision", NewsImpact.HIGH, "14:00",
                  blackout_before_min=15, blackout_after_min=30),

    # Non-Farm Payrolls — First Friday of month, 8:30 AM ET
    EconomicEvent("Non-Farm Payrolls", NewsImpact.HIGH, "08:30",
                  day_of_week=4, week_of_month=1,
                  blackout_before_min=10, blackout_after_min=15),

    # CPI — ~12th of each month, 8:30 AM ET
    EconomicEvent("CPI Release", NewsImpact.HIGH, "08:30",
                  blackout_before_min=10, blackout_after_min=10),

    # PPI — ~14th of each month, 8:30 AM ET
    EconomicEvent("PPI Release", NewsImpact.MEDIUM, "08:30",
                  blackout_before_min=5, blackout_after_min=5),

    # GDP — End of month, 8:30 AM ET
    EconomicEvent("GDP Release", NewsImpact.HIGH, "08:30",
                  blackout_before_min=10, blackout_after_min=10),

    # Initial Jobless Claims — Every Thursday, 8:30 AM ET
    EconomicEvent("Jobless Claims", NewsImpact.MEDIUM, "08:30",
                  day_of_week=3,
                  blackout_before_min=3, blackout_after_min=3),

    # ISM Manufacturing — First business day of month, 10:00 AM ET
    EconomicEvent("ISM Manufacturing", NewsImpact.MEDIUM, "10:00",
                  blackout_before_min=5, blackout_after_min=5),

    # Retail Sales — ~15th of month, 8:30 AM ET
    EconomicEvent("Retail Sales", NewsImpact.MEDIUM, "08:30",
                  blackout_before_min=5, blackout_after_min=5),
]


class MarketIntelligence:
    """
    Market intelligence engine providing context for trading decisions.
    """

    def __init__(self, config: SystemConfig):
        self.config = config
        self._blackout_active = False
        self._current_blackout_event: Optional[str] = None
        self._blackout_end: Optional[datetime] = None

        # Custom event dates (add specific dates for FOMC, etc.)
        self._custom_events: list[dict] = []

        # Volatility tracking
        self._recent_atr_values: list[float] = []
        self._volatility_multiplier = 1.0

    # -------------------------------------------------------------------------
    # News Blackout Management
    # -------------------------------------------------------------------------

    async def check_news_blackout(self) -> tuple[bool, Optional[str]]:
        """
        Check if we're currently in a news blackout window.
        Returns (is_blackout, event_name).
        """
        if not self.config.enable_news_filter:
            return False, None

        now_et = datetime.now(ET)
        now_time = now_et.time()
        today_dow = now_et.weekday()

        # Check custom events first (specific dates)
        for event in self._custom_events:
            event_dt = event.get("datetime")
            if event_dt:
                before = event_dt - timedelta(minutes=event.get("blackout_before", 10))
                after = event_dt + timedelta(minutes=event.get("blackout_after", 10))
                if before <= now_et <= after:
                    return True, event.get("name", "Custom Event")

        # Check recurring events
        for event in RECURRING_EVENTS:
            if not self._event_matches_today(event, now_et):
                continue

            h, m = event.typical_time_et.split(":")
            event_time = time(int(h), int(m))
            event_dt = now_et.replace(
                hour=event_time.hour,
                minute=event_time.minute,
                second=0
            )

            before = event_dt - timedelta(minutes=event.blackout_before_min)
            after = event_dt + timedelta(minutes=event.blackout_after_min)

            if before <= now_et <= after:
                if not self._blackout_active:
                    self._blackout_active = True
                    self._current_blackout_event = event.name
                    self._blackout_end = after
                    await event_bus.publish(Event(
                        event_type=EventType.NEWS_BLACKOUT_START,
                        data={"event": event.name,
                              "ends_at": after.isoformat()},
                        source="market_intel"
                    ))
                    logger.warning("news_blackout_started",
                                   event=event.name,
                                   ends_at=after.isoformat())
                return True, event.name

        # Clear blackout if it was active
        if self._blackout_active:
            self._blackout_active = False
            await event_bus.publish(Event(
                event_type=EventType.NEWS_BLACKOUT_END,
                data={"event": self._current_blackout_event},
                source="market_intel"
            ))
            logger.info("news_blackout_ended",
                        event=self._current_blackout_event)
            self._current_blackout_event = None
            self._blackout_end = None

        return False, None

    def _event_matches_today(self, event: EconomicEvent,
                             now: datetime) -> bool:
        """Check if a recurring event falls on today."""
        if event.day_of_week is not None:
            if now.weekday() != event.day_of_week:
                return False
            if event.week_of_month is not None:
                week = (now.day - 1) // 7 + 1
                if week != event.week_of_month:
                    return False
            return True

        # For monthly events without a specific day, check approximate dates
        # In production, use an actual economic calendar API
        return False

    def add_custom_event(self, name: str, event_datetime: datetime,
                         impact: NewsImpact = NewsImpact.HIGH,
                         blackout_before: int = 10,
                         blackout_after: int = 10):
        """Add a specific event date (e.g., known FOMC date)."""
        self._custom_events.append({
            "name": name,
            "datetime": event_datetime,
            "impact": impact.value,
            "blackout_before": blackout_before,
            "blackout_after": blackout_after,
        })
        logger.info("custom_event_added", name=name,
                     datetime=event_datetime.isoformat())

    # -------------------------------------------------------------------------
    # Volatility Monitoring
    # -------------------------------------------------------------------------

    async def update_volatility(self, atr: float, instrument: str):
        """Track ATR values to detect volatility spikes."""
        self._recent_atr_values.append(atr)
        # Keep last 100 readings
        if len(self._recent_atr_values) > 100:
            self._recent_atr_values = self._recent_atr_values[-100:]

        if len(self._recent_atr_values) >= 20:
            avg_atr = sum(self._recent_atr_values[-20:]) / 20
            long_avg = sum(self._recent_atr_values) / len(self._recent_atr_values)

            if long_avg > 0:
                self._volatility_multiplier = avg_atr / long_avg

                # Volatility spike detection
                if self._volatility_multiplier > 2.0:
                    logger.warning("volatility_spike_detected",
                                   instrument=instrument,
                                   multiplier=self._volatility_multiplier)
                    await event_bus.publish(Event(
                        event_type=EventType.VOLATILITY_SPIKE,
                        data={
                            "instrument": instrument,
                            "multiplier": self._volatility_multiplier,
                            "current_atr": atr,
                            "avg_atr": long_avg,
                        },
                        source="market_intel"
                    ))

    def get_volatility_multiplier(self) -> float:
        """
        Returns current volatility relative to recent average.
        > 1.0 means higher than normal, < 1.0 means lower.
        Used by risk manager to adjust position sizing.
        """
        return self._volatility_multiplier

    def should_reduce_size(self) -> bool:
        """Whether current volatility warrants reduced position sizes."""
        return self._volatility_multiplier > 1.5

    def should_halt_trading(self) -> bool:
        """Whether volatility is extreme enough to halt new entries."""
        return self._volatility_multiplier > 3.0

    # -------------------------------------------------------------------------
    # Session Analysis
    # -------------------------------------------------------------------------

    def get_market_context(self) -> dict:
        """Provide current market context for strategy decisions."""
        now_ct = datetime.now(CT)
        now_et = datetime.now(ET)

        return {
            "time_ct": now_ct.strftime("%H:%M"),
            "time_et": now_et.strftime("%H:%M"),
            "is_rth": self._is_regular_trading_hours(now_ct),
            "is_pre_market": self._is_pre_market(now_ct),
            "is_post_market": self._is_post_market(now_ct),
            "blackout_active": self._blackout_active,
            "blackout_event": self._current_blackout_event,
            "volatility_multiplier": self._volatility_multiplier,
            "reduce_size": self.should_reduce_size(),
            "halt_trading": self.should_halt_trading(),
        }

    def _is_regular_trading_hours(self, now_ct: datetime) -> bool:
        """RTH: 8:30 AM - 3:15 PM CT"""
        t = now_ct.time()
        return time(8, 30) <= t <= time(15, 15)

    def _is_pre_market(self, now_ct: datetime) -> bool:
        t = now_ct.time()
        return time(18, 0) <= t <= time(23, 59) or time(0, 0) <= t < time(8, 30)

    def _is_post_market(self, now_ct: datetime) -> bool:
        t = now_ct.time()
        return time(15, 15) < t < time(16, 59)

    def get_upcoming_events(self, hours_ahead: int = 4) -> list[dict]:
        """Get events occurring in the next N hours."""
        upcoming = []
        now_et = datetime.now(ET)
        cutoff = now_et + timedelta(hours=hours_ahead)

        for event in self._custom_events:
            event_dt = event.get("datetime")
            if event_dt and now_et <= event_dt <= cutoff:
                upcoming.append(event)

        return upcoming
