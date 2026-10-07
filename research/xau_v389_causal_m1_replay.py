from __future__ import annotations

"""V389 causal M1 liquidity-sweep/reclaim reversal; research-only.

Frozen C4 M15_LB12_B020 episodes from V386 (2025) and V384 (2026).
Calibration policies are selected from 2025 ONLY. Holdout receives only
the frozen 2025 policy, and is not executed if 2025 has no positive edge.

Signal timestamps are M5/M15 completed-bar times; fills use the next
available M1 open. No future candles are consulted for entry/SL/TP.
The sweep threshold's 'R' is a PRE-TOUCH REFERENCE unit defined as
max(zone width, 0.5*zone ATR), NOT the realized execution risk unit.
PnL R is normalized by the actual structural SL distance after costs.

This is independent admission research, not broker execution. Historical
news calendar and broker-specific event gates cannot be applied without
timestamped causal data; their absence is disclosed, never silently passed.
"""
import argparse
import glob
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from fx_scanner.models import ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import load_price_frame
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity
from xau_v384_adaptive_c4_reforecast_cached import (
    _arrays as _c4_arrays,
    _bar_cache,
    _completed_bars,
    _forecast,
    _price_before,
)
from xau_v387_execution_pnl_replay import (
    ADAPTIVE_CONFIG, MAX_OPEN_POSITIONS, _dt, _f, _find_entry_index,
    _load_adaptive, _max_drawdown, _price_arrays, _simulate_trade,
)
from xau_v389_liquidity_sweep_reversal import DISCOVERY_2025_GRID

SCHEMA = "XAU_V389_CAUSAL_M1_REPLAY_V1"
MAX_SIGNAL_HOURS = 12
STOP_ATR_BUFFER = 0.10
MIN_CALIBRATION_TRADES = 30
MIN_HOLDOUT_TRADES = 20
EXPECTED_SHARDS = 4
POLICIES = {p["name"]: p for p in DISCOVERY_2025_GRID}


def _frame_arrays(frame: Any, completed: list[datetime]) -> dict[str, Any]:
    return {
        "completed": completed,
        "open": frame["open"].to_numpy(dtype=float, copy=False),
        "high": frame["high"].to_numpy(dtype=float, copy=False),
        "low": frame["low"].to_numpy(dtype=float, copy=False),
        "close": frame["close"].to_numpy(dtype=float, copy=False),
    }


def _signal(
    *,
    m5: dict[str, Any],
    m15: dict[str, Any],
    touch_at: datetime,
    direction: str,
    zone_low: float,
    zone_high: float,
    ref_r: float,
    policy: dict[str, Any],
) -> dict[str, Any] | None:
    """Find first qualifying sweep -> M5 reclaim -> later displacement.

    The reclaim bar can contain both sweep and reclaim: its close necessarily
    occurs after its high/low, so no intrabar ordering assumption is needed.
    Confirmation must start AFTER the reclaim bar has completed.
    """
    threshold = float(policy["min_sweep_r"]) * ref_r
    displacement = float(policy["min_displacement_r"]) * ref_r
    boundary = zone_low if direction == "LONG" else zone_high
    first = bisect_left(m5["completed"], touch_at)
    deadline = touch_at + timedelta(hours=MAX_SIGNAL_HOURS)
    last = bisect_right(m5["completed"], deadline)
    extreme = boundary
    swept = False
    reclaim_at = None
    reclaim_close = None
    reclaim_index = None
    reclaim_extreme = None
    for k in range(first, min(last, len(m5["completed"]))):
        at = m5["completed"][k]
        lo, hi = float(m5["low"][k]), float(m5["high"][k])
        close = float(m5["close"][k])
        if direction == "LONG":
            extreme = min(extreme, lo)
            swept = swept or extreme <= boundary - threshold
        else:
            extreme = max(extreme, hi)
            swept = swept or extreme >= boundary + threshold
        if not swept:
            continue

        if reclaim_at is not None:
            # A fresh adverse extreme after reclaim invalidates the pending
            # confirmation; await a new causal reclaim, never look ahead.
            broke = (lo < reclaim_extreme if direction == "LONG"
                     else hi > reclaim_extreme)
            if broke:
                reclaim_at = None
                reclaim_close = None
                reclaim_index = None
                reclaim_extreme = None

        if reclaim_at is None:
            reclaimed = close >= boundary if direction == "LONG" else close <= boundary
            if reclaimed:
                reclaim_at, reclaim_close, reclaim_index = at, close, k
                reclaim_extreme = extreme
            continue

        tf = policy["confirm_tf"]
        if tf == "M5":
            if k <= reclaim_index or at - timedelta(minutes=5) < reclaim_at:
                continue
            c_open, c_close = float(m5["open"][k]), close
        else:
            ix = bisect_left(m15["completed"], at)
            if ix >= len(m15["completed"]) or m15["completed"][ix] != at:
                continue
            if at - timedelta(minutes=15) < reclaim_at:
                continue
            c_open = float(m15["open"][ix])
            c_close = float(m15["close"][ix])

        if direction == "LONG":
            confirmed = (c_close >= reclaim_close + displacement
                         and c_close > c_open and c_close >= boundary)
        else:
            confirmed = (c_close <= reclaim_close - displacement
                         and c_close < c_open and c_close <= boundary)
        if confirmed:
            return {
                "confirm_at": at,
                "reclaim_at": reclaim_at,
                "reclaim_close": reclaim_close,
                "sweep_extreme": extreme,
                "sweep_depth_ref_r": abs(extreme - boundary) / ref_r,
                "displacement_ref_r": abs(c_close - reclaim_close) / ref_r,
            }
    return None


