from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Iterable, Sequence

RESEARCH_VERSION = "XAU_EVENT_REACTION_ATLAS_V193"
ARTIFACT_CONTRACT = "XAU_EVENT_REACTION_ATLAS_V193_1"

EVENT_CLUSTER_SECONDS = 90
MIN_SEGMENT_SAMPLES = 30


@dataclass(frozen=True, slots=True)
class HistoricalEvent:
    event_id: str
    scheduled_at: datetime
    title: str
    family: str
    impact: str
    source: str
    source_tier: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None:
            raise ValueError("historical event timestamp must be timezone-aware")
        object.__setattr__(self, "scheduled_at", self.scheduled_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class EventCluster:
    cluster_id: str
    scheduled_at: datetime
    events: tuple[HistoricalEvent, ...]
    families: tuple[str, ...]
    impact: str
    attribution: str


def classify_event_family(title: str) -> str:
    text = " ".join(str(title).upper().split())
    if "NON-FARM" in text or "NONFARM" in text or "EMPLOYMENT SITUATION" in text:
        return "NFP_EMPLOYMENT"
    if "UNEMPLOYMENT RATE" in text:
        return "UNEMPLOYMENT_RATE"
    if "UNEMPLOYMENT CLAIMS" in text or "JOBLESS CLAIMS" in text or "UI WEEKLY CLAIMS" in text:
        return "JOBLESS_CLAIMS"
    if "CONSUMER PRICE INDEX" in text or "CORE CPI" in text or text.startswith("CPI"):
        return "CPI"
    if "PRODUCER PRICE INDEX" in text or "CORE PPI" in text or text.startswith("PPI"):
        return "PPI"
    if "PERSONAL CONSUMPTION" in text or "PCE PRICE" in text or "PERSONAL INCOME AND OUTLAYS" in text:
        return "PCE"
    if "GROSS DOMESTIC PRODUCT" in text or text.startswith("GDP"):
        return "GDP"
    if "RETAIL SALES" in text:
        return "RETAIL_SALES"
    if "DURABLE GOODS" in text:
        return "DURABLE_GOODS"
    if "ISM" in text and ("MANUFACTUR" in text or "SERVICES" in text):
        return "ISM"
    if "JOLTS" in text or "JOB OPENINGS" in text:
        return "JOLTS"
    if "FOMC" in text and ("STATEMENT" in text or "RATE" in text or "FEDERAL FUNDS" in text):
        return "FOMC_DECISION"
    if ("FED" in text or "FOMC MEMBER" in text) and ("SPEAK" in text or "SPEECH" in text):
        return "FED_SPEECH"
    if "CURRENT ACCOUNT" in text or "INTERNATIONAL TRANSACTIONS" in text:
        return "CURRENT_ACCOUNT"
    if "TRADE BALANCE" in text or "INTERNATIONAL TRADE" in text:
        return "TRADE"
    return "OTHER_USD"


def parse_release_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if isfinite(parsed) else None

    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "NA", "null", "None"}:
        return None

    multiplier = 1.0
    suffix = text[-1:].upper()
    if suffix == "K":
        multiplier = 1_000.0
        text = text[:-1]
    elif suffix == "M":
        multiplier = 1_000_000.0
        text = text[:-1]
    elif suffix == "B":
        multiplier = 1_000_000_000.0
        text = text[:-1]
    elif suffix == "T":
        multiplier = 1_000_000_000_000.0
        text = text[:-1]

    if text.endswith("%"):
        text = text[:-1]
        multiplier *= 0.01

    text = text.strip()
    if text.startswith("<") or text.startswith(">"):
        text = text[1:].strip()
    try:
        parsed = float(text) * multiplier
    except ValueError:
        return None
    return parsed if isfinite(parsed) else None


def _impact_rank(value: str) -> int:
    text = str(value).upper()
    if "HIGH" in text:
        return 3
    if "MEDIUM" in text:
        return 2
    if "LOW" in text:
        return 1
    return 0


