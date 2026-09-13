from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.research_xau_d1_tsmom_crossfeed_v1 import BOUNDARY_HOURS_UTC
from adaptive_xau_ctrader_crossfeed_v1 import fetch_history, as_rows, period
from adaptive_xau_expansion_v4_walkforward import param_grid, generate_trades, reprice
from adaptive_xau_expansion_v41_intraday_timing import h1_rows
from adaptive_router_public_backtest import indicators, metrics

SYMBOL = "XAUUSD"
CONFIG_ID = "S2R2T2H0"
CONFIRM_START = date(2024, 1, 1)
CONFIRM_END = date(2026, 8, 31)
BASE_COST_R = 0.05
POLICIES = ("STATIC", "CURRENT_RUNTIME", "BE100", "BE125", "BE150", "DEFERRED_STEP")


def lock_r(policy: str, favorable_r: float) -> float | None:
    if policy == "STATIC":
        return None
    if policy == "CURRENT_RUNTIME":
        if favorable_r < 0.50:
            return None
        if favorable_r < 0.80:
            return 0.05
        if favorable_r < 1.20:
            return 0.25
        if favorable_r < 1.80:
            return 0.55
        if favorable_r < 2.50:
            return 1.00
        return max(1.00, favorable_r - 0.75)
    if policy == "BE100":
        return 0.05 if favorable_r >= 1.00 else None
    if policy == "BE125":
        return 0.10 if favorable_r >= 1.25 else None
    if policy == "BE150":
        return 0.25 if favorable_r >= 1.50 else None
    if policy == "DEFERRED_STEP":
        if favorable_r < 1.25:
            return None
        if favorable_r < 1.75:
            return 0.10
        if favorable_r < 2.25:
            return 0.50
        if favorable_r < 2.50:
            return 1.00
        return max(1.00, favorable_r - 1.00)
    raise ValueError(policy)


def simulate_open(
    *,
    side: str,
    entry_i: int,
    entry_price: float,
    structural_stop: float,
    structural_target: float,
    deadline: datetime,
    h1: list[dict[str, Any]],
    policy: str,
) -> dict[str, Any] | None:
    risk = entry_price - structural_stop if side == "LONG" else structural_stop - entry_price
    if not math.isfinite(risk) or risk <= 0:
        return None
    stop = float(structural_stop)
    exit_i = None
    exit_price = None
    reason = "TIME"
    updates = 0
    for i in range(entry_i, len(h1)):
        bar = h1[i]
        if bar["dt"] >= deadline:
            break
        o, hi, lo, close = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if side == "LONG":
            if o <= stop:
                exit_i, exit_price, reason = i, o, "STOP_GAP"
                break
            if o >= structural_target:
                exit_i, exit_price, reason = i, structural_target, "TP_GAP"
                break
            hit_stop, hit_target = lo <= stop, hi >= structural_target
        else:
            if o >= stop:
                exit_i, exit_price, reason = i, o, "STOP_GAP"
                break
            if o <= structural_target:
                exit_i, exit_price, reason = i, structural_target, "TP_GAP"
                break
            hit_stop, hit_target = hi >= stop, lo <= structural_target
        if hit_stop and hit_target:
            exit_i, exit_price, reason = i, stop, "SL_AMBIGUOUS_FIRST"
            break
        if hit_stop:
            exit_i, exit_price, reason = i, stop, "SL"
            break
        if hit_target:
            exit_i, exit_price, reason = i, structural_target, "TP"
            break

        favorable = (close - entry_price) / risk if side == "LONG" else (entry_price - close) / risk
        desired_r = lock_r(policy, favorable)
        if desired_r is not None:
            candidate = entry_price + desired_r * risk if side == "LONG" else entry_price - desired_r * risk
            valid = candidate > stop and candidate < close if side == "LONG" else candidate < stop and candidate > close
            if valid:
                stop = candidate
                updates += 1

    if exit_i is None:
        candidates = [i for i in range(entry_i, len(h1)) if h1[i]["dt"] < deadline]
        if not candidates:
            return None
        exit_i = candidates[-1]
        exit_price = float(h1[exit_i]["close"])
    gross_r = (exit_price - entry_price) / risk if side == "LONG" else (entry_price - exit_price) / risk
    return {
        "symbol": SYMBOL,
        "timeframe": "H1_EXECUTION_ON_D1_SETUP",
        "setup": "EXPANSION_BREAKOUT",
        "side": side,
        "entry_at": h1[entry_i]["dt"].isoformat(),
        "exit_at": h1[exit_i]["dt"].isoformat(),
        "gross_r": round(gross_r, 6),
        "net_r": round(gross_r - BASE_COST_R, 6),
        "cost_r": BASE_COST_R,
        "exit_reason": reason,
        "management_policy": policy,
        "lock_updates": updates,
        "final_stop": round(stop, 6),
    }


