from __future__ import annotations

"""V383 research-only adaptive C4 path reforecast replay.

Goal
----
Test the state machine requested for C4:

    NOW leg -> target main reversal zone
      -> if structural invalidation occurs first: invalidate, recompute, reforecast
      -> if target zone is touched first: measure expected reversal reaction

The frozen C4 selector is not retrained or modified. Only runtime path state is
recomputed from newly completed bars after each resolution event.

2025 is intended for configuration selection. 2026 is an untouched holdout.
No execution authority is produced by this module.
"""

import argparse
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from fx_scanner.models import Bar, ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import bars_from_frame, load_price_frame, resample_ohlc
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity

SCHEMA = "XAU_V383_ADAPTIVE_C4_REFORECAST_V1"
RULES = {"H4": "4h", "H1": "1h", "M15": "15min", "M5": "5min"}
TF_MINUTES = {"H4": 240, "H1": 60, "M15": 15, "M5": 5}
WINDOWS = {"H4": 400, "H1": 560, "M15": 256, "M5": 384}
MAX_LEG_HOURS = 24.0 * 30.0
REVERSAL_HOURS = {"H1": 12.0, "H4": 32.0}
REVERSAL_ATR = 0.50
MIN_WARMUP_H1 = 560


@dataclass(frozen=True)
class Config:
    name: str
    m15_lookback: int
    buffer_atr: float


CONFIGS = (
    Config("M15_LB8_B010", 8, 0.10),
    Config("M15_LB12_B010", 12, 0.10),
    Config("M15_LB16_B010", 16, 0.10),
    Config("M15_LB12_B020", 12, 0.20),
)


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _bar_cache(price: pd.DataFrame) -> tuple[dict[str, tuple[Bar, ...]], dict[str, list[datetime]], dict[str, pd.DataFrame]]:
    bars: dict[str, tuple[Bar, ...]] = {}
    completed: dict[str, list[datetime]] = {}
    frames: dict[str, pd.DataFrame] = {}
    for tf, rule in RULES.items():
        frame = resample_ohlc(price, rule)
        frames[tf] = frame
        rows = bars_from_frame(frame, tf)
        bars[tf] = rows
        delta = timedelta(minutes=TF_MINUTES[tf])
        completed[tf] = [ensure_utc(row.timestamp) + delta for row in rows]
    return bars, completed, frames


def _completed_bars(
    bars: dict[str, tuple[Bar, ...]],
    completed: dict[str, list[datetime]],
    tf: str,
    as_of: datetime,
) -> tuple[Bar, ...]:
    idx = bisect_right(completed[tf], ensure_utc(as_of))
    start = max(0, idx - WINDOWS[tf])
    return bars[tf][start:idx]


def _arrays(price: pd.DataFrame) -> dict[str, Any]:
    return {
        "timestamps": [ensure_utc(pd.Timestamp(x).to_pydatetime()) for x in price["timestamp"]],
        "high": price["high"].to_numpy(dtype=float, copy=False),
        "low": price["low"].to_numpy(dtype=float, copy=False),
        "close": price["close"].to_numpy(dtype=float, copy=False),
    }


def _price_before(arrays: dict[str, Any], as_of: datetime) -> float | None:
    idx = bisect_left(arrays["timestamps"], ensure_utc(as_of)) - 1
    return None if idx < 0 else float(arrays["close"][idx])


def _next_m15_close(completed: Sequence[datetime], after: datetime) -> datetime | None:
    idx = bisect_right(completed, ensure_utc(after))
    return None if idx >= len(completed) else ensure_utc(completed[idx])


