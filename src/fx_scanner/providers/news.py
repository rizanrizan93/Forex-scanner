from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from enum import StrEnum
from typing import Iterable

from ..exceptions import DataContractError

UTC = timezone.utc


class EventImpact(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event_id: str
    title: str
    currency: str
    scheduled_at: datetime
    impact: EventImpact
    source: str
    source_url: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.title.strip() or not self.source.strip():
            raise DataContractError("economic event identifiers are required")
        currency = self.currency.upper().strip()
        if len(currency) != 3:
            raise DataContractError("economic event currency must be three letters")
        object.__setattr__(self, "currency", currency)
        if self.scheduled_at.tzinfo is None:
            raise DataContractError("economic event timestamp must be timezone-aware")
        object.__setattr__(self, "scheduled_at", self.scheduled_at.astimezone(UTC))
        if not self.source_url.startswith("https://"):
            raise DataContractError("economic event source URL must use HTTPS")
        for name in ("actual", "forecast", "previous"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, bool) or not isfinite(float(value)):
                    raise DataContractError(f"economic event {name} must be finite numeric")
                object.__setattr__(self, name, float(value))


@dataclass(frozen=True, slots=True)
class NewsBlockDecision:
    blocked: bool
    relevant_events: tuple[EconomicEvent, ...]
    reason: str | None


def evaluate_news_block(
    *,
    now: datetime,
    currencies: Iterable[str],
    events: Iterable[EconomicEvent],
    pre_block_minutes: int = 30,
    post_block_minutes: int = 30,
    impacts: tuple[EventImpact, ...] = (EventImpact.HIGH,),
) -> NewsBlockDecision:
    if now.tzinfo is None:
        raise DataContractError("news-block now timestamp must be timezone-aware")
    if pre_block_minutes < 0 or post_block_minutes < 0:
        raise DataContractError("news block windows cannot be negative")

    now_utc = now.astimezone(UTC)
    wanted = {str(c).upper() for c in currencies}
    if any(len(c) != 3 for c in wanted):
        raise DataContractError("news-block currencies must be three-letter codes")

    relevant: list[EconomicEvent] = []
    pre = timedelta(minutes=pre_block_minutes)
    post = timedelta(minutes=post_block_minutes)
    for event in events:
        if event.currency not in wanted or event.impact not in impacts:
            continue
        if event.scheduled_at - pre <= now_utc <= event.scheduled_at + post:
            relevant.append(event)

    relevant.sort(key=lambda e: (e.scheduled_at, e.currency, e.event_id))
    if not relevant:
        return NewsBlockDecision(False, (), None)
    names = ",".join(f"{e.currency}:{e.event_id}" for e in relevant)
    return NewsBlockDecision(True, tuple(relevant), f"HIGH_IMPACT_WINDOW:{names}")