def run_shard(*, year: int, adaptive_json: Path, csv_path: Path,
              shard_index: int, shard_count: int, policy: str,
              output: Path) -> dict[str, Any]:
    if year == 2026 and policy == "all":
        raise ValueError("Holdout must replay only the frozen 2025 policy")
    selected_policies = POLICIES if policy == "all" else {policy: POLICIES[policy]}
    adaptive, touches = _load_adaptive(adaptive_json)
    price = load_price_frame(csv_path)
    arrays = _price_arrays(price)
    c4_arrays = _c4_arrays(price)
    bars, completed, frames = _bar_cache(price)
    m5 = _frame_arrays(frames["M5"], completed["M5"])
    m15 = _frame_arrays(frames["M15"], completed["M15"])
    forecast_cache: dict[datetime, dict[str, Any] | None] = {}
    cache_stats = {"hits": 0, "evaluations": 0}
    rows = [row for i, row in enumerate(touches) if i % shard_count == shard_index]
    skips = {name: Counter() for name in selected_policies}
    trades = {name: [] for name in selected_policies}

    for n, episode in enumerate(rows, 1):
        touch_at = _dt(episode["resolved_at"])
        episode_at = _dt(episode["as_of"])
        # Geometry is frozen at the causal forecast preceding target touch.
        # A reselected target is NOT silently substituted by a future zone.
        forecast = _forecast(as_of=episode_at, arrays=c4_arrays, bars=bars,
                             completed=completed, cache=forecast_cache,
                             cache_stats=cache_stats)
        final_zone_id = str(episode.get("final_target_zone_id") or "")
        if not forecast or forecast["zone_id"] != final_zone_id:
            for s in skips.values(): s["ZONE_GEOMETRY_UNAVAILABLE_OR_CHANGED"] += 1
            continue
        zone_low = float(forecast["zone_low"])
        zone_high = float(forecast["zone_high"])
        atr = float(forecast["atr"])
        zone_direction = str(forecast["zone_direction"]).upper()
        if zone_direction not in {"LONG", "SHORT"}:
            for s in skips.values(): s["INVALID_REVERSAL_SIDE"] += 1
            continue
        direction = zone_direction
        # Must be a counter-leg target touch, not a continuation disguised as reversal.
        if str(episode.get("final_direction") or "").upper() == direction:
            for s in skips.values(): s["NOT_COUNTER_LEG_ZONE"] += 1
            continue
        ref_r = max(zone_high - zone_low, 0.5 * atr, 0.01)

        for name, cfg in selected_policies.items():
            signal = _signal(m5=m5, m15=m15, touch_at=touch_at,
                             direction=direction, zone_low=zone_low,
                             zone_high=zone_high, ref_r=ref_r, policy=cfg)
            if signal is None:
                skips[name]["NO_SWEEP_RECLAIM_DISPLACEMENT"] += 1
                continue
            confirm_at = signal["confirm_at"]
            entry_idx = _find_entry_index(arrays["timestamps"], confirm_at)
            if entry_idx is None or arrays["timestamps"][entry_idx] - confirm_at > timedelta(minutes=5):
                skips[name]["NO_PROMPT_M1_ENTRY_AFTER_CONFIRM"] += 1
                continue
            px = _price_before(c4_arrays, confirm_at)
            if px is None:
                skips[name]["NO_CAUSAL_PRICE"] += 1
                continue
            h1 = _completed_bars(bars, completed, "H1", confirm_at)
            h4 = _completed_bars(bars, completed, "H4", confirm_at)
            b15 = _completed_bars(bars, completed, "M15", confirm_at)
            b5 = _completed_bars(bars, completed, "M5", confirm_at)
            if min(len(h1) / 80, len(h4) / 40, len(b15) / 32, len(b5) / 32) < 1:
                skips[name]["INSUFFICIENT_CAUSAL_HTF_BARS"] += 1
                continue
            result = evaluate_sd_liquidity(bars_h1=h1, bars_h4=h4,
                                           bars_m15=b15, bars_m5=b5,
                                           as_of=confirm_at, price_now=float(px))
            destination = dict(result.get("structural_destination") or {})
            target_mid = _f(destination.get("price"))
            if target_mid is None:
                skips[name]["NO_OPPOSING_STRUCTURAL_DESTINATION"] += 1
                continue
            target_side = str(destination.get("direction") or "").upper()
            if target_side in {"LONG", "SHORT"} and target_side == direction:
                skips[name]["DESTINATION_NOT_OPPOSING"] += 1
                continue
            stop_mid = (float(signal["sweep_extreme"]) - STOP_ATR_BUFFER * atr
                        if direction == "LONG"
                        else float(signal["sweep_extreme"]) + STOP_ATR_BUFFER * atr)
            trade = _simulate_trade(arrays=arrays, entry_idx=entry_idx,
                                    direction=direction, stop_mid=stop_mid,
                                    target_mid=float(target_mid))
            if trade is None:
                skips[name]["INVALID_SL_TP_GEOMETRY"] += 1
                continue
            if trade.get("rejected"):
                skips[name][str(trade.get("reject_reason") or "RR_REJECTED")] += 1
                continue
            trade.update({
                "policy": name, "episode_index": episode.get("index"),
                "c4_selector": ADAPTIVE_CONFIG, "touch_at": touch_at.isoformat(),
                "forecast_as_of": episode_at.isoformat(),
                "zone_id": final_zone_id, "zone_timeframe": forecast["timeframe"],
                "reclaim_at": signal["reclaim_at"].isoformat(),
                "confirmation_at": confirm_at.isoformat(),
                "sweep_extreme": signal["sweep_extreme"],
                "sweep_depth_ref_r": signal["sweep_depth_ref_r"],
                "displacement_ref_r": signal["displacement_ref_r"],
                "terminal_zone_id": destination.get("zone_id"),
                "terminal_timeframe": destination.get("timeframe"),
            })
            trades[name].append(trade)
        if n % 50 == 0:
            print(f"V389_PROGRESS year={year} shard={shard_index} "
                  f"processed={n}/{len(rows)} candidates="
                  f"{ {k: len(v) for k,v in trades.items()} }", flush=True)

    payload = {
        "schema": SCHEMA, "mode": "SHARD", "year": year,
        "generated_at": datetime.now(UTC).isoformat(),
        "c4_selector": ADAPTIVE_CONFIG, "adaptive_schema": adaptive.get("schema"),
        "shard_index": shard_index, "shard_count": shard_count,
        "total_target_touches": len(touches), "shard_target_touches": len(rows),
        "policies": {name: {"candidate_trades": trades[name],
                            "skip_counts": dict(skips[name])}
                     for name in selected_policies},
        "causal_news_gate": "NOT_APPLIED_NO_TIMESTAMPED_HISTORICAL_CALENDAR",
        "broker_dom_gate": "NOT_APPLIED_NO_CAUSAL_HISTORICAL_DOM",
        "cost_and_stop_first_model": "V387_FIXED_RESEARCH_ASSUMPTIONS",
        "execution_authority": False, "live_execution_enabled": False,
        "demo_execution_authority": False,
        "cache_stats": cache_stats,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print("V389_SHARD_SUMMARY=" + json.dumps({
        "year": year, "shard": shard_index,
        "candidates": {k: len(v) for k, v in trades.items()},
        "skips": {k: dict(v) for k, v in skips.items()},
    }, sort_keys=True), flush=True)
    return payload


def _summary(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates.sort(key=lambda t: (str(t["entry_at"]), str(t.get("episode_index"))))
    accepted = []
    active_exits: list[datetime] = []
    for t in candidates:
        at = _dt(t["entry_at"])
        active_exits = [x for x in active_exits if x > at]
        if len(active_exits) >= MAX_OPEN_POSITIONS:
            continue
        accepted.append(t)
        active_exits.append(_dt(t["exit_at"]))
    r = [float(t["r_multiple"]) for t in accepted]
    wins = [v for v in r if v > 0]
    losses = [v for v in r if v < 0]
    gross_loss = abs(sum(losses))
    pf = None if gross_loss < 1e-12 else sum(wins) / gross_loss
    metrics = {
        "candidate_count": len(candidates),
        "trades": len(accepted),
        "win_rate": len(wins) / len(r) if r else None,
        "profit_factor_r": pf,
        "expectancy_r": sum(r) / len(r) if r else None,
        "total_r": sum(r),
        "max_drawdown_r": _max_drawdown(r),
        "median_mae_r": median(float(t["mae_r"]) for t in accepted) if accepted else None,
        "median_mfe_r": median(float(t["mfe_r"]) for t in accepted) if accepted else None,
        "trades_per_month": len(accepted) / 12,
        "exit_counts": dict(Counter(str(t["exit_reason"]) for t in accepted)),
    }
    return metrics, accepted


def aggregate(*, year: int, inputs: str, output: Path, freeze: Path | None) -> dict[str, Any]:
    paths = sorted(Path(p) for p in glob.glob(inputs))
    if not paths:
        raise RuntimeError("No V389 shards available")
    parts = [json.loads(p.read_text()) for p in paths]
    actual = {int(p["shard_index"]) for p in parts if p["mode"] == "SHARD" and int(p["year"]) == year}
    expected = set(range(EXPECTED_SHARDS))
    if actual != expected or len(parts) != EXPECTED_SHARDS:
        raise RuntimeError(f"Incomplete/duplicate V389 shards: {sorted(actual)} vs {sorted(expected)}")
    policy_names = set(parts[0]["policies"])
    if any(set(p["policies"]) != policy_names for p in parts):
        raise RuntimeError("Policy mismatch between shards")
    summaries = {}
    all_trades = {}
    skip_counts = {}
    for name in sorted(policy_names):
        candidates = [dict(t) for p in parts for t in p["policies"][name]["candidate_trades"]]
        metrics, accepted = _summary(candidates)
        summaries[name], all_trades[name] = metrics, accepted
        counts = Counter()
        for p in parts: counts.update(p["policies"][name]["skip_counts"])
        skip_counts[name] = dict(counts)
    payload = {
        "schema": SCHEMA, "mode": "AGGREGATE", "year": year,
        "generated_at": datetime.now(UTC).isoformat(),
        "c4_selector": ADAPTIVE_CONFIG,
        "policy_summaries": summaries, "trades_by_policy": all_trades,
        "skip_counts": skip_counts, "shards": EXPECTED_SHARDS,
        "selection_uses_2026": False,
        "live_execution_enabled": False, "execution_authority": False,
        "limitations": [
            "M1 OHLC, not broker bid/ask tick fills; same-bar STOP_FIRST.",
            "Fixed V387 research spread/slippage/commission, not live broker quotes.",
            "Historical high-impact news and DOM gates unavailable; no claim of applying them.",
            "C4 target zone geometry from causal episode start; changed-zone episodes skipped.",
            "Sweep threshold uses reference zone/ATR R; trade PnL uses structural risk R.",
        ],
    }
    if freeze is not None:
        if year != 2025 or set(summaries) != set(POLICIES):
            raise RuntimeError("Freeze selection requires full 2025 discovery grid")
        eligible = [(name, m) for name, m in summaries.items()
                    if m["trades"] >= MIN_CALIBRATION_TRADES
                    and m["profit_factor_r"] is not None
                    and m["profit_factor_r"] > 1.0
                    and m["expectancy_r"] is not None
                    and m["expectancy_r"] > 0.0]
        winner = max(eligible, key=lambda x: (
            x[1]["profit_factor_r"], x[1]["expectancy_r"],
            -x[1]["max_drawdown_r"], x[1]["trades"]))[0] if eligible else None
        frozen = {
            "schema": SCHEMA, "frozen_at": datetime.now(UTC).isoformat(),
            "selection_period": 2025, "holdout_period": 2026,
            "c4_selector": ADAPTIVE_CONFIG, "selected_policy": winner,
            "selection_rule": "n>=30, PF>1, expectancy>0; maximize PF, expectancy, lower DD",
            "status": "FROZEN_FOR_BLIND_HOLDOUT" if winner else "CALIBRATION_REJECTED",
            "winner_2025_metrics": summaries.get(winner) if winner else None,
            "all_2025_metrics": summaries,
            "live_execution_enabled": False, "execution_authority": False,
        }
        freeze.parent.mkdir(parents=True, exist_ok=True)
        freeze.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
        payload["frozen_selection"] = frozen
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print("V389_AGGREGATE=" + json.dumps({
        "year": year, "summaries": summaries,
        "frozen_policy": payload.get("frozen_selection", {}).get("selected_policy"),
    }, sort_keys=True), flush=True)
    return payload


def holdout(*, calibration: Path, holdout_json: Path, output: Path) -> dict[str, Any]:
    cal = json.loads(calibration.read_text())
    ho = json.loads(holdout_json.read_text())
    winner = cal.get("selected_policy")
    if not winner or ho["year"] != 2026 or set(ho["policy_summaries"]) != {winner}:
        raise RuntimeError("Blind holdout must contain only the frozen 2025 policy")
    a = cal["winner_2025_metrics"]
    b = ho["policy_summaries"][winner]
    passed = (a["trades"] >= MIN_CALIBRATION_TRADES
              and b["trades"] >= MIN_HOLDOUT_TRADES
              and a["profit_factor_r"] is not None and a["profit_factor_r"] >= 1.5
              and b["profit_factor_r"] is not None and b["profit_factor_r"] >= 1.5
              and a["expectancy_r"] > 0 and b["expectancy_r"] > 0)
    result = {
        "schema": SCHEMA, "frozen_policy": winner,
        "c4_selector": ADAPTIVE_CONFIG,
        "calibration_2025": a, "blind_holdout_2026": b,
        "decision": "PROVISIONAL_PASS_REQUIRES_WALK_FORWARD" if passed else "REJECTED",
        "live_execution_enabled": False, "execution_authority": False,
        "warning": "Historical news/DOM gates not available; no production promotion.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("V389_HOLDOUT_DECISION=" + json.dumps(result, sort_keys=True), flush=True)
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--year", type=int, choices=[2025, 2026], required=True)
    s.add_argument("--adaptive-json", type=Path, required=True)
    s.add_argument("--csv", type=Path, required=True)
    s.add_argument("--shard-index", type=int, required=True)
    s.add_argument("--shard-count", type=int, default=EXPECTED_SHARDS)
    s.add_argument("--policy", required=True, choices=["all", *POLICIES])
    s.add_argument("--output", type=Path, required=True)
    a = sub.add_parser("aggregate")
    a.add_argument("--year", type=int, choices=[2025, 2026], required=True)
    a.add_argument("--inputs", required=True)
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--freeze", type=Path)
    h = sub.add_parser("holdout")
    h.add_argument("--calibration", type=Path, required=True)
    h.add_argument("--holdout-json", type=Path, required=True)
    h.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.mode == "shard":
        run_shard(year=args.year, adaptive_json=args.adaptive_json, csv_path=args.csv,
                  shard_index=args.shard_index, shard_count=args.shard_count,
                  policy=args.policy, output=args.output)
    elif args.mode == "aggregate":
        aggregate(year=args.year, inputs=args.inputs, output=args.output, freeze=args.freeze)
    else:
        holdout(calibration=args.calibration, holdout_json=args.holdout_json,
                output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