def _forecast(
    *,
    as_of: datetime,
    arrays: dict[str, Any],
    bars: dict[str, tuple[Bar, ...]],
    completed: dict[str, list[datetime]],
) -> dict[str, Any] | None:
    px = _price_before(arrays, as_of)
    if px is None:
        return None
    h1 = _completed_bars(bars, completed, "H1", as_of)
    h4 = _completed_bars(bars, completed, "H4", as_of)
    m15 = _completed_bars(bars, completed, "M15", as_of)
    m5 = _completed_bars(bars, completed, "M5", as_of)
    if len(h1) < 80 or len(h4) < 40 or len(m15) < 32 or len(m5) < 32:
        return None
    result = evaluate_sd_liquidity(
        bars_h1=h1,
        bars_h4=h4,
        bars_m15=m15,
        bars_m5=m5,
        as_of=as_of,
        price_now=px,
    )
    leg = dict(result.get("current_leg_forecast") or {})
    zone = dict(result.get("main_reversal_zone") or result.get("decision_zone") or {})
    direction = str(leg.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None
    low = _safe_float(zone.get("low"))
    high = _safe_float(zone.get("high"))
    atr = _safe_float(zone.get("atr"))
    if low is None or high is None or atr is None or atr <= 0 or high <= low:
        return None
    return {
        "as_of": ensure_utc(as_of),
        "price_now": px,
        "direction": direction,
        "zone_id": zone.get("zone_id"),
        "timeframe": str(zone.get("timeframe") or ""),
        "zone_direction": str(zone.get("direction") or "").upper(),
        "zone_low": low,
        "zone_high": high,
        "atr": atr,
        "distance_atr": _safe_float(leg.get("distance_atr")),
        "path_rank": dict(zone.get("next_zone_path") or {}).get("path_rank"),
        "checkpoint": dict(leg.get("checkpoint") or {}),
        "engine_state": result.get("state"),
    }


def _invalidation_level(
    *,
    forecast: dict[str, Any],
    config: Config,
    m15_frame: pd.DataFrame,
    as_of: datetime,
) -> float | None:
    work = m15_frame.copy()
    work["completed_at"] = pd.to_datetime(work["timestamp"], utc=True) + pd.Timedelta(minutes=15)
    known = work[work["completed_at"] <= pd.Timestamp(ensure_utc(as_of))].tail(config.m15_lookback)
    if len(known) < max(4, config.m15_lookback // 2):
        return None
    atr = float(forecast["atr"])
    if forecast["direction"] == "LONG":
        return float(known["low"].min()) - config.buffer_atr * atr
    return float(known["high"].max()) + config.buffer_atr * atr


def _target_touch_event(arrays: dict[str, Any], forecast: dict[str, Any], end_at: datetime) -> datetime | None:
    start = bisect_left(arrays["timestamps"], forecast["as_of"])
    end = bisect_left(arrays["timestamps"], ensure_utc(end_at))
    if end <= start:
        return None
    lows = arrays["low"][start:end]
    highs = arrays["high"][start:end]
    hit = np.flatnonzero((lows <= forecast["zone_high"]) & (highs >= forecast["zone_low"]))
    if not len(hit):
        return None
    return arrays["timestamps"][start + int(hit[0])] + timedelta(minutes=1)


def _invalidation_event(
    *,
    forecast: dict[str, Any],
    invalidation: float | None,
    m15_frame: pd.DataFrame,
    end_at: datetime,
) -> datetime | None:
    if invalidation is None:
        return None
    work = m15_frame.copy()
    work["completed_at"] = pd.to_datetime(work["timestamp"], utc=True) + pd.Timedelta(minutes=15)
    future = work[
        (work["completed_at"] > pd.Timestamp(forecast["as_of"]))
        & (work["completed_at"] <= pd.Timestamp(ensure_utc(end_at)))
    ]
    if future.empty:
        return None
    if forecast["direction"] == "LONG":
        rows = future[future["close"] < invalidation]
    else:
        rows = future[future["close"] > invalidation]
    if rows.empty:
        return None
    return ensure_utc(pd.Timestamp(rows.iloc[0]["completed_at"]).to_pydatetime())


def _reversal_hit(arrays: dict[str, Any], forecast: dict[str, Any], touch_at: datetime) -> bool:
    tf = forecast["timeframe"]
    hours = float(REVERSAL_HOURS.get(tf, 24.0))
    start = bisect_left(arrays["timestamps"], ensure_utc(touch_at))
    end = bisect_left(arrays["timestamps"], ensure_utc(touch_at) + timedelta(hours=hours))
    end = min(end, len(arrays["timestamps"]))
    if end <= start:
        return False
    atr = float(forecast["atr"])
    if forecast["zone_direction"] == "SHORT":
        target = float(forecast["zone_low"]) - REVERSAL_ATR * atr
        return bool(np.any(arrays["low"][start:end] <= target))
    if forecast["zone_direction"] == "LONG":
        target = float(forecast["zone_high"]) + REVERSAL_ATR * atr
        return bool(np.any(arrays["high"][start:end] >= target))
    return False


def _run_config(
    *,
    year: int,
    config: Config,
    arrays: dict[str, Any],
    bars: dict[str, tuple[Bar, ...]],
    completed: dict[str, list[datetime]],
    frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    h1_times = [x for x in completed["H1"] if ensure_utc(x).year == year]
    if len(h1_times) < 50:
        return {"config": config.name, "episodes": [], "summary": {}}
    cursor = h1_times[min(MIN_WARMUP_H1 - 1, len(h1_times) - 1)] if len(h1_times) >= MIN_WARMUP_H1 else h1_times[40]
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    data_end = arrays["timestamps"][-1] + timedelta(minutes=1)
    hard_end = min(year_end, data_end)
    episodes: list[dict[str, Any]] = []
    prior_resolution: str | None = None
    prior_direction: str | None = None
    prior_invalidated_index: int | None = None
    loop_guard = 0

    while cursor < hard_end and loop_guard < 5000:
        loop_guard += 1
        forecast = _forecast(as_of=cursor, arrays=arrays, bars=bars, completed=completed)
        if forecast is None:
            nxt = _next_m15_close(completed["M15"], cursor)
            if nxt is None or nxt <= cursor:
                break
            cursor = nxt
            continue

        invalidation = _invalidation_level(
            forecast=forecast,
            config=config,
            m15_frame=frames["M15"],
            as_of=cursor,
        )
        end_at = min(hard_end, cursor + timedelta(hours=MAX_LEG_HOURS))
        touch_at = _target_touch_event(arrays, forecast, end_at)
        invalid_at = _invalidation_event(
            forecast=forecast,
            invalidation=invalidation,
            m15_frame=frames["M15"],
            end_at=end_at,
        )

        if touch_at is not None and (invalid_at is None or touch_at <= invalid_at):
            resolution = "TARGET_TOUCH"
            resolved_at = touch_at
            reversal = _reversal_hit(arrays, forecast, touch_at)
        elif invalid_at is not None:
            resolution = "INVALIDATED"
            resolved_at = invalid_at
            reversal = False
        else:
            resolution = "CENSORED"
            resolved_at = end_at
            reversal = False

        episode = {
            "index": len(episodes),
            "as_of": cursor.isoformat(),
            "resolved_at": resolved_at.isoformat(),
            "resolution": resolution,
            "direction": forecast["direction"],
            "zone_direction": forecast["zone_direction"],
            "target_zone_id": forecast["zone_id"],
            "target_timeframe": forecast["timeframe"],
            "target_low": forecast["zone_low"],
            "target_high": forecast["zone_high"],
            "distance_atr": forecast["distance_atr"],
            "path_rank": forecast["path_rank"],
            "invalidation": invalidation,
            "hours_to_resolution": max(0.0, (resolved_at - cursor).total_seconds() / 3600.0),
            "reversal_050_atr_after_touch": reversal,
            "previous_resolution": prior_resolution,
            "previous_direction": prior_direction,
            "direction_flipped": bool(prior_direction and prior_direction != forecast["direction"]),
            "is_reforecast_after_invalidation": prior_resolution == "INVALIDATED",
            "recovery_from_previous_invalidation": False,
        }
        episodes.append(episode)
        if prior_invalidated_index is not None:
            episodes[prior_invalidated_index]["next_reforecast_index"] = episode["index"]
            episodes[prior_invalidated_index]["next_reforecast_direction"] = forecast["direction"]
            if resolution == "TARGET_TOUCH":
                episodes[prior_invalidated_index]["recovery_from_invalidation"] = True
                episode["recovery_from_previous_invalidation"] = True
            else:
                episodes[prior_invalidated_index]["recovery_from_invalidation"] = False

        prior_resolution = resolution
        prior_direction = forecast["direction"]
        prior_invalidated_index = episode["index"] if resolution == "INVALIDATED" else None

        nxt = _next_m15_close(completed["M15"], resolved_at)
        if nxt is None or nxt <= cursor:
            break
        cursor = nxt

    touches = [r for r in episodes if r["resolution"] == "TARGET_TOUCH"]
    invalids = [r for r in episodes if r["resolution"] == "INVALIDATED"]
    recoverable = [r for r in invalids if "recovery_from_invalidation" in r]
    recovered = [r for r in recoverable if r.get("recovery_from_invalidation")]
    chains = [r for r in touches if r.get("reversal_050_atr_after_touch")]
    fast_invalids = [r for r in invalids if float(r.get("hours_to_resolution") or 0.0) <= 8.0]
    reforecasts = [r for r in episodes if r.get("is_reforecast_after_invalidation")]
    flips = [r for r in reforecasts if r.get("direction_flipped")]
    total = len(episodes)

    summary = {
        "episodes": total,
        "target_touches": len(touches),
        "invalidations": len(invalids),
        "censored": sum(r["resolution"] == "CENSORED" for r in episodes),
        "current_leg_target_rate": None if not total else len(touches) / total,
        "invalidation_rate": None if not total else len(invalids) / total,
        "reforecast_recovery_n": len(recoverable),
        "reforecast_recovery_rate": None if not recoverable else len(recovered) / len(recoverable),
        "direction_flip_after_invalidation_rate": None if not reforecasts else len(flips) / len(reforecasts),
        "chain_touch_plus_reversal_rate": None if not total else len(chains) / total,
        "reversal_after_touch_rate": None if not touches else len(chains) / len(touches),
        "fast_invalidation_le_8h_rate": None if not invalids else len(fast_invalids) / len(invalids),
        "median_hours_to_target": None if not touches else float(np.median([r["hours_to_resolution"] for r in touches])),
        "median_hours_to_invalidation": None if not invalids else float(np.median([r["hours_to_resolution"] for r in invalids])),
        "resolution_counts": dict(Counter(r["resolution"] for r in episodes)),
    }
    return {"config": config.name, "parameters": {"m15_lookback": config.m15_lookback, "buffer_atr": config.buffer_atr}, "summary": summary, "episodes": episodes}


def run(year: int, csv_path: Path, output: Path) -> dict[str, Any]:
    price = load_price_frame(csv_path)
    arrays = _arrays(price)
    bars, completed, frames = _bar_cache(price)
    results = [
        _run_config(
            year=year,
            config=config,
            arrays=arrays,
            bars=bars,
            completed=completed,
            frames=frames,
        )
        for config in CONFIGS
    ]
    payload = {
        "schema": SCHEMA,
        "year": year,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "source": "HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY",
        "causal": True,
        "execution_authority": False,
        "champion_selector": "V376_C4_NEXT_ZONE_PATH_FROZEN",
        "purpose": "Test adaptive invalidate -> recompute -> reforecast state machine without retraining C4.",
        "configs": results,
        "limitations": [
            "Research replay uses public M1 OHLC and completed M15 structural invalidation; it is not bid/ask tick execution replay.",
            "The adaptive layer changes path state only; frozen C4 zone-selection parameters are unchanged.",
            "2025 should be used for configuration selection and 2026 only as holdout validation.",
            "Trade PnL is not inferred from these path metrics; execution gates, costs, SL/TP, and news are outside V383.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("V383_SUMMARY=" + json.dumps({r["config"]: r["summary"] for r in results}, sort_keys=True))
    print(f"OUTPUT={output}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.year, args.csv, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