def cluster_events(
    events: Iterable[HistoricalEvent],
    *,
    tolerance_seconds: int = EVENT_CLUSTER_SECONDS,
) -> tuple[EventCluster, ...]:
    ordered = sorted(events, key=lambda item: (item.scheduled_at, item.event_id))
    if not ordered:
        return ()

    groups: list[list[HistoricalEvent]] = []
    current: list[HistoricalEvent] = [ordered[0]]
    anchor = ordered[0].scheduled_at
    for event in ordered[1:]:
        if abs((event.scheduled_at - anchor).total_seconds()) <= tolerance_seconds:
            current.append(event)
            continue
        groups.append(current)
        current = [event]
        anchor = event.scheduled_at
    groups.append(current)

    output: list[EventCluster] = []
    for items in groups:
        at = min(item.scheduled_at for item in items)
        families = tuple(sorted({item.family for item in items}))
        impact = max((item.impact for item in items), key=_impact_rank)
        attribution = "SINGLE_EVENT" if len(items) == 1 else "MULTI_EVENT_CLUSTER"
        raw = "|".join([at.isoformat(), *sorted(item.event_id for item in items)])
        import hashlib
        cluster_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        output.append(
            EventCluster(
                cluster_id=cluster_id,
                scheduled_at=at,
                events=tuple(items),
                families=families,
                impact=impact,
                attribution=attribution,
            )
        )
    return tuple(output)


