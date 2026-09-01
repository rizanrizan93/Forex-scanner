from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import datetime, timedelta, timezone
from math import isfinite
from enum import StrEnum
from typing import Any, Iterable

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


@dataclass(frozen=True, slots=True)
class EconomicCalendarSnapshot:
    events: tuple[EconomicEvent, ...]
    fetched_at: datetime
    source: str
    source_url: str


class ForexFactoryCalendarProvider:
    """Fetch the public weekly calendar and fail closed if it is not current."""

    def __init__(
        self,
        transport: Any,
        *,
        url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        allowed_host: str = "nfs.faireconomy.media",
    ):
        self.transport = transport
        self.url = str(url)
        self.allowed_host = str(allowed_host)

    @staticmethod
    def _event_id(title: str, currency: str, scheduled_at: datetime) -> str:
        raw = f"{currency}|{scheduled_at.isoformat()}|{title}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def fetch(self, *, now: datetime | None = None) -> EconomicCalendarSnapshot:
        fetched_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
        response = self.transport.get(
            self.url,
            allowed_host=self.allowed_host,
            headers={"Accept": "application/json"},
        )
        if int(response.status_code) != 200:
            raise DataContractError(
                f"economic calendar HTTP status {response.status_code}"
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except Exception as exc:
            raise DataContractError("economic calendar JSON decode failed") from exc
        if not isinstance(payload, list) or not payload:
            raise DataContractError("economic calendar payload must be a non-empty list")

        impact_map = {
            "LOW": EventImpact.LOW,
            "MEDIUM": EventImpact.MEDIUM,
            "HIGH": EventImpact.HIGH,
        }
        events: list[EconomicEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            currency = str(item.get("country", "")).upper().strip()
            impact = impact_map.get(str(item.get("impact", "")).upper().strip())
            raw_date = str(item.get("date", "")).strip()
            if not title or len(currency) != 3 or impact is None or not raw_date:
                continue
            try:
                scheduled_at = datetime.fromisoformat(
                    raw_date.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if scheduled_at.tzinfo is None:
                continue
            scheduled_at = scheduled_at.astimezone(UTC)
            events.append(
                EconomicEvent(
                    event_id=self._event_id(title, currency, scheduled_at),
                    title=title,
                    currency=currency,
                    scheduled_at=scheduled_at,
                    impact=impact,
                    source="FOREX_FACTORY_WEEKLY",
                    source_url=self.url,
                )
            )

        if not events:
            raise DataContractError("economic calendar contained no usable events")
        events.sort(key=lambda event: (event.scheduled_at, event.currency, event.event_id))

        # A successfully fetched but cached/stale weekly export must never be
        # interpreted as an empty current calendar.
        freshness_window = timedelta(days=4)
        if not any(
            fetched_at - freshness_window <= event.scheduled_at <= fetched_at + freshness_window
            for event in events
        ):
            raise DataContractError(
                "economic calendar does not cover the current runtime week"
            )
        return EconomicCalendarSnapshot(
            events=tuple(events),
            fetched_at=fetched_at,
            source="FOREX_FACTORY_WEEKLY",
            source_url=self.url,
        )
