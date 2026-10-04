from __future__ import annotations

"""V383 research-only adaptive C4 path reforecast replay.

State machine under test:
  CURRENT LEG -> TARGET ZONE
    * target touched -> measure >=0.50 ATR reversal from that zone
    * structural invalidation -> recompute immediately from fresh completed bars
    * periodic structural refresh -> replace forecast if C4 zone/path changes
    * zone lifecycle expiry -> abandon stale target and recompute

Frozen V376 C4 parameters are never retrained here. 2025 is configuration
selection; 2026 is holdout. No execution authority is produced.
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
from fx_scanner.xau_sd_liquidity_engine_v342 import TF_PARAMS, evaluate_sd_liquidity

SCHEMA = "XAU_V383_ADAPTIVE_C4_REFORECAST_V2"
RULES = {"H4": "4h", "H1": "1h", "M15": "15min", "M5": "5min"}
TF_MINUTES = {"H4": 240, "H1": 60, "M15": 15, "M5": 5}
WINDOWS = {"H4": 400, "H1": 560, "M15": 256, "M5": 384}
MAX_LEG_HOURS = 24.0 * 30.0
REFRESH_HOURS = 4.0
REVERSAL_HOURS = {"H1": 12.0, "H4": 32.0}
REVERSAL_ATR = 0.50


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


def _iso(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


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


def _completed_bars(bars: dict[str, tuple[Bar, ...]], completed: dict[str, list[datetime]], tf: str, as_of: datetime) -> tuple[Bar, ...]:
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


def _next_completed(times: Sequence[datetime], after: datetime) -> datetime | None:
    idx = bisect_right(times, ensure_utc(after))
    return None if idx >= len(times) else ensure_utc(times[idx])


def _forecast(*, as_of: datetime, arrays: dict[str, Any], bars: dict[str, tuple[Bar, ...]], completed: dict[str, list[datetime]]) -> dict[str, Any] | None:
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
        bars_h1=h1, bars_h4=h4, bars_m15=m15, bars_m5=m5,
        as_of=as_of, price_now=px,
    )
    leg = dict(result.get("current_leg_forecast") or {})
    zone = dict(result.get("main_reversal_zone") or result.get("decision_zone") or {})
    direction = str(leg.get("direction") or "").upper()
    low, high, atr = (_safe_float(zone.get("low")), _safe_float(zone.get("high")), _safe_float(zone.get("atr")))
    if direction not in {"LONG", "SHORT"} or low is None or high is None or atr is None or atr <= 0 or high <= low:
        return None
    return {
        "as_of": ensure_utc(as_of), "price_now": px, "direction": direction,
        "zone_id": str(zone.get("zone_id") or ""), "timeframe": str(zone.get("timeframe") or ""),
        "zone_direction": str(zone.get("direction") or "").upper(),
        "zone_low": low, "zone_high": high, "atr": atr,
        "zone_available_at": zone.get("available_at"),
        "distance_atr": _safe_float(leg.get("distance_atr")),
        "path_rank": dict(zone.get("next_zone_path") or {}).get("path_rank"),
    }


def _zone_expiry(forecast: dict[str, Any], fallback: datetime) -> datetime:
    available = _iso(forecast.get("zone_available_at"))
    lifecycle = _safe_float(dict(TF_PARAMS.get(str(forecast.get("timeframe") or "")) or {}).get("lifecycle_hours"))
    if available is None or lifecycle is None or lifecycle <= 0:
        return fallback
    return min(fallback, available + timedelta(hours=lifecycle))


def _invalidation_level(*, forecast: dict[str, Any], config: Config, m15_frame: pd.DataFrame, as_of: datetime) -> float | None:
    work = m15_frame.copy()
    work["completed_at"] = pd.to_datetime(work["timestamp"], utc=True) + pd.Timedelta(minutes=15)
    known = work[work["completed_at"] <= pd.Timestamp(ensure_utc(as_of))].tail(config.m15_lookback)
    if len(known) < max(4, config.m15_lookback // 2):
        return None
    if forecast["direction"] == "LONG":
        return float(known["low"].min()) - config.buffer_atr * float(forecast["atr"])
    return float(known["high"].max()) + config.buffer_atr * float(forecast["atr"])


def _target_touch(arrays: dict[str, Any], forecast: dict[str, Any], start_at: datetime, end_at: datetime) -> datetime | None:
    start = bisect_left(arrays["timestamps"], ensure_utc(start_at))
    end = bisect_left(arrays["timestamps"], ensure_utc(end_at))
    if end <= start:
        return None
    hit = np.flatnonzero((arrays["low"][start:end] <= forecast["zone_high"]) & (arrays["high"][start:end] >= forecast["zone_low"]))
    return None if not len(hit) else arrays["timestamps"][start + int(hit[0])] + timedelta(minutes=1)


def _invalidation_event(*, forecast: dict[str, Any], invalidation: float | None, m15_frame: pd.DataFrame, start_at: datetime, end_at: datetime) -> datetime | None:
    if invalidation is None:
        return None
    work = m15_frame.copy()
    work["completed_at"] = pd.to_datetime(work["timestamp"], utc=True) + pd.Timedelta(minutes=15)
    future = work[(work["completed_at"] > pd.Timestamp(ensure_utc(start_at))) & (work["completed_at"] <= pd.Timestamp(ensure_utc(end_at)))]
    if forecast["direction"] == "LONG":
        rows = future[future["close"] < invalidation]
    else:
        rows = future[future["close"] > invalidation]
    return None if rows.empty else ensure_utc(pd.Timestamp(rows.iloc[0]["completed_at"]).to_pydatetime())


def _reversal_hit(arrays: dict[str, Any], forecast: dict[str, Any], touch_at: datetime) -> bool:
    hours = float(REVERSAL_HOURS.get(forecast["timeframe"], 24.0))
    start = bisect_left(arrays["timestamps"], ensure_utc(touch_at))
    end = min(len(arrays["timestamps"]), bisect_left(arrays["timestamps"], ensure_utc(touch_at) + timedelta(hours=hours)))
    if end <= start:
        return False
    if forecast["zone_direction"] == "SHORT":
        return bool(np.any(arrays["low"][start:end] <= forecast["zone_low"] - REVERSAL_ATR * forecast["atr"]))
    if forecast["zone_direction"] == "LONG":
        return bool(np.any(arrays["high"][start:end] >= forecast["zone_high"] + REVERSAL_ATR * forecast["atr"]))
    return False


def _same_path(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.get("direction") == b.get("direction") and a.get("zone_id") == b.get("zone_id")


def _run_config(*, year: int, config: Config, arrays: dict[str, Any], bars: dict[str, tuple[Bar, ...]], completed: dict[str, list[datetime]], frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    h1_year = [t for t in completed["H1"] if ensure_utc(t).year == year]
    if len(h1_year) < 600:
        return {"config": config.name, "summary": {}, "episodes": []}
    cursor = ensure_utc(h1_year[559])
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    hard_end = min(year_end, arrays["timestamps"][-1] + timedelta(minutes=1))
    episodes: list[dict[str, Any]] = []
    trigger = "INITIAL"
    loop_guard = 0

    while cursor < hard_end and loop_guard < 5000:
        loop_guard += 1
        forecast = _forecast(as_of=cursor, arrays=arrays, bars=bars, completed=completed)
        if forecast is None:
            nxt = _next_completed(completed["M15"], cursor)
            if nxt is None or nxt <= cursor:
                break
            cursor = nxt
            continue

        episode_start = cursor
        initial_direction = forecast["direction"]
        initial_zone = forecast["zone_id"]
        refresh_count = 0
        resolution = "CENSORED"
        resolved_at = min(hard_end, cursor + timedelta(hours=MAX_LEG_HOURS))
        reversal = False

        while cursor < hard_end:
            max_end = min(hard_end, episode_start + timedelta(hours=MAX_LEG_HOURS))
            expiry = _zone_expiry(forecast, max_end)
            periodic = min(max_end, cursor + timedelta(hours=REFRESH_HOURS))
            segment_end = min(max_end, expiry, periodic)
            invalidation = _invalidation_level(forecast=forecast, config=config, m15_frame=frames["M15"], as_of=cursor)
            touch_at = _target_touch(arrays, forecast, cursor, segment_end)
            invalid_at = _invalidation_event(forecast=forecast, invalidation=invalidation, m15_frame=frames["M15"], start_at=cursor, end_at=segment_end)

            if touch_at is not None and (invalid_at is None or touch_at <= invalid_at):
                resolution, resolved_at = "TARGET_TOUCH", touch_at
                reversal = _reversal_hit(arrays, forecast, touch_at)
                break
            if invalid_at is not None:
                resolution, resolved_at = "INVALIDATED", invalid_at
                break
            if expiry <= periodic and expiry <= max_end:
                resolution, resolved_at = "EXPIRED", expiry
                break
            if segment_end >= max_end:
                resolution, resolved_at = "CENSORED", max_end
                break

            # Periodic structural refresh. Same selected path continues; changed
            # selected zone/direction closes this forecast and starts a new one.
            refreshed = _forecast(as_of=periodic, arrays=arrays, bars=bars, completed=completed)
            if refreshed is None:
                cursor = periodic
                continue
            refresh_count += 1
            if not _same_path(forecast, refreshed):
                resolution, resolved_at = "RESELECTED", periodic
                break
            forecast = refreshed
            cursor = periodic

        episodes.append({
            "index": len(episodes), "trigger": trigger,
            "as_of": episode_start.isoformat(), "resolved_at": resolved_at.isoformat(),
            "resolution": resolution, "direction": initial_direction,
            "final_direction": forecast["direction"], "target_zone_id": initial_zone,
            "final_target_zone_id": forecast["zone_id"], "target_timeframe": forecast["timeframe"],
            "distance_atr": forecast.get("distance_atr"), "path_rank": forecast.get("path_rank"),
            "hours_to_resolution": max(0.0, (resolved_at - episode_start).total_seconds() / 3600.0),
            "refresh_count": refresh_count, "reversal_050_atr_after_touch": reversal,
        })

        if resolution == "INVALIDATED":
            trigger = "AFTER_INVALIDATION"
            nxt = _next_completed(completed["M15"], resolved_at)
        elif resolution == "RESELECTED":
            trigger = "AFTER_RESELECTION"
            nxt = resolved_at
        else:
            trigger = "AFTER_" + resolution
            nxt = _next_completed(completed["M15"], resolved_at)
        if nxt is None or nxt <= episode_start:
            break
        cursor = nxt

    terminal = [r for r in episodes if r["resolution"] in {"TARGET_TOUCH", "INVALIDATED", "EXPIRED", "CENSORED"}]
    touches = [r for r in terminal if r["resolution"] == "TARGET_TOUCH"]
    invalids = [r for r in terminal if r["resolution"] == "INVALIDATED"]
    reselected = [r for r in episodes if r["resolution"] == "RESELECTED"]
    chains = [r for r in touches if r["reversal_050_atr_after_touch"]]
    fast_invalids = [r for r in invalids if r["hours_to_resolution"] <= 8.0]

    # Recovery: after each invalidation, allow intervening reselections. The first
    # next terminal outcome determines whether adaptive reforecast recovered.
    recovery_n = recovery_success = 0
    for i, row in enumerate(episodes):
        if row["resolution"] != "INVALIDATED":
            continue
        for nxt in episodes[i + 1:]:
            if nxt["resolution"] == "RESELECTED":
                continue
            recovery_n += 1
            recovery_success += int(nxt["resolution"] == "TARGET_TOUCH")
            break

    summary = {
        "episodes": len(episodes), "terminal_legs": len(terminal),
        "target_touches": len(touches), "invalidations": len(invalids),
        "reselected_paths": len(reselected),
        "expired": sum(r["resolution"] == "EXPIRED" for r in terminal),
        "censored": sum(r["resolution"] == "CENSORED" for r in terminal),
        "current_leg_target_rate": None if not terminal else len(touches) / len(terminal),
        "invalidation_rate": None if not terminal else len(invalids) / len(terminal),
        "reselection_rate_per_episode": None if not episodes else len(reselected) / len(episodes),
        "reforecast_recovery_n": recovery_n,
        "reforecast_recovery_rate": None if not recovery_n else recovery_success / recovery_n,
        "chain_touch_plus_reversal_rate": None if not terminal else len(chains) / len(terminal),
        "reversal_after_touch_rate": None if not touches else len(chains) / len(touches),
        "fast_invalidation_le_8h_rate": None if not invalids else len(fast_invalids) / len(invalids),
        "median_hours_to_target": None if not touches else float(np.median([r["hours_to_resolution"] for r in touches])),
        "median_hours_to_invalidation": None if not invalids else float(np.median([r["hours_to_resolution"] for r in invalids])),
        "resolution_counts": dict(Counter(r["resolution"] for r in episodes)),
    }
    return {"config": config.name, "parameters": {"m15_lookback": config.m15_lookback, "buffer_atr": config.buffer_atr, "periodic_refresh_hours": REFRESH_HOURS}, "summary": summary, "episodes": episodes}


def run(year: int, csv_path: Path, output: Path) -> dict[str, Any]:
    price = load_price_frame(csv_path)
    arrays = _arrays(price)
    bars, completed, frames = _bar_cache(price)
    results = [_run_config(year=year, config=c, arrays=arrays, bars=bars, completed=completed, frames=frames) for c in CONFIGS]
    payload = {
        "schema": SCHEMA, "year": year, "generated_at": datetime.now(tz=UTC).isoformat(),
        "source": "HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY", "causal": True,
        "execution_authority": False, "champion_selector": "V376_C4_NEXT_ZONE_PATH_FROZEN",
        "purpose": "Test adaptive invalidate/reselect/expire -> recompute -> reforecast state machine without retraining C4.",
        "configs": results,
        "limitations": [
            "Public M1 OHLC plus completed M15 structural invalidation; not bid/ask tick execution replay.",
            "C4 zone-selection parameters remain frozen; only path state is recalculated.",
            "2025 is configuration selection; 2026 must remain holdout.",
            "Path metrics are not trade PnL; costs, news, SL/TP and execution gates are outside V383.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("V383_SUMMARY=" + json.dumps({r["config"]: r["summary"] for r in results}, sort_keys=True))
    print(f"OUTPUT={output}")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.year, a.csv, a.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