def _ema(values: Sequence[float], length: int) -> float | None:
    if len(values) < length or length <= 0:
        return None
    alpha = 2.0 / (length + 1.0)
    value = sum(values[:length]) / length
    for item in values[length:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _true_ranges(bars: Sequence[Any]) -> list[float]:
    output: list[float] = []
    previous_close = None
    for bar in bars:
        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)
        if previous_close is None:
            output.append(max(0.0, high - low))
        else:
            output.append(
                max(
                    high - low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            )
        previous_close = close
    return output


def _infer_bar_interval(bars: Sequence[Any]) -> timedelta:
    ordered = sorted(
        {
            bar.timestamp.astimezone(UTC)
            for bar in bars
            if getattr(bar, "timestamp", None) is not None
        }
    )
    diffs = [
        (right - left).total_seconds()
        for left, right in zip(ordered, ordered[1:])
        if right > left
    ]
    if not diffs:
        return timedelta(minutes=1)
    seconds = float(median(diffs))
    if not isfinite(seconds) or seconds <= 0:
        return timedelta(minutes=1)
    return timedelta(seconds=seconds)


def _completed_bars(
    bars: Sequence[Any],
    *,
    end_at: datetime,
    interval: timedelta,
    start_at: datetime | None = None,
) -> tuple[Any, ...]:
    end_utc = end_at.astimezone(UTC)
    start_utc = None if start_at is None else start_at.astimezone(UTC)
    output = []
    for bar in bars:
        opened = bar.timestamp.astimezone(UTC)
        closed = opened + interval
        if closed > end_utc:
            continue
        if start_utc is not None and opened < start_utc:
            continue
        output.append(bar)
    return tuple(output)


def technical_context_before(
    bars: Sequence[Any],
    *,
    event_at: datetime,
) -> dict[str, Any]:
    interval = _infer_bar_interval(bars)
    before = _completed_bars(
        bars,
        end_at=event_at,
        interval=interval,
    )
    if not before:
        return {
            "state": "INSUFFICIENT_PRE_EVENT_HISTORY",
            "trend": "UNKNOWN",
            "atr14": None,
            "bar_interval_minutes": interval.total_seconds() / 60.0,
        }
    window = before[-240:]
    closes = [float(bar.close) for bar in window]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    trs = _true_ranges(window[-30:])
    atr14 = None if len(trs) < 14 else sum(trs[-14:]) / 14.0

    if None not in {ema20, ema50, ema200}:
        assert ema20 is not None and ema50 is not None and ema200 is not None
        if ema20 > ema50 > ema200:
            trend = "BULL_STACK"
        elif ema20 < ema50 < ema200:
            trend = "BEAR_STACK"
        else:
            trend = "MIXED_STACK"
    else:
        trend = "UNKNOWN"

    last_close = closes[-1]
    prior_12 = window[-12:] if len(window) >= 12 else window
    local_high = max(float(bar.high) for bar in prior_12)
    local_low = min(float(bar.low) for bar in prior_12)
    range_points = max(0.0, local_high - local_low)
    compression_atr = (
        None
        if atr14 is None or atr14 <= 0
        else range_points / atr14
    )
    return {
        "state": "AVAILABLE",
        "trend": trend,
        "last_close": last_close,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "atr14": atr14,
        "local_12bar_high": local_high,
        "local_12bar_low": local_low,
        "local_12bar_range_atr": compression_atr,
        "bar_interval_minutes": interval.total_seconds() / 60.0,
    }


def reaction_metrics_from_bars(
    bars: Sequence[Any],
    *,
    event_at: datetime,
) -> dict[str, Any] | None:
    ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
    if not ordered:
        return None
    interval = _infer_bar_interval(ordered)
    context = technical_context_before(ordered, event_at=event_at)
    atr = context.get("atr14")
    pre = _completed_bars(
        ordered,
        end_at=event_at,
        interval=interval,
    )
    if not pre:
        return None
    reference = pre[-1]
    p0 = float(reference.close)
    if p0 <= 0:
        return None

    responses: dict[str, Any] = {}
    for minutes in (5, 15, 30, 60):
        target = event_at + timedelta(minutes=minutes)
        completed = _completed_bars(
            ordered,
            start_at=event_at,
            end_at=target,
            interval=interval,
        )
        if not completed:
            responses[f"r{minutes}m_points"] = None
            responses[f"r{minutes}m_atr"] = None
            responses[f"mfe{minutes}m_atr"] = None
            responses[f"mae{minutes}m_atr"] = None
            continue

        post_bar = completed[-1]
        close = float(post_bar.close)
        change = close - p0
        high = max(float(bar.high) for bar in completed)
        low = min(float(bar.low) for bar in completed)
        responses[f"r{minutes}m_points"] = change
        responses[f"r{minutes}m_atr"] = (
            None if atr is None or atr <= 0 else change / float(atr)
        )
        responses[f"mfe{minutes}m_atr"] = (
            None if atr is None or atr <= 0 else (high - p0) / float(atr)
        )
        responses[f"mae{minutes}m_atr"] = (
            None if atr is None or atr <= 0 else (p0 - low) / float(atr)
        )

    return {
        "reference_price": p0,
        "pre_context": context,
        "bar_interval_minutes": interval.total_seconds() / 60.0,
        **responses,
    }


def _single_event_surprise(cluster: EventCluster) -> dict[str, Any]:
    if cluster.attribution != "SINGLE_EVENT":
        return {
            "available": False,
            "raw": None,
            "sign": "CLUSTERED",
        }
    event = cluster.events[0]
    if event.actual is None or event.forecast is None:
        return {
            "available": False,
            "raw": None,
            "sign": "MISSING",
        }
    raw = float(event.actual) - float(event.forecast)
    tolerance = max(1e-12, abs(float(event.forecast)) * 1e-9)
    sign = "IN_LINE" if abs(raw) <= tolerance else "POSITIVE" if raw > 0 else "NEGATIVE"
    return {
        "available": True,
        "raw": raw,
        "sign": sign,
    }


def reaction_for_cluster(
    cluster: EventCluster,
    bars: Sequence[Any],
) -> dict[str, Any] | None:
    metrics = reaction_metrics_from_bars(
        bars,
        event_at=cluster.scheduled_at,
    )
    if metrics is None:
        return None

    responses = {
        key: value
        for key, value in metrics.items()
        if key.startswith(("r5m_", "r15m_", "r30m_", "r60m_", "mfe", "mae"))
    }
    r15 = responses.get("r15m_atr")
    mfe15 = responses.get("mfe15m_atr")
    mae15 = responses.get("mae15m_atr")
    if r15 is None:
        direction15 = "UNKNOWN"
    elif r15 > 0:
        direction15 = "UP"
    elif r15 < 0:
        direction15 = "DOWN"
    else:
        direction15 = "FLAT"

    whipsaw15 = bool(
        mfe15 is not None
        and mae15 is not None
        and float(mfe15) >= 0.25
        and float(mae15) >= 0.25
    )

    return {
        "cluster_id": cluster.cluster_id,
        "scheduled_at": cluster.scheduled_at.isoformat(),
        "families": list(cluster.families),
        "family": cluster.families[0] if len(cluster.families) == 1 else "MULTI_EVENT_CLUSTER",
        "impact": cluster.impact,
        "attribution": cluster.attribution,
        "event_count": len(cluster.events),
        "source_tiers": sorted({item.source_tier for item in cluster.events}),
        "surprise": _single_event_surprise(cluster),
        "pre_context": metrics["pre_context"],
        "reference_price": metrics["reference_price"],
        "bar_interval_minutes": metrics["bar_interval_minutes"],
        "direction15m": direction15,
        "whipsaw15m": whipsaw15,
        "execution_influence": False,
        "execution_authority": False,
        **responses,
    }


def _quantile(values: Sequence[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(len(ordered) - 1, lower + 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _segment_stats(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    valid15 = [
        float(row["r15m_atr"])
        for row in rows
        if row.get("r15m_atr") is not None
    ]
    abs5 = [
        abs(float(row["r5m_atr"]))
        for row in rows
        if row.get("r5m_atr") is not None
    ]
    abs15 = [abs(value) for value in valid15]
    up = sum(value > 0 for value in valid15)
    down = sum(value < 0 for value in valid15)
    directional_total = up + down
    return {
        "n": len(rows),
        "n_directional_15m": directional_total,
        "historical_up_frequency_15m": (
            None if directional_total == 0 else up / directional_total
        ),
        "historical_down_frequency_15m": (
            None if directional_total == 0 else down / directional_total
        ),
        "median_r15m_atr": None if not valid15 else median(valid15),
        "median_abs_r5m_atr": None if not abs5 else median(abs5),
        "median_abs_r15m_atr": None if not abs15 else median(abs15),
        "p80_abs_r15m_atr": _quantile(abs15, 0.80),
        "p90_abs_r15m_atr": _quantile(abs15, 0.90),
        "whipsaw_15m_rate": (
            None
            if not rows
            else sum(bool(row.get("whipsaw15m")) for row in rows) / len(rows)
        ),
    }


def build_reaction_atlas(
    rows: Sequence[dict[str, Any]],
    *,
    minimum_samples: int = MIN_SEGMENT_SAMPLES,
) -> dict[str, Any]:
    clean = [dict(row) for row in rows]
    by_family: dict[str, list[dict[str, Any]]] = {}
    by_family_surprise: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_family_trend: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for row in clean:
        family = str(row.get("family") or "UNKNOWN")
        by_family.setdefault(family, []).append(row)

        surprise = str(dict(row.get("surprise") or {}).get("sign") or "MISSING")
        by_family_surprise.setdefault((family, surprise), []).append(row)

        trend = str(dict(row.get("pre_context") or {}).get("trend") or "UNKNOWN")
        by_family_trend.setdefault((family, trend), []).append(row)

    def serialize(
        groups: dict[Any, list[dict[str, Any]]],
        key_builder,
    ) -> list[dict[str, Any]]:
        output = []
        for key, group in sorted(groups.items(), key=lambda item: str(item[0])):
            stats = _segment_stats(group)
            if stats["n"] < minimum_samples:
                continue
            output.append({**key_builder(key), **stats})
        return output

    years = [
        datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00")).year
        for row in clean
        if row.get("scheduled_at")
    ]
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "sample_count": len(clean),
        "year_min": None if not years else min(years),
        "year_max": None if not years else max(years),
        "overall": _segment_stats(clean),
        "by_family": serialize(
            by_family,
            lambda key: {"family": key},
        ),
        "by_family_surprise": serialize(
            by_family_surprise,
            lambda key: {"family": key[0], "surprise_sign": key[1]},
        ),
        "by_family_pretrend": serialize(
            by_family_trend,
            lambda key: {"family": key[0], "pre_trend": key[1]},
        ),
        "interpretation": (
            "Historical conditional frequencies and ATR-normalized reactions only. "
            "They are not calibrated probabilities and cannot authorize execution."
        ),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
