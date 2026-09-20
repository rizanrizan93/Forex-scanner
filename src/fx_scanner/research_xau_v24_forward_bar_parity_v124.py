from __future__ import annotations

"""Read-only forward-data parity audit for the frozen XAU V24 champion.

The historical V20/V24 research constructed H1 and D1 context from M15 bars.
The forward adapter currently reads broker-native H1/D1 bars. This diagnostic
compares the two representations on the same cTrader DEMO feed before we claim
that forward signal semantics are exact.

No orders, signal writes, strategy mutation, or production influence occur here.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc

UTC = timezone.utc
SYMBOL = "XAUUSD"
RESEARCH_VERSION = "XAU_V24_FORWARD_BAR_PARITY_V124"
ARTIFACT_CONTRACT = "XAU_V24_FORWARD_BAR_PARITY_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False
M15_WINDOW_DAYS = 48
M15_COUNT = 6000
H1_COUNT = 1600
D1_COUNT = 120


@dataclass(frozen=True, slots=True)
class Ohlc:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


def _aggregate_h1(rows: Sequence[Bar]) -> tuple[Ohlc, ...]:
    buckets: dict[datetime, list[Bar]] = {}
    for row in sorted(rows, key=lambda x: ensure_utc(x.timestamp)):
        stamp = ensure_utc(row.timestamp)
        key = stamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(row)
    out: list[Ohlc] = []
    for stamp in sorted(buckets):
        group = sorted(buckets[stamp], key=lambda x: ensure_utc(x.timestamp))
        if len(group) != 4:
            continue
        minutes = [ensure_utc(x.timestamp).minute for x in group]
        if minutes != [0, 15, 30, 45]:
            continue
        out.append(
            Ohlc(
                timestamp=stamp,
                open=float(group[0].open),
                high=max(float(x.high) for x in group),
                low=min(float(x.low) for x in group),
                close=float(group[-1].close),
            )
        )
    return tuple(out)


def _aggregate_d1(rows: Sequence[Bar]) -> dict[date, Ohlc]:
    buckets: dict[date, list[Bar]] = {}
    for row in sorted(rows, key=lambda x: ensure_utc(x.timestamp)):
        stamp = ensure_utc(row.timestamp)
        buckets.setdefault(stamp.date(), []).append(row)
    out: dict[date, Ohlc] = {}
    for day in sorted(buckets):
        group = sorted(buckets[day], key=lambda x: ensure_utc(x.timestamp))
        out[day] = Ohlc(
            timestamp=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            open=float(group[0].open),
            high=max(float(x.high) for x in group),
            low=min(float(x.low) for x in group),
            close=float(group[-1].close),
        )
    return out


def _bar_ohlc(row: Bar) -> Ohlc:
    return Ohlc(
        timestamp=ensure_utc(row.timestamp),
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
    )


def _diff(a: Ohlc, b: Ohlc) -> dict[str, float]:
    return {
        "open": abs(a.open - b.open),
        "high": abs(a.high - b.high),
        "low": abs(a.low - b.low),
        "close": abs(a.close - b.close),
    }


def _summarize_diffs(values: Iterable[dict[str, float]]) -> dict[str, object]:
    rows = tuple(values)
    if not rows:
        return {"count": 0, "max": None, "median": None}
    keys = ("open", "high", "low", "close")
    return {
        "count": len(rows),
        "max": {key: max(row[key] for row in rows) for key in keys},
        "median": {key: median(row[key] for row in rows) for key in keys},
    }


def compare_h1(m15: Sequence[Bar], broker_h1: Sequence[Bar]) -> dict[str, object]:
    aggregated = {row.timestamp: row for row in _aggregate_h1(m15)}
    native = {ensure_utc(row.timestamp): _bar_ohlc(row) for row in broker_h1}
    common = sorted(set(aggregated) & set(native))
    diffs = [_diff(aggregated[key], native[key]) for key in common]
    return {
        "aggregated_rows": len(aggregated),
        "broker_rows": len(native),
        "overlap_rows": len(common),
        "overlap_fraction_of_aggregated": (
            len(common) / len(aggregated) if aggregated else 0.0
        ),
        "diffs": _summarize_diffs(diffs),
        "latest_aggregated_at": max(aggregated).isoformat() if aggregated else None,
        "latest_broker_at": max(native).isoformat() if native else None,
    }


def compare_d1(m15: Sequence[Bar], broker_d1: Sequence[Bar]) -> dict[str, object]:
    aggregated = _aggregate_d1(m15)
    native_by_day = {
        ensure_utc(row.timestamp).date(): _bar_ohlc(row)
        for row in broker_d1
    }
    comparisons: dict[str, object] = {}
    for shift in (-1, 0, 1):
        diffs: list[dict[str, float]] = []
        matches = 0
        for day, agg in aggregated.items():
            native = native_by_day.get(day + timedelta(days=shift))
            if native is None:
                continue
            matches += 1
            diffs.append(_diff(agg, native))
        comparisons[str(shift)] = {
            "date_shift_days": shift,
            "overlap_rows": matches,
            "overlap_fraction_of_aggregated": (
                matches / len(aggregated) if aggregated else 0.0
            ),
            "diffs": _summarize_diffs(diffs),
        }
    return {
        "aggregated_rows": len(aggregated),
        "broker_rows": len(native_by_day),
        "alignments": comparisons,
        "aggregated_dates": (
            [min(aggregated).isoformat(), max(aggregated).isoformat()]
            if aggregated else None
        ),
        "broker_dates": (
            [min(native_by_day).isoformat(), max(native_by_day).isoformat()]
            if native_by_day else None
        ),
        "broker_timestamp_hours_utc": sorted(
            {ensure_utc(row.timestamp).hour for row in broker_d1}
        ),
    }


def _json_safe_bar(row: Bar | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "timestamp": ensure_utc(row.timestamp).isoformat(),
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V124_DEMO_FEED_REQUIRED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        start = now - timedelta(days=M15_WINDOW_DAYS)
        m15 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=start,
                to_time=now,
                count=M15_COUNT,
            )
        )
        h1 = tuple(
            feed.historical_bars(
                SYMBOL,
                "H1",
                from_time=start,
                to_time=now,
                count=H1_COUNT,
            )
        )
        d1 = tuple(
            feed.historical_bars(
                SYMBOL,
                "D1",
                from_time=now - timedelta(days=D1_COUNT + 30),
                to_time=now,
                count=D1_COUNT,
            )
        )
    finally:
        feed.close()

    payload = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "symbol": SYMBOL,
        "captured_at": now.isoformat(),
        "m15": {
            "rows": len(m15),
            "first": _json_safe_bar(m15[0] if m15 else None),
            "last": _json_safe_bar(m15[-1] if m15 else None),
        },
        "h1": compare_h1(m15, h1),
        "d1": compare_d1(m15, d1),
    }

    output = Path(
        os.getenv(
            "V124_PARITY_OUTPUT",
            "artifacts/xau-v24-forward-bar-parity-v124.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    h1_summary = payload["h1"]
    d1_summary = payload["d1"]
    print(
        "V124_H1_PARITY "
        f"m15_rows={len(m15)} broker_h1_rows={len(h1)} "
        f"overlap={h1_summary['overlap_rows']} "
        f"fraction={h1_summary['overlap_fraction_of_aggregated']:.6f} "
        f"max_diff={h1_summary['diffs']['max']}"
    )
    print(
        "V124_D1_PARITY "
        f"m15_rows={len(m15)} broker_d1_rows={len(d1)} "
        f"timestamp_hours={d1_summary['broker_timestamp_hours_utc']} "
        f"alignments={json.dumps(d1_summary['alignments'], sort_keys=True)}"
    )
    print(f"V124_ARTIFACT path={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
