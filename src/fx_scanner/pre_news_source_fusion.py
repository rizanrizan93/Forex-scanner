"""Provider-neutral fusion for pre-news economic-calendar consensus data.

This module intentionally separates *calendar consensus* from *official actuals*.
Investing.com and Myfxbook are secondary consensus providers; neither is treated
as authoritative by itself.  Official statistical releases may set
``authoritative_actual=True`` and win only for the post-release actual value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import median
import re
from typing import Iterable

SOURCE_INVESTING = "INVESTING_COM"
SOURCE_MYFXBOOK = "MYFXBOOK"
SOURCE_FOREX_FACTORY = "FOREX_FACTORY_WEEKLY"
SOURCE_SHOWMYTRADES = "SHOWMYTRADES"
SOURCE_HELIOUS = "HELIOUS"
SOURCE_TRADING_ECONOMICS = "TRADING_ECONOMICS"

# Count distinct forecast providers with numeric figures, never the
# count of downloaded schedules or duplicated rows.
SECONDARY_CONSENSUS_SOURCES = frozenset({
    SOURCE_INVESTING, SOURCE_MYFXBOOK, SOURCE_FOREX_FACTORY,
    SOURCE_SHOWMYTRADES, SOURCE_HELIOUS, SOURCE_TRADING_ECONOMICS,
})


def _clean_title(title: str) -> str:
    text = str(title or "").upper()
    text = text.replace("Y/Y", "YOY").replace("M/M", "MOM")
    text = text.replace("YEAR-ON-YEAR", "YOY").replace("MONTH-ON-MONTH", "MOM")
    text = re.sub(r"\([^)]*\)", lambda m: m.group(0) if re.search(r"YOY|MOM", m.group(0), re.I) else " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_event_key(title: str) -> str:
    """Map provider-specific event names to one canonical economic component.

    The function is deliberately conservative: unknown events receive a stable
    normalized key rather than being silently mapped to the wrong component.
    """
    text = _clean_title(title)
    core = (
        "CORE" in text
        or "EX FOOD ENERGY" in text
        or "EXCLUDING FOOD ENERGY" in text
        or "EX FOOD AND ENERGY" in text
        or "EXCLUDING FOOD AND ENERGY" in text
    )
    yoy = "YOY" in text
    mom = "MOM" in text

    is_cpi = (
        re.search(r"\bCPI\b", text) is not None
        or "CONSUMER PRICE INDEX" in text
        or "INFLATION RATE" in text
    )
    if is_cpi:
        prefix = "CORE_CPI" if core else "CPI"
        if mom:
            return prefix + "_MOM"
        if yoy:
            return prefix + "_YOY"
        return prefix

    is_ppi = (
        re.search(r"\bPPI\b", text) is not None
        or "PRODUCER PRICE INDEX" in text
        or "PRODUCER PRICE INFLATION" in text
    )
    if is_ppi:
        prefix = "CORE_PPI" if core else "PPI"
        if mom:
            return prefix + "_MOM"
        if yoy:
            return prefix + "_YOY"
        return prefix

    if "UNEMPLOYMENT RATE" in text:
        return "UNEMPLOYMENT_RATE"
    if "NONFARM" in text or "NON FARM" in text or "PAYROLL" in text:
        return "NONFARM_PAYROLLS"
    if "AVERAGE HOURLY EARNINGS" in text:
        if mom:
            return "AVERAGE_HOURLY_EARNINGS_MOM"
        if yoy:
            return "AVERAGE_HOURLY_EARNINGS_YOY"
        return "AVERAGE_HOURLY_EARNINGS"
    if "JOLTS" in text or "JOB OPENINGS" in text:
        return "JOLTS_JOB_OPENINGS"
    if "EMPLOYMENT COST INDEX" in text:
        return "ECI"
    if "PERSONAL CONSUMPTION EXPENDITURES" in text or re.search(r"\bPCE\b", text):
        prefix = "CORE_PCE" if core else "PCE"
        if mom:
            return prefix + "_MOM"
        if yoy:
            return prefix + "_YOY"
        return prefix
    if "GROSS DOMESTIC PRODUCT" in text or re.search(r"\bGDP\b", text):
        return "GDP"
    if "FOMC" in text or "FEDERAL FUNDS" in text or "INTEREST RATE DECISION" in text:
        return "FOMC"

    fallback = re.sub(r"\s+", "_", text).strip("_")
    return fallback or "UNKNOWN_EVENT"


@dataclass(frozen=True, slots=True)
class SourceQuote:
    source: str
    title: str
    currency: str
    scheduled_at: datetime
    forecast: float | None = None
    previous: float | None = None
    actual: float | None = None
    authoritative_actual: bool = False

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.title.strip():
            raise ValueError("source and title are required")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        object.__setattr__(self, "currency", self.currency.upper().strip())
        object.__setattr__(self, "scheduled_at", self.scheduled_at.astimezone(UTC))
        for field in ("forecast", "previous", "actual"):
            value = getattr(self, field)
            if value is not None:
                value = float(value)
                if not isfinite(value):
                    raise ValueError(f"{field} must be finite")
                object.__setattr__(self, field, value)

    @property
    def canonical_key(self) -> str:
        return canonical_event_key(self.title)


@dataclass(frozen=True, slots=True)
class FusedConsensus:
    canonical_key: str
    currency: str
    scheduled_at: datetime
    forecast: float | None
    previous: float | None
    actual: float | None
    sources: tuple[str, ...]
    source_agreement: str
    conflicts: tuple[str, ...]
    source_count: int
    forecast_source_count: int
    forecast_sources: tuple[str, ...]
    forecast_quotes: tuple[tuple[str, float, float | None], ...]
    rejected_quote_sources: tuple[str, ...]
    actual_source_count: int = 0
    actual_quotes: tuple[tuple[str, float], ...] = ()

    @property
    def source_conflict(self) -> bool:
        return bool(self.conflicts)


def _fuse_numeric(values: list[float], *, field: str) -> tuple[float | None, bool]:
    if not values:
        return None, False
    center = float(median(values))
    if len(values) == 1:
        return center, False
    spread = max(values) - min(values)
    # Calendar providers normally publish the same consensus.  A small tolerance
    # absorbs formatting/rounding differences without hiding a real divergence.
    tolerance = max(0.01, abs(center) * 0.02)
    return center, spread > tolerance

def _comparable_inflation_quote(key: str, forecast: float | None, previous: float | None) -> bool:
    """Do not compare CPI growth-rate percentages with CPI index levels.

    A provider may label both 'CPI m/m' and an index-level series with the same
    title. Values over 10 percentage points/month (or 30 points/year) are
    quarantined, not silently rescaled or interpreted as inflation forecasts.
    This affects forecast consensus only; official actuals are unaffected.
    """
    if key in {"CPI_MOM", "CORE_CPI_MOM"}:
        return all(abs(value) <= 10.0 for value in (forecast, previous) if value is not None)
    if key in {"CPI_YOY", "CORE_CPI_YOY"}:
        return all(abs(value) <= 30.0 for value in (forecast, previous) if value is not None)
    return True


def fuse_consensus(quotes: Iterable[SourceQuote]) -> FusedConsensus:
    rows = tuple(quotes)
    if not rows:
        raise ValueError("at least one source quote is required")

    keys = {row.canonical_key for row in rows}
    currencies = {row.currency for row in rows}
    if len(keys) != 1:
        raise ValueError(f"cannot fuse different events: {sorted(keys)}")
    if len(currencies) != 1:
        raise ValueError(f"cannot fuse different currencies: {sorted(currencies)}")

    times = [row.scheduled_at for row in rows]
    anchor = min(times)
    conflicts: list[str] = []
    if max(abs((value - anchor).total_seconds()) for value in times) > 120:
        conflicts.append("RELEASE_TIME_CONFLICT")

    # Forecast quorum must be based on DISTINCT providers with an actual
    # numeric forecast for this exact release component. A BLS/BEA schedule
    # row, duplicate provider row, or missing forecast must not count.
    forecasts_by_source: dict[str, SourceQuote] = {}
    previous_by_source: dict[str, SourceQuote] = {}
    rejected_quote_sources: set[str] = set()
    for row in rows:
        # A schedule-only row may legitimately carry an index-level previous
        # value. Quarantine ONLY provider rows claiming a numeric forecast.
        if row.forecast is not None and not _comparable_inflation_quote(
            row.canonical_key, row.forecast, row.previous
        ):
            rejected_quote_sources.add(row.source)
            continue
        if row.forecast is not None:
            prior = forecasts_by_source.get(row.source)
            if prior is None:
                forecasts_by_source[row.source] = row
            elif abs(prior.forecast - row.forecast) > 1e-9:
                conflicts.append("DUPLICATE_SOURCE_FORECAST_CONFLICT")
        # Compare previous observations only within the same numeric
        # forecast series. BLS/BEA official schedule observations can be index
        # levels (e.g. CPI index 338.9), not calendar CPI MoM percentages.
        # Their values remain in official release data but must not contaminate
        # the pre-release forecast-vs-previous consensus comparison.
        if row.previous is not None and row.forecast is not None:
            prior = previous_by_source.get(row.source)
            if prior is None:
                previous_by_source[row.source] = row
            elif abs(prior.previous - row.previous) > 1e-9:
                conflicts.append("DUPLICATE_SOURCE_PREVIOUS_CONFLICT")

    forecast, forecast_conflict = _fuse_numeric(
        [row.forecast for row in forecasts_by_source.values()], field="forecast"
    )
    previous, previous_conflict = _fuse_numeric(
        [row.previous for row in previous_by_source.values()], field="previous"
    )
    if forecast_conflict:
        conflicts.append("CONSENSUS_CONFLICT")
    if previous_conflict:
        conflicts.append("PREVIOUS_CONFLICT")
    forecast_sources = tuple(sorted(forecasts_by_source))
    forecast_quotes = tuple(
        (source, forecasts_by_source[source].forecast,
         forecasts_by_source[source].previous)
        for source in forecast_sources
    )

    actual_by_source: dict[str, float] = {}
    for row in rows:
        if row.actual is None:
            continue
        if not _comparable_inflation_quote(row.canonical_key, row.actual, None):
            rejected_quote_sources.add(row.source)
            continue
        prior_actual = actual_by_source.get(row.source)
        if prior_actual is not None and abs(prior_actual - row.actual) > 1e-9:
            conflicts.append("DUPLICATE_SOURCE_ACTUAL_CONFLICT")
        else:
            actual_by_source[row.source] = row.actual
    official_actuals = [
        row.actual
        for row in rows
        if row.authoritative_actual and row.actual is not None
    ]
    if official_actuals:
        actual, official_conflict = _fuse_numeric(official_actuals, field="actual")
        if official_conflict:
            conflicts.append("OFFICIAL_ACTUAL_CONFLICT")
    else:
        actual, actual_conflict = _fuse_numeric(
            list(actual_by_source.values()), field="actual"
        )
        if actual_conflict:
            conflicts.append("ACTUAL_CONFLICT")

    sources = tuple(sorted({row.source for row in rows}))
    agreement = (
        "SOURCE_CONFLICT"
        if conflicts
        else "MULTI_SOURCE_AGREE"
        if len(sources) >= 2
        else "SINGLE_SOURCE"
    )
    return FusedConsensus(
        canonical_key=next(iter(keys)),
        currency=next(iter(currencies)),
        scheduled_at=anchor,
        forecast=forecast,
        previous=previous,
        actual=actual,
        sources=sources,
        source_agreement=agreement,
        conflicts=tuple(conflicts),
        source_count=len(sources),
        forecast_source_count=len(forecast_sources),
        forecast_sources=forecast_sources,
        forecast_quotes=forecast_quotes,
        rejected_quote_sources=tuple(sorted(rejected_quote_sources)),
        actual_source_count=len(actual_by_source),
        actual_quotes=tuple(sorted(actual_by_source.items())),
    )


def group_and_fuse(quotes: Iterable[SourceQuote]) -> tuple[FusedConsensus, ...]:
    """Fuse equivalent provider rows without collapsing distinct CPI components."""
    groups: dict[tuple[str, str, int], list[SourceQuote]] = {}
    for row in quotes:
        # 5-minute release bucket only groups provider clock formatting; canonical
        # event key keeps headline/core and MoM/YoY components independent.
        bucket = int(row.scheduled_at.timestamp() // 300)
        groups.setdefault((row.currency, row.canonical_key, bucket), []).append(row)
    fused = [fuse_consensus(group) for group in groups.values()]
    return tuple(sorted(fused, key=lambda row: (row.scheduled_at, row.canonical_key)))
