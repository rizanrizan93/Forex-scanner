from __future__ import annotations

"""UTC-calendar D1 context for the frozen XAU V24 champion.

V20/V24 research built D1 bars by grouping M15 data on UTC calendar dates.
V124 proved cTrader H1 OHLC is exactly equal to four M15 bars, while broker D1
uses a 21:00 UTC session boundary. Therefore H1 can be used as a much cheaper
lossless source for reconstructing the research D1 semantics.

The context is cached once per UTC target date in broker_order_events. No new
schema is required and no order path consumes these cache events directly.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Any, Sequence

from .models import Bar, ensure_utc

UTC = timezone.utc
CONTEXT_EVENT_TYPE = "DEMO_XAU_V24_UTC_D1_CONTEXT"
CONTEXT_CODE = "XAU_V24_UTC_D1_CONTEXT_V1"
LOOKBACK_DAYS = 1100
H1_CHUNK_DAYS = 60
H1_CHUNK_COUNT = 1600
MIN_DAILY_ROWS = 200


@dataclass(frozen=True, slots=True)
class UtcD1Context:
    target_day: date
    signal_day: date
    direction: str | None
    atr14: float
    ema200: float
    ret60: float
    close: float
    closes_tail: tuple[float, ...]
    history_days: int
    seed_day: date
    source: str

    def payload(self) -> dict[str, Any]:
        return {
            "target_day": self.target_day.isoformat(),
            "signal_day": self.signal_day.isoformat(),
            "direction": self.direction,
            "atr14": self.atr14,
            "ema200": self.ema200,
            "ret60": self.ret60,
            "close": self.close,
            "closes_tail": list(self.closes_tail),
            "history_days": self.history_days,
            "seed_day": self.seed_day.isoformat(),
            "source": self.source,
            "research_semantics": "UTC_CALENDAR_D1_FROM_CTRADER_H1_PARITY_V124",
            "execution_influence": True,
            "environment": "DEMO",
            "live_execution_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class DailyOhlc:
    day: date
    open: float
    high: float
    low: float
    close: float


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def aggregate_h1_to_utc_days(rows: Sequence[Bar], *, before_day: date) -> tuple[DailyOhlc, ...]:
    grouped: dict[date, list[Bar]] = {}
    for row in sorted(rows, key=lambda x: ensure_utc(x.timestamp)):
        stamp = ensure_utc(row.timestamp)
        if stamp.date() >= before_day:
            continue
        grouped.setdefault(stamp.date(), []).append(row)
    out: list[DailyOhlc] = []
    for day in sorted(grouped):
        group = sorted(grouped[day], key=lambda x: ensure_utc(x.timestamp))
        out.append(
            DailyOhlc(
                day=day,
                open=float(group[0].open),
                high=max(float(x.high) for x in group),
                low=min(float(x.low) for x in group),
                close=float(group[-1].close),
            )
        )
    return tuple(out)


def _direction(close: float, ema200: float, ret60: float) -> str | None:
    if close > ema200 and ret60 > 0:
        return "LONG"
    if close < ema200 and ret60 < 0:
        return "SHORT"
    return None


def context_from_daily(rows: Sequence[DailyOhlc], *, target_day: date) -> UtcD1Context:
    daily = tuple(sorted((x for x in rows if x.day < target_day), key=lambda x: x.day))
    if len(daily) < MIN_DAILY_ROWS:
        raise ValueError(f"V24_UTC_D1_HISTORY_SHORT:{len(daily)}/{MIN_DAILY_ROWS}")

    ema = float(daily[0].close)
    atr = float(daily[0].high - daily[0].low)
    previous_close = float(daily[0].close)
    closes: list[float] = [previous_close]

    for row in daily[1:]:
        close = float(row.close)
        tr = max(
            float(row.high) - float(row.low),
            abs(float(row.high) - previous_close),
            abs(float(row.low) - previous_close),
        )
        ema = (2.0 / 201.0) * close + (199.0 / 201.0) * ema
        atr = (1.0 / 14.0) * tr + (13.0 / 14.0) * atr
        previous_close = close
        closes.append(close)

    if len(closes) < 61 or not isfinite(ema) or not isfinite(atr) or atr <= 0:
        raise ValueError("V24_UTC_D1_STATE_INVALID")
    ret60 = closes[-1] / closes[-61] - 1.0
    close = closes[-1]
    return UtcD1Context(
        target_day=target_day,
        signal_day=daily[-1].day,
        direction=_direction(close, ema, ret60),
        atr14=float(atr),
        ema200=float(ema),
        ret60=float(ret60),
        close=float(close),
        closes_tail=tuple(closes[-61:]),
        history_days=len(daily),
        seed_day=daily[0].day,
        source="FULL_H1_BOOTSTRAP",
    )


def advance_context(
    previous: UtcD1Context,
    rows: Sequence[DailyOhlc],
    *,
    target_day: date,
) -> UtcD1Context:
    daily = tuple(
        sorted(
            (
                x
                for x in rows
                if previous.signal_day < x.day < target_day
            ),
            key=lambda x: x.day,
        )
    )
    if not daily:
        return UtcD1Context(
            target_day=target_day,
            signal_day=previous.signal_day,
            direction=previous.direction,
            atr14=previous.atr14,
            ema200=previous.ema200,
            ret60=previous.ret60,
            close=previous.close,
            closes_tail=previous.closes_tail,
            history_days=previous.history_days,
            seed_day=previous.seed_day,
            source="CACHE_CARRY_FORWARD",
        )

    ema = float(previous.ema200)
    atr = float(previous.atr14)
    previous_close = float(previous.close)
    closes = list(previous.closes_tail)
    history_days = int(previous.history_days)

    for row in daily:
        close = float(row.close)
        tr = max(
            float(row.high) - float(row.low),
            abs(float(row.high) - previous_close),
            abs(float(row.low) - previous_close),
        )
        ema = (2.0 / 201.0) * close + (199.0 / 201.0) * ema
        atr = (1.0 / 14.0) * tr + (13.0 / 14.0) * atr
        previous_close = close
        closes.append(close)
        closes = closes[-61:]
        history_days += 1

    if len(closes) < 61 or atr <= 0:
        raise ValueError("V24_UTC_D1_ADVANCE_INVALID")
    ret60 = closes[-1] / closes[-61] - 1.0
    close = closes[-1]
    return UtcD1Context(
        target_day=target_day,
        signal_day=daily[-1].day,
        direction=_direction(close, ema, ret60),
        atr14=float(atr),
        ema200=float(ema),
        ret60=float(ret60),
        close=float(close),
        closes_tail=tuple(closes),
        history_days=history_days,
        seed_day=previous.seed_day,
        source="CACHE_INCREMENTAL_H1",
    )


def _parse_context(payload: dict[str, Any]) -> UtcD1Context | None:
    try:
        target_day = date.fromisoformat(str(payload["target_day"]))
        signal_day = date.fromisoformat(str(payload["signal_day"]))
        seed_day = date.fromisoformat(str(payload["seed_day"]))
        direction = payload.get("direction")
        if direction not in {None, "LONG", "SHORT"}:
            return None
        closes = tuple(float(x) for x in payload["closes_tail"])
        if len(closes) < 61:
            return None
        context = UtcD1Context(
            target_day=target_day,
            signal_day=signal_day,
            direction=direction,
            atr14=float(payload["atr14"]),
            ema200=float(payload["ema200"]),
            ret60=float(payload["ret60"]),
            close=float(payload["close"]),
            closes_tail=closes[-61:],
            history_days=int(payload["history_days"]),
            seed_day=seed_day,
            source=str(payload.get("source") or "CACHE"),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        context.atr14 <= 0
        or context.history_days < MIN_DAILY_ROWS
        or not all(
            isfinite(value)
            for value in (
                context.atr14,
                context.ema200,
                context.ret60,
                context.close,
            )
        )
    ):
        return None
    return context


def load_cached_contexts(store, *, account_id: str, limit: int = 16) -> tuple[UtcD1Context, ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,account_id,event_type,code,payload")
        .eq("account_id", str(account_id))
        .eq("event_type", CONTEXT_EVENT_TYPE)
        .eq("code", CONTEXT_CODE)
        .order("observed_at", desc=True)
        .limit(int(limit))
        .execute()
    )
    out: list[UtcD1Context] = []
    for row in response.data or []:
        context = _parse_context(dict(row.get("payload") or {}))
        if context is not None:
            out.append(context)
    return tuple(out)


def _fetch_h1(feed, *, start: datetime, end: datetime) -> tuple[Bar, ...]:
    if start >= end:
        return ()
    output: dict[datetime, Bar] = {}
    cursor = start
    while cursor < end:
        window_end = min(end, cursor + timedelta(days=H1_CHUNK_DAYS))
        rows = feed.historical_bars(
            "XAUUSD",
            "H1",
            from_time=cursor,
            to_time=window_end,
            count=H1_CHUNK_COUNT,
        )
        for row in rows:
            stamp = ensure_utc(row.timestamp)
            if start <= stamp < end:
                output[stamp] = row
        cursor = window_end
    return tuple(output[key] for key in sorted(output))


def _persist_context(store, *, account_id: str, context: UtcD1Context) -> None:
    key = f"v24-utc-d1:{context.target_day.isoformat()}"
    store.record_order_event(
        backend="CTRADER",
        account_id=str(account_id),
        signal_key=key,
        broker_order_id=key,
        event_type=CONTEXT_EVENT_TYPE,
        accepted=True,
        code=CONTEXT_CODE,
        message="XAU V24 UTC-calendar D1 context cached",
        payload=context.payload(),
    )


def load_or_build_context(
    *,
    store,
    feed,
    account_id: str,
    target_day: date,
) -> UtcD1Context:
    cached = load_cached_contexts(store, account_id=account_id, limit=24)
    exact = next((x for x in cached if x.target_day == target_day), None)
    if exact is not None:
        return exact

    prior = next(
        (
            x
            for x in sorted(cached, key=lambda c: c.target_day, reverse=True)
            if x.target_day < target_day
        ),
        None,
    )
    target_start = _day_start(target_day)

    if prior is not None:
        start = _day_start(prior.signal_day + timedelta(days=1))
        h1 = _fetch_h1(feed, start=start, end=target_start)
        daily = aggregate_h1_to_utc_days(h1, before_day=target_day)
        context = advance_context(prior, daily, target_day=target_day)
    else:
        start = target_start - timedelta(days=LOOKBACK_DAYS)
        h1 = _fetch_h1(feed, start=start, end=target_start)
        daily = aggregate_h1_to_utc_days(h1, before_day=target_day)
        context = context_from_daily(daily, target_day=target_day)

    _persist_context(store, account_id=account_id, context=context)
    return context