def panel(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "base_0_05R": metrics(reprice(trades, 0.05)),
        "stress_0_10R": metrics(reprice(trades, 0.10)),
        "severe_0_15R": metrics(reprice(trades, 0.15)),
    }


def replay_boundary(history, boundary: int, cfg) -> dict[str, Any]:
    daily = as_rows(history, boundary)
    ind = indicators(daily)
    daily_index = {row["dt"].isoformat(): i for i, row in enumerate(daily)}
    baseline = period(generate_trades(daily, cfg), CONFIRM_START, CONFIRM_END)
    h1 = h1_rows(history)
    h1_times = [x["dt"] for x in h1]
    variants = {p: [] for p in POLICIES}
    for base in baseline:
        signal_i = daily_index.get(base["signal_at"])
        if signal_i is None or signal_i + 1 >= len(daily):
            continue
        atr = ind["atr"][signal_i]
        if atr is None or atr <= 0:
            continue
        side = str(base["side"])
        entry_daily_i = signal_i + 1
        start = daily[entry_daily_i]["dt"]
        entry_i = next((i for i, ts in enumerate(h1_times) if ts >= start), None)
        if entry_i is None:
            continue
        entry_price = float(h1[entry_i]["open"])
        baseline_entry = float(daily[entry_daily_i]["open"])
        baseline_risk = float(cfg.stop_atr * atr)
        structural_stop = baseline_entry - baseline_risk if side == "LONG" else baseline_entry + baseline_risk
        structural_target = baseline_entry + cfg.rr * baseline_risk if side == "LONG" else baseline_entry - cfg.rr * baseline_risk
        hold_i = min(len(daily) - 1, entry_daily_i + cfg.max_hold)
        deadline = daily[hold_i]["dt"] + timedelta(hours=24)
        for policy in POLICIES:
            trade = simulate_open(
                side=side,
                entry_i=entry_i,
                entry_price=entry_price,
                structural_stop=structural_stop,
                structural_target=structural_target,
                deadline=deadline,
                h1=h1,
                policy=policy,
            )
            if trade is not None:
                trade["signal_at"] = base["signal_at"]
                trade["d1_boundary_hour_utc"] = boundary
                variants[policy].append(trade)
    return {
        "boundary_hour_utc": boundary,
        "baseline_signal_count": len(baseline),
        "policies": {p: {"panel": panel(ts), "trades": ts} for p, ts in variants.items()},
    }


