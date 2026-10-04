from __future__ import annotations

"""Optimized V383 adaptive C4 reforecast replay.

Methodology is identical to V383 V2, but canonical C4 forecasts are cached by
causal timestamp and shared across invalidation challengers. M15 structural
arrays are also precomputed. No forecast/outcome leakage is introduced.
"""

import argparse
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from fx_scanner.models import Bar, ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import bars_from_frame, load_price_frame, resample_ohlc
from fx_scanner.xau_sd_liquidity_engine_v342 import TF_PARAMS, evaluate_sd_liquidity

SCHEMA = "XAU_V383_ADAPTIVE_C4_REFORECAST_V3_CACHED"
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


def sf(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def iso(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return ensure_utc(v)
    try:
        return ensure_utc(datetime.fromisoformat(str(v).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def build_cache(price: pd.DataFrame):
    bars: dict[str, tuple[Bar, ...]] = {}
    completed: dict[str, list[datetime]] = {}
    frames: dict[str, pd.DataFrame] = {}
    for tf, rule in RULES.items():
        f = resample_ohlc(price, rule)
        frames[tf] = f
        b = bars_from_frame(f, tf)
        bars[tf] = b
        d = timedelta(minutes=TF_MINUTES[tf])
        completed[tf] = [ensure_utc(x.timestamp) + d for x in b]
    return bars, completed, frames


def completed_bars(bars, completed, tf: str, t: datetime):
    i = bisect_right(completed[tf], ensure_utc(t))
    return bars[tf][max(0, i - WINDOWS[tf]):i]


def make_arrays(price: pd.DataFrame, m15_frame: pd.DataFrame) -> dict[str, Any]:
    m1t = [ensure_utc(pd.Timestamp(x).to_pydatetime()) for x in price["timestamp"]]
    m15t = [ensure_utc(pd.Timestamp(x).to_pydatetime()) + timedelta(minutes=15) for x in m15_frame["timestamp"]]
    return {
        "m1t": m1t,
        "m1h": price["high"].to_numpy(float, copy=False),
        "m1l": price["low"].to_numpy(float, copy=False),
        "m1c": price["close"].to_numpy(float, copy=False),
        "m15t": m15t,
        "m15h": m15_frame["high"].to_numpy(float, copy=False),
        "m15l": m15_frame["low"].to_numpy(float, copy=False),
        "m15c": m15_frame["close"].to_numpy(float, copy=False),
    }


def price_before(a: dict[str, Any], t: datetime) -> float | None:
    i = bisect_left(a["m1t"], ensure_utc(t)) - 1
    return None if i < 0 else float(a["m1c"][i])


def raw_forecast(t: datetime, a, bars, completed) -> dict[str, Any] | None:
    px = price_before(a, t)
    if px is None:
        return None
    h1 = completed_bars(bars, completed, "H1", t)
    h4 = completed_bars(bars, completed, "H4", t)
    m15 = completed_bars(bars, completed, "M15", t)
    m5 = completed_bars(bars, completed, "M5", t)
    if len(h1) < 80 or len(h4) < 40 or len(m15) < 32 or len(m5) < 32:
        return None
    r = evaluate_sd_liquidity(bars_h1=h1, bars_h4=h4, bars_m15=m15, bars_m5=m5, as_of=t, price_now=px)
    leg = dict(r.get("current_leg_forecast") or {})
    z = dict(r.get("main_reversal_zone") or r.get("decision_zone") or {})
    direction = str(leg.get("direction") or "").upper()
    lo, hi, atr = sf(z.get("low")), sf(z.get("high")), sf(z.get("atr"))
    if direction not in {"LONG", "SHORT"} or lo is None or hi is None or atr is None or atr <= 0 or hi <= lo:
        return None
    return {
        "as_of": ensure_utc(t), "direction": direction,
        "zone_id": str(z.get("zone_id") or ""), "timeframe": str(z.get("timeframe") or ""),
        "zone_direction": str(z.get("direction") or "").upper(), "zone_low": lo, "zone_high": hi,
        "atr": atr, "zone_available_at": z.get("available_at"),
        "distance_atr": sf(leg.get("distance_atr")),
        "path_rank": dict(z.get("next_zone_path") or {}).get("path_rank"),
    }


def cached_forecaster(a, bars, completed):
    cache: dict[datetime, dict[str, Any] | None] = {}
    calls = 0
    def get(t: datetime) -> dict[str, Any] | None:
        nonlocal calls
        key = ensure_utc(t)
        if key not in cache:
            cache[key] = raw_forecast(key, a, bars, completed)
            calls += 1
        v = cache[key]
        return None if v is None else dict(v)
    def stats():
        return {"unique_c4_evaluations": calls, "cached_timestamps": len(cache)}
    return get, stats


def next_completed(times: Sequence[datetime], t: datetime) -> datetime | None:
    i = bisect_right(times, ensure_utc(t))
    return None if i >= len(times) else ensure_utc(times[i])


def expiry(f: dict[str, Any], fallback: datetime) -> datetime:
    av = iso(f.get("zone_available_at"))
    life = sf(dict(TF_PARAMS.get(f.get("timeframe") or "") or {}).get("lifecycle_hours"))
    return fallback if av is None or life is None or life <= 0 else min(fallback, av + timedelta(hours=life))


def invalidation_level(f: dict[str, Any], c: Config, a: dict[str, Any], t: datetime) -> float | None:
    i = bisect_right(a["m15t"], ensure_utc(t))
    j = max(0, i - c.m15_lookback)
    if i - j < max(4, c.m15_lookback // 2):
        return None
    if f["direction"] == "LONG":
        return float(np.min(a["m15l"][j:i])) - c.buffer_atr * f["atr"]
    return float(np.max(a["m15h"][j:i])) + c.buffer_atr * f["atr"]


def touch_event(a, f, start_at, end_at):
    s, e = bisect_left(a["m1t"], start_at), bisect_left(a["m1t"], end_at)
    if e <= s:
        return None
    hit = np.flatnonzero((a["m1l"][s:e] <= f["zone_high"]) & (a["m1h"][s:e] >= f["zone_low"]))
    return None if not len(hit) else a["m1t"][s + int(hit[0])] + timedelta(minutes=1)


def invalid_event(a, f, level, start_at, end_at):
    if level is None:
        return None
    s, e = bisect_right(a["m15t"], start_at), bisect_right(a["m15t"], end_at)
    if e <= s:
        return None
    vals = a["m15c"][s:e]
    hit = np.flatnonzero(vals < level) if f["direction"] == "LONG" else np.flatnonzero(vals > level)
    return None if not len(hit) else a["m15t"][s + int(hit[0])]


def reversal_hit(a, f, t):
    hours = float(REVERSAL_HOURS.get(f["timeframe"], 24.0))
    s = bisect_left(a["m1t"], t)
    e = min(len(a["m1t"]), bisect_left(a["m1t"], t + timedelta(hours=hours)))
    if e <= s:
        return False
    if f["zone_direction"] == "SHORT":
        return bool(np.any(a["m1l"][s:e] <= f["zone_low"] - REVERSAL_ATR * f["atr"]))
    if f["zone_direction"] == "LONG":
        return bool(np.any(a["m1h"][s:e] >= f["zone_high"] + REVERSAL_ATR * f["atr"]))
    return False


def same_path(a, b):
    return a.get("direction") == b.get("direction") and a.get("zone_id") == b.get("zone_id")


def simulate(year: int, c: Config, a, completed, get_forecast: Callable[[datetime], dict[str, Any] | None]):
    times = [x for x in completed["H1"] if x.year == year]
    if len(times) < 600:
        return {"config": c.name, "summary": {}, "episodes": []}
    cursor = times[559]
    hard_end = min(datetime(year + 1, 1, 1, tzinfo=UTC), a["m1t"][-1] + timedelta(minutes=1))
    episodes = []
    trigger = "INITIAL"
    guard = 0
    while cursor < hard_end and guard < 5000:
        guard += 1
        f = get_forecast(cursor)
        if f is None:
            nxt = next_completed(a["m15t"], cursor)
            if nxt is None: break
            cursor = nxt
            continue
        episode_start = cursor
        start_dir, start_zone = f["direction"], f["zone_id"]
        refreshes = 0
        while True:
            cap = min(hard_end, episode_start + timedelta(hours=MAX_LEG_HOURS))
            exp = expiry(f, cap)
            periodic = min(cap, cursor + timedelta(hours=REFRESH_HOURS))
            end = min(cap, exp, periodic)
            level = invalidation_level(f, c, a, cursor)
            te = touch_event(a, f, cursor, end)
            ie = invalid_event(a, f, level, cursor, end)
            if te is not None and (ie is None or te <= ie):
                resolution, resolved, rev = "TARGET_TOUCH", te, reversal_hit(a, f, te)
                break
            if ie is not None:
                resolution, resolved, rev = "INVALIDATED", ie, False
                break
            if exp <= periodic and exp <= cap:
                resolution, resolved, rev = "EXPIRED", exp, False
                break
            if end >= cap:
                resolution, resolved, rev = "CENSORED", cap, False
                break
            nf = get_forecast(periodic)
            if nf is None:
                cursor = periodic
                continue
            refreshes += 1
            if not same_path(f, nf):
                resolution, resolved, rev = "RESELECTED", periodic, False
                break
            f, cursor = nf, periodic
        episodes.append({
            "index": len(episodes), "trigger": trigger, "as_of": episode_start.isoformat(),
            "resolved_at": resolved.isoformat(), "resolution": resolution,
            "direction": start_dir, "target_zone_id": start_zone,
            "final_direction": f["direction"], "final_target_zone_id": f["zone_id"],
            "target_timeframe": f["timeframe"], "distance_atr": f.get("distance_atr"),
            "path_rank": f.get("path_rank"), "hours_to_resolution": (resolved - episode_start).total_seconds()/3600.0,
            "refresh_count": refreshes, "reversal_050_atr_after_touch": rev,
        })
        if resolution == "INVALIDATED":
            trigger, nxt = "AFTER_INVALIDATION", next_completed(a["m15t"], resolved)
        elif resolution == "RESELECTED":
            trigger, nxt = "AFTER_RESELECTION", resolved
        else:
            trigger, nxt = "AFTER_" + resolution, next_completed(a["m15t"], resolved)
        if nxt is None or nxt <= episode_start: break
        cursor = nxt

    terminal = [r for r in episodes if r["resolution"] != "RESELECTED"]
    touches = [r for r in terminal if r["resolution"] == "TARGET_TOUCH"]
    invalids = [r for r in terminal if r["resolution"] == "INVALIDATED"]
    reselect = [r for r in episodes if r["resolution"] == "RESELECTED"]
    chains = [r for r in touches if r["reversal_050_atr_after_touch"]]
    recover_n = recover_ok = 0
    for i, row in enumerate(episodes):
        if row["resolution"] != "INVALIDATED": continue
        for nxt in episodes[i+1:]:
            if nxt["resolution"] == "RESELECTED": continue
            recover_n += 1
            recover_ok += int(nxt["resolution"] == "TARGET_TOUCH")
            break
    summary = {
        "episodes": len(episodes), "terminal_legs": len(terminal), "target_touches": len(touches),
        "invalidations": len(invalids), "reselected_paths": len(reselect),
        "expired": sum(r["resolution"] == "EXPIRED" for r in terminal),
        "censored": sum(r["resolution"] == "CENSORED" for r in terminal),
        "current_leg_target_rate": None if not terminal else len(touches)/len(terminal),
        "invalidation_rate": None if not terminal else len(invalids)/len(terminal),
        "reselection_rate_per_episode": None if not episodes else len(reselect)/len(episodes),
        "reforecast_recovery_n": recover_n,
        "reforecast_recovery_rate": None if not recover_n else recover_ok/recover_n,
        "chain_touch_plus_reversal_rate": None if not terminal else len(chains)/len(terminal),
        "reversal_after_touch_rate": None if not touches else len(chains)/len(touches),
        "fast_invalidation_le_8h_rate": None if not invalids else sum(r["hours_to_resolution"] <= 8 for r in invalids)/len(invalids),
        "median_hours_to_target": None if not touches else float(np.median([r["hours_to_resolution"] for r in touches])),
        "median_hours_to_invalidation": None if not invalids else float(np.median([r["hours_to_resolution"] for r in invalids])),
        "resolution_counts": dict(Counter(r["resolution"] for r in episodes)),
    }
    return {"config": c.name, "parameters": {"m15_lookback": c.m15_lookback, "buffer_atr": c.buffer_atr, "periodic_refresh_hours": REFRESH_HOURS}, "summary": summary, "episodes": episodes}


def run(year: int, csv_path: Path, output: Path):
    price = load_price_frame(csv_path)
    bars, completed, frames = build_cache(price)
    a = make_arrays(price, frames["M15"])
    get_forecast, cache_stats = cached_forecaster(a, bars, completed)
    results = [simulate(year, c, a, completed, get_forecast) for c in CONFIGS]
    payload = {
        "schema": SCHEMA, "year": year, "generated_at": datetime.now(tz=UTC).isoformat(),
        "source": "HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY", "causal": True, "execution_authority": False,
        "champion_selector": "V376_C4_NEXT_ZONE_PATH_FROZEN", "forecast_cache": cache_stats(),
        "purpose": "Adaptive C4 invalidate/reselect/expire -> causal recompute -> reforecast replay.",
        "configs": results,
        "limitations": [
            "Public M1 OHLC and completed M15 invalidation, not bid/ask tick replay.",
            "C4 selector remains frozen; cache only removes duplicate same-timestamp evaluations.",
            "2025 is configuration selection; 2026 is holdout.",
            "Path metrics are not trade PnL; costs/news/execution gates are outside V383.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
    print("V383_SUMMARY=" + json.dumps({r["config"]: r["summary"] for r in results}, sort_keys=True))
    print("CACHE=" + json.dumps(payload["forecast_cache"], sort_keys=True))
    return payload


def main():
    p=argparse.ArgumentParser(); p.add_argument("--year", type=int, required=True); p.add_argument("--csv", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a=p.parse_args(); run(a.year, a.csv, a.output); return 0


if __name__ == "__main__": raise SystemExit(main())
