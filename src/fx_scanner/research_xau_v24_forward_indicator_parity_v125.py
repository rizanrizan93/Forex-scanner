from __future__ import annotations

"""Read-only V125 fidelity audit for XAU V24 forward indicator warm-up.

V124 proved cTrader H1 OHLC is exactly equal to M15 aggregation and exposed the
broker-native D1 session mismatch. V125 asks the next question: do the bounded
forward windows used for EMA/ADX/ATR materially differ from a much longer
history, and does the 1,100-calendar-day UTC-D1 bootstrap converge to the
available long-history recurrence?

This module is SHADOW_ONLY. It writes only a JSON artifact and never writes
signals or orders.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from .demo_xau_v24_champion_candidate_producer import _indicator_series
from .demo_xau_v24_utc_d1_context import (
    H1_CHUNK_COUNT,
    H1_CHUNK_DAYS,
    aggregate_h1_to_utc_days,
    context_from_daily,
)
from .exceptions import CollectorUnavailable
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc

UTC = timezone.utc
SYMBOL = "XAUUSD"
RESEARCH_VERSION = "XAU_V24_FORWARD_INDICATOR_PARITY_V125"
ARTIFACT_CONTRACT = "XAU_V24_FORWARD_INDICATOR_PARITY_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False

FORWARD_H1_BARS = 180
REFERENCE_H1_BARS = 1600
FORWARD_M15_BARS = 360
REFERENCE_M15_BARS = 5999
D1_FORWARD_BOOTSTRAP_DAYS = 1100
D1_REFERENCE_CALENDAR_DAYS = 5400
COMPARE_TAIL = 100
D1_COMPARE_TARGETS = 180


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _summary(values: Sequence[float]) -> dict[str, Any]:
    rows = [abs(float(x)) for x in values if isfinite(float(x))]
    if not rows:
        return {"count": 0, "max_abs": None, "median_abs": None}
    return {
        "count": len(rows),
        "max_abs": max(rows),
        "median_abs": median(rows),
    }


def _compare_indicator_tail(
    long_rows: Sequence[Bar],
    *,
    short_count: int,
    tail_count: int,
    fields: Sequence[str],
) -> dict[str, Any]:
    long_values = tuple(sorted(long_rows, key=lambda x: ensure_utc(x.timestamp)))
    short_values = long_values[-int(short_count):]
    long_ind = _indicator_series(long_values)
    short_ind = _indicator_series(short_values)
    tail = min(int(tail_count), len(short_values))
    output: dict[str, Any] = {
        "long_rows": len(long_values),
        "short_rows": len(short_values),
        "tail_rows": tail,
        "fields": {},
    }
    for field in fields:
        diffs: list[float] = []
        pairs = 0
        for offset in range(1, tail + 1):
            long_raw = long_ind[field][-offset]
            short_raw = short_ind[field][-offset]
            a = _finite(long_raw)
            b = _finite(short_raw)
            if a is None or b is None:
                continue
            pairs += 1
            diffs.append(b - a)
        output["fields"][field] = {
            "paired": pairs,
            **_summary(diffs),
            "latest_long": _finite(long_ind[field][-1]) if long_values else None,
            "latest_short": _finite(short_ind[field][-1]) if short_values else None,
        }
    return output


def _bias_at(rows: Sequence[Bar], indicators: dict[str, Sequence[float | None]], index: int, adx_min: float) -> str | None:
    values = (
        indicators["ema20"][index],
        indicators["ema50"][index],
        indicators["adx"][index],
        indicators["plus_di"][index],
        indicators["minus_di"][index],
    )
    parsed = tuple(_finite(value) for value in values)
    if any(value is None for value in parsed):
        return None
    ema20, ema50, adx, plus_di, minus_di = (float(value) for value in parsed)
    if adx < float(adx_min):
        return None
    close = float(rows[index].close)
    long_ok = close > ema20 > ema50 and plus_di > minus_di
    short_ok = close < ema20 < ema50 and minus_di > plus_di
    if long_ok == short_ok:
        return None
    return "LONG" if long_ok else "SHORT"


def _compare_h1_bias(long_rows: Sequence[Bar], *, short_count: int, tail_count: int, adx_min: float) -> dict[str, Any]:
    long_values = tuple(sorted(long_rows, key=lambda x: ensure_utc(x.timestamp)))
    short_values = long_values[-int(short_count):]
    long_ind = _indicator_series(long_values)
    short_ind = _indicator_series(short_values)
    tail = min(int(tail_count), len(short_values))
    mismatches = 0
    paired = 0
    examples: list[dict[str, Any]] = []
    start_long = len(long_values) - len(short_values)
    for short_i in range(max(0, len(short_values) - tail), len(short_values)):
        long_i = start_long + short_i
        long_bias = _bias_at(long_values, long_ind, long_i, adx_min)
        short_bias = _bias_at(short_values, short_ind, short_i, adx_min)
        paired += 1
        if long_bias != short_bias:
            mismatches += 1
            if len(examples) < 12:
                examples.append(
                    {
                        "timestamp": ensure_utc(short_values[short_i].timestamp).isoformat(),
                        "long_bias": long_bias,
                        "short_bias": short_bias,
                        "long_adx": _finite(long_ind["adx"][long_i]),
                        "short_adx": _finite(short_ind["adx"][short_i]),
                    }
                )
    return {
        "adx_min": float(adx_min),
        "paired": paired,
        "mismatches": mismatches,
        "mismatch_fraction": mismatches / paired if paired else None,
        "examples": examples,
    }


def _fetch_recent(feed, timeframe: str, count: int, days: int, now: datetime) -> tuple[Bar, ...]:
    return tuple(
        feed.historical_bars(
            SYMBOL,
            timeframe,
            from_time=now - timedelta(days=int(days)),
            to_time=now,
            count=int(count),
        )
    )


def _d1_tail_warmup_comparison(
    daily,
    *,
    target_count: int = D1_COMPARE_TARGETS,
) -> dict[str, Any]:
    """Compare rolling 1,100-day D1 state to long-history state over recent targets."""
    days = [row.day for row in daily]
    candidates = days[-int(target_count):]
    rows: list[dict[str, Any]] = []
    for target_day in candidates:
        short_cutoff = target_day - timedelta(days=D1_FORWARD_BOOTSTRAP_DAYS)
        short_daily = tuple(
            row for row in daily
            if short_cutoff <= row.day < target_day
        )
        reference_daily = tuple(row for row in daily if row.day < target_day)
        if len(short_daily) < 200 or len(reference_daily) < 200:
            continue
        reference = context_from_daily(reference_daily, target_day=target_day)
        forward = context_from_daily(short_daily, target_day=target_day)
        rows.append(
            {
                "target_day": target_day.isoformat(),
                "direction_reference": reference.direction,
                "direction_forward": forward.direction,
                "direction_match": reference.direction == forward.direction,
                "ema200_abs_diff": abs(forward.ema200 - reference.ema200),
                "atr14_abs_diff": abs(forward.atr14 - reference.atr14),
                "ret60_abs_diff": abs(forward.ret60 - reference.ret60),
            }
        )

    mismatches = [row for row in rows if not row["direction_match"]]
    return {
        "targets_requested": int(target_count),
        "targets_compared": len(rows),
        "direction_mismatches": len(mismatches),
        "direction_mismatch_fraction": (
            len(mismatches) / len(rows) if rows else None
        ),
        "ema200_abs_diff": _summary([row["ema200_abs_diff"] for row in rows]),
        "atr14_abs_diff": _summary([row["atr14_abs_diff"] for row in rows]),
        "ret60_abs_diff": _summary([row["ret60_abs_diff"] for row in rows]),
        "mismatch_examples": mismatches[:12],
    }


def _fetch_available_h1_backwards(
    feed,
    *,
    start: datetime,
    end: datetime,
) -> tuple[Bar, ...]:
    """Discover available H1 history from newest to oldest for diagnostics.

    Production V24 deliberately fails closed when a required H1 chunk is
    unavailable. V125 is different: it is trying to discover how much older
    broker history exists. Start from the known-current end and stop after the
    first empty/unsupported older chunk once at least one valid chunk was seen.
    """
    if start >= end:
        return ()
    output: dict[datetime, Bar] = {}
    cursor_end = ensure_utc(end)
    lower = ensure_utc(start)
    saw_data = False
    while cursor_end > lower:
        cursor_start = max(lower, cursor_end - timedelta(days=H1_CHUNK_DAYS))
        try:
            rows = feed.historical_bars(
                SYMBOL,
                "H1",
                from_time=cursor_start,
                to_time=cursor_end,
                count=H1_CHUNK_COUNT,
            )
        except CollectorUnavailable:
            if saw_data:
                break
            cursor_end = cursor_start
            continue
        accepted = 0
        for row in rows:
            stamp = ensure_utc(row.timestamp)
            if cursor_start <= stamp < cursor_end:
                output[stamp] = row
                accepted += 1
        if accepted:
            saw_data = True
        elif saw_data:
            break
        cursor_end = cursor_start
    return tuple(output[key] for key in sorted(output))


def _d1_warmup_comparison(feed, *, now: datetime) -> dict[str, Any]:
    target_day = ensure_utc(now).date()
    target_start = datetime.combine(target_day, datetime.min.time(), tzinfo=UTC)
    long_start = target_start - timedelta(days=D1_REFERENCE_CALENDAR_DAYS)
    h1 = _fetch_available_h1_backwards(feed, start=long_start, end=target_start)
    daily = aggregate_h1_to_utc_days(h1, before_day=target_day)
    if len(daily) < 200:
        raise RuntimeError(f"V125_D1_REFERENCE_HISTORY_SHORT:{len(daily)}")

    short_cutoff = target_day - timedelta(days=D1_FORWARD_BOOTSTRAP_DAYS)
    short_daily = tuple(row for row in daily if row.day >= short_cutoff)
    if len(short_daily) < 200:
        raise RuntimeError(f"V125_D1_FORWARD_HISTORY_SHORT:{len(short_daily)}")

    reference = context_from_daily(daily, target_day=target_day)
    forward = context_from_daily(short_daily, target_day=target_day)
    return {
        "target_day": target_day.isoformat(),
        "reference_calendar_days_requested": D1_REFERENCE_CALENDAR_DAYS,
        "forward_calendar_days": D1_FORWARD_BOOTSTRAP_DAYS,
        "reference_daily_rows": len(daily),
        "forward_daily_rows": len(short_daily),
        "reference_seed_day": reference.seed_day.isoformat(),
        "forward_seed_day": forward.seed_day.isoformat(),
        "direction_reference": reference.direction,
        "direction_forward": forward.direction,
        "direction_match": reference.direction == forward.direction,
        "atr14_reference": reference.atr14,
        "atr14_forward": forward.atr14,
        "atr14_abs_diff": abs(forward.atr14 - reference.atr14),
        "atr14_relative_diff": (
            abs(forward.atr14 - reference.atr14) / abs(reference.atr14)
            if abs(reference.atr14) > 1e-12 else None
        ),
        "ema200_reference": reference.ema200,
        "ema200_forward": forward.ema200,
        "ema200_abs_diff": abs(forward.ema200 - reference.ema200),
        "ema200_relative_to_price": (
            abs(forward.ema200 - reference.ema200) / abs(reference.close)
            if abs(reference.close) > 1e-12 else None
        ),
        "ret60_reference": reference.ret60,
        "ret60_forward": forward.ret60,
        "ret60_abs_diff": abs(forward.ret60 - reference.ret60),
        "close_reference": reference.close,
        "close_forward": forward.close,
        "close_abs_diff": abs(forward.close - reference.close),
        "recent_target_parity": _d1_tail_warmup_comparison(
            daily,
            target_count=D1_COMPARE_TARGETS,
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V125_DEMO_FEED_REQUIRED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        h1 = _fetch_recent(feed, "H1", REFERENCE_H1_BARS, 90, now)
        m15 = _fetch_recent(feed, "M15", REFERENCE_M15_BARS, 75, now)
        d1_warmup = _d1_warmup_comparison(feed, now=now)
    finally:
        feed.close()

    h1_sorted = tuple(sorted(h1, key=lambda x: ensure_utc(x.timestamp)))
    m15_sorted = tuple(sorted(m15, key=lambda x: ensure_utc(x.timestamp)))
    payload = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "symbol": SYMBOL,
        "captured_at": now.isoformat(),
        "h1": {
            "indicator_parity": _compare_indicator_tail(
                h1_sorted,
                short_count=FORWARD_H1_BARS,
                tail_count=COMPARE_TAIL,
                fields=("ema20", "ema50", "atr", "plus_di", "minus_di", "adx"),
            ),
            "bias_adx12": _compare_h1_bias(
                h1_sorted,
                short_count=FORWARD_H1_BARS,
                tail_count=COMPARE_TAIL,
                adx_min=12.0,
            ),
            "bias_adx15": _compare_h1_bias(
                h1_sorted,
                short_count=FORWARD_H1_BARS,
                tail_count=COMPARE_TAIL,
                adx_min=15.0,
            ),
        },
        "m15": {
            "indicator_parity": _compare_indicator_tail(
                m15_sorted,
                short_count=FORWARD_M15_BARS,
                tail_count=COMPARE_TAIL,
                fields=("atr",),
            ),
        },
        "d1_warmup": d1_warmup,
        "note": (
            "This is a forward-fidelity diagnostic. It does not retune V24 and "
            "does not authorize any execution change."
        ),
    }

    output = Path(os.getenv("V125_OUTPUT", "artifacts/xau-v24-forward-indicator-parity-v125.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    h1p = payload["h1"]["indicator_parity"]
    m15p = payload["m15"]["indicator_parity"]
    d1p = payload["d1_warmup"]
    print(
        "V125_H1_WARMUP "
        f"long_rows={h1p['long_rows']} short_rows={h1p['short_rows']} "
        f"ema20_max={h1p['fields']['ema20']['max_abs']} "
        f"ema50_max={h1p['fields']['ema50']['max_abs']} "
        f"adx_max={h1p['fields']['adx']['max_abs']} "
        f"bias12_mismatch={payload['h1']['bias_adx12']['mismatches']}/"
        f"{payload['h1']['bias_adx12']['paired']} "
        f"bias15_mismatch={payload['h1']['bias_adx15']['mismatches']}/"
        f"{payload['h1']['bias_adx15']['paired']}"
    )
    print(
        "V125_M15_WARMUP "
        f"long_rows={m15p['long_rows']} short_rows={m15p['short_rows']} "
        f"atr_max={m15p['fields']['atr']['max_abs']}"
    )
    print(
        "V125_D1_WARMUP "
        f"reference_rows={d1p['reference_daily_rows']} "
        f"forward_rows={d1p['forward_daily_rows']} "
        f"direction_match={int(bool(d1p['direction_match']))} "
        f"ema_abs_diff={d1p['ema200_abs_diff']} "
        f"atr_abs_diff={d1p['atr14_abs_diff']} "
        f"ret60_abs_diff={d1p['ret60_abs_diff']} "
        f"recent_direction_mismatch={d1p['recent_target_parity']['direction_mismatches']}/"
        f"{d1p['recent_target_parity']['targets_compared']}"
    )
    print(f"V125_ARTIFACT path={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