def aggregate(boundaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    static_stress = [b["policies"]["STATIC"]["panel"]["stress_0_10R"] for b in boundaries]
    static_net = statistics.median(float(x.get("net_r", 0.0) or 0.0) for x in static_stress)
    static_pf = statistics.median(float(x.get("profit_factor", 0.0) or 0.0) for x in static_stress)
    static_dd = statistics.median(float(x.get("max_drawdown_pct_at_0_5pct_risk", 0.0) or 0.0) for x in static_stress)
    out = []
    for policy in POLICIES:
        stress = [b["policies"][policy]["panel"]["stress_0_10R"] for b in boundaries]
        severe = [b["policies"][policy]["panel"]["severe_0_15R"] for b in boundaries]
        med_net = statistics.median(float(x.get("net_r", 0.0) or 0.0) for x in stress)
        med_exp = statistics.median(float(x.get("expectancy_r", 0.0) or 0.0) for x in stress)
        med_pf = statistics.median(float(x.get("profit_factor", 0.0) or 0.0) for x in stress)
        med_dd = statistics.median(float(x.get("max_drawdown_pct_at_0_5pct_risk", 0.0) or 0.0) for x in stress)
        positive = sum(float(x.get("expectancy_r", 0.0) or 0.0) > 0 and float(x.get("profit_factor", 0.0) or 0.0) > 1.0 for x in stress)
        severe_positive = sum(float(x.get("expectancy_r", 0.0) or 0.0) > 0 and float(x.get("profit_factor", 0.0) or 0.0) > 1.0 for x in severe)
        retention = med_net / static_net if static_net else 0.0
        pf_gain = med_pf / static_pf if static_pf else 0.0
        dd_ratio = med_dd / static_dd if static_dd else 0.0
        pareto = bool(policy != "STATIC" and positive == 3 and severe_positive == 3 and retention >= 0.90 and med_pf >= static_pf and med_dd <= static_dd)
        out.append({
            "policy": policy,
            "positive_boundaries_stress": positive,
            "positive_boundaries_severe": severe_positive,
            "median_stress_net_r": round(med_net, 6),
            "median_stress_expectancy_r": round(med_exp, 6),
            "median_stress_profit_factor": round(med_pf, 4),
            "median_stress_max_dd_pct": round(med_dd, 4),
            "net_retention_vs_static": round(retention, 4),
            "pf_ratio_vs_static": round(pf_gain, 4),
            "dd_ratio_vs_static": round(dd_ratio, 4),
            "pareto_preferred": pareto,
        })
    out.sort(key=lambda x: (x["pareto_preferred"], x["median_stress_net_r"], x["median_stress_profit_factor"]), reverse=True)
    return out


def main() -> None:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_V42_RESEARCH_DEMO_ONLY")
    cfg = next(c for c in param_grid() if c.config_id == CONFIG_ID)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        history = fetch_history(feed)
    finally:
        try:
            feed.close()
        except Exception:
            pass
    boundaries = [replay_boundary(history, b, cfg) for b in BOUNDARY_HOURS_UTC]
    summary = aggregate(boundaries)
    preferred = next((x["policy"] for x in summary if x["pareto_preferred"]), None)
    result = {
        "schema_version": "XAU_EXPANSION_V42_PROFIT_PROTECTION",
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "promotion_eligible": False,
        "post_hoc_management_diagnostic": True,
        "fresh_forward_evidence_required": True,
        "symbol": SYMBOL,
        "d1_setup_config": CONFIG_ID,
        "entry_mode": "OPEN",
        "policies": list(POLICIES),
        "policy_definitions": {
            "CURRENT_RUNTIME": "0.50->+0.05R, 0.80->+0.25R, 1.20->+0.55R, 1.80->+1.00R, >=2.50 trail favorable-0.75R",
            "BE100": ">=1.00R close -> lock +0.05R only",
            "BE125": ">=1.25R close -> lock +0.10R only",
            "BE150": ">=1.50R close -> lock +0.25R only",
            "DEFERRED_STEP": "1.25->+0.10R, 1.75->+0.50R, 2.25->+1.00R, >=2.50 trail favorable-1.00R",
        },
        "method": {
            "stop_moves_decided_on_completed_h1_close_and_apply_next_bar": True,
            "same_bar_policy": "STOP_FIRST",
            "d1_stop_target_geometry_frozen": True,
            "costs_r": [0.05, 0.10, 0.15],
            "daily_boundaries_are_robustness_replicas": list(BOUNDARY_HOURS_UTC),
        },
        "summary": summary,
        "pareto_forward_candidate": preferred,
        "boundaries": boundaries,
    }
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, allow_nan=False))
    for row in summary:
        print("POLICY", row["policy"], "net=", row["median_stress_net_r"], "exp=", row["median_stress_expectancy_r"], "pf=", row["median_stress_profit_factor"], "dd=", row["median_stress_max_dd_pct"], "retain=", row["net_retention_vs_static"], "pareto=", row["pareto_preferred"])
    for b in boundaries:
        for policy_name in POLICIES:
            m = b["policies"][policy_name]["panel"]["stress_0_10R"]
            print("BOUNDARY", b["boundary_hour_utc"], policy_name, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"), "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"))


if __name__ == "__main__":
    main()
