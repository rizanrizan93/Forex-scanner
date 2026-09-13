from __future__ import annotations

import json
import math
import statistics
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.research_xau_d1_tsmom_crossfeed_v1 import BOUNDARY_HOURS_UTC
from adaptive_xau_ctrader_crossfeed_v1 import fetch_history, as_rows, period
from adaptive_xau_expansion_v4_walkforward import param_grid, generate_trades, reprice
from adaptive_router_public_backtest import indicators, ema, metrics

UTC = timezone.utc
SYMBOL = "XAUUSD"
CONFIG_ID = "S2R2T2H0"
CONFIRM_START = date(2024, 1, 1)
CONFIRM_END = date(2026, 8, 31)
BASE_COST_R = 0.05
ENTRY_WINDOW_HOURS = 24
ENTRY_MODES = ("OPEN", "PB15_24H", "PB25_24H", "RECLAIM_24H", "H4_ALIGN_24H")
MANAGEMENT_MODES = ("STATIC", "RUNTIME_LOCK")


def h1_rows(history) -> list[dict[str, Any]]:
    return [{"dt": r.timestamp, "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close)} for r in sorted(history, key=lambda x: x.timestamp)]


def build_h4(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        dt = row["dt"]
        start = dt.replace(hour=(dt.hour // 4) * 4, minute=0, second=0, microsecond=0)
        grouped.setdefault(start, []).append(row)
    out = []
    for start, items in sorted(grouped.items()):
        items = sorted(items, key=lambda x: x["dt"])
        if len(items) < 3:
            continue
        out.append({"dt": start, "close_time": items[-1]["dt"] + timedelta(hours=1), "open": items[0]["open"], "high": max(x["high"] for x in items), "low": min(x["low"] for x in items), "close": items[-1]["close"]})
    closes = [x["close"] for x in out]
    e20 = ema(closes, 20) if closes else []
    e50 = ema(closes, 50) if closes else []
    for i, row in enumerate(out):
        row["e20"] = e20[i]
        row["e50"] = e50[i]
    return out


def h4_aligned(row: dict[str, Any], side: str) -> bool:
    return bool(row["close"] > row["e20"] > row["e50"]) if side == "LONG" else bool(row["close"] < row["e20"] < row["e50"])


def first_index(times: list[datetime], at: datetime) -> int:
    return bisect_left(times, at)


def choose_entry(mode: str, *, side: str, baseline_entry: float, baseline_risk: float, start: datetime, h1: list[dict[str, Any]], h1_times: list[datetime], h4: list[dict[str, Any]]) -> tuple[int, float, str] | None:
    start_i = first_index(h1_times, start)
    if start_i >= len(h1):
        return None
    deadline = start + timedelta(hours=ENTRY_WINDOW_HOURS)
    if mode == "OPEN":
        return start_i, float(h1[start_i]["open"]), "NEXT_D1_OPEN_H1"
    if mode in {"PB15_24H", "PB25_24H"}:
        fraction = 0.15 if mode == "PB15_24H" else 0.25
        limit = baseline_entry - fraction * baseline_risk if side == "LONG" else baseline_entry + fraction * baseline_risk
        for i in range(start_i, len(h1)):
            bar = h1[i]
            if bar["dt"] >= deadline:
                break
            touched = bar["low"] <= limit if side == "LONG" else bar["high"] >= limit
            if touched:
                return i, float(limit), f"{mode}_LIMIT"
        return None
    if mode == "RECLAIM_24H":
        adverse = False
        adverse_level = baseline_entry - 0.15 * baseline_risk if side == "LONG" else baseline_entry + 0.15 * baseline_risk
        for i in range(start_i, len(h1)):
            bar = h1[i]
            if bar["dt"] >= deadline:
                break
            if side == "LONG":
                adverse = adverse or bar["low"] <= adverse_level
                reclaimed = adverse and bar["close"] >= baseline_entry
            else:
                adverse = adverse or bar["high"] >= adverse_level
                reclaimed = adverse and bar["close"] <= baseline_entry
            if reclaimed and i + 1 < len(h1) and h1[i + 1]["dt"] < deadline:
                return i + 1, float(h1[i + 1]["open"]), "RECLAIM_NEXT_H1_OPEN"
        return None
    if mode == "H4_ALIGN_24H":
        eligible = [x for x in h4 if x["close_time"] <= start]
        if eligible and h4_aligned(eligible[-1], side):
            return start_i, float(h1[start_i]["open"]), "PREEXISTING_H4_ALIGN"
        for row in h4:
            close_time = row["close_time"]
            if close_time <= start:
                continue
            if close_time > deadline:
                break
            if not h4_aligned(row, side):
                continue
            i = first_index(h1_times, close_time)
            if i < len(h1) and h1[i]["dt"] < deadline:
                return i, float(h1[i]["open"]), "H4_ALIGN_NEXT_H1_OPEN"
        return None
    raise ValueError(mode)


def lock_r_for_close(side: str, entry: float, close: float, risk: float) -> float | None:
    favorable = (close - entry) / risk if side == "LONG" else (entry - close) / risk
    if favorable < 0.50:
        return None
    if favorable < 0.80:
        return 0.05
    if favorable < 1.20:
        return 0.25
    if favorable < 1.80:
        return 0.55
    if favorable < 2.50:
        return 1.00
    return max(1.00, favorable - 0.75)


def simulate(*, side: str, entry_i: int, entry_price: float, structural_stop: float, structural_target: float, deadline: datetime, h1: list[dict[str, Any]], management: str, entry_reason: str) -> dict[str, Any] | None:
    risk = entry_price - structural_stop if side == "LONG" else structural_stop - entry_price
    if not math.isfinite(risk) or risk <= 0:
        return None
    stop = float(structural_stop)
    exit_price = None
    exit_i = None
    exit_reason = "TIME"
    lock_updates = 0
    max_favorable_r = 0.0
    max_adverse_r = 0.0
    for i in range(entry_i, len(h1)):
        bar = h1[i]
        if bar["dt"] >= deadline:
            break
        o, hi, lo, close = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if side == "LONG":
            max_favorable_r = max(max_favorable_r, (hi - entry_price) / risk)
            max_adverse_r = min(max_adverse_r, (lo - entry_price) / risk)
            if o <= stop:
                exit_price, exit_i, exit_reason = o, i, "STOP_GAP"
                break
            if o >= structural_target:
                exit_price, exit_i, exit_reason = structural_target, i, "TP_GAP"
                break
            hit_stop, hit_target = lo <= stop, hi >= structural_target
        else:
            max_favorable_r = max(max_favorable_r, (entry_price - lo) / risk)
            max_adverse_r = min(max_adverse_r, (entry_price - hi) / risk)
            if o >= stop:
                exit_price, exit_i, exit_reason = o, i, "STOP_GAP"
                break
            if o <= structural_target:
                exit_price, exit_i, exit_reason = structural_target, i, "TP_GAP"
                break
            hit_stop, hit_target = hi >= stop, lo <= structural_target
        if hit_stop and hit_target:
            exit_price, exit_i, exit_reason = stop, i, "SL_AMBIGUOUS_FIRST"
            break
        if hit_stop:
            exit_price, exit_i, exit_reason = stop, i, "SL"
            break
        if hit_target:
            exit_price, exit_i, exit_reason = structural_target, i, "TP"
            break
        if management == "RUNTIME_LOCK":
            lock_r = lock_r_for_close(side, entry_price, close, risk)
            if lock_r is not None:
                candidate = entry_price + lock_r * risk if side == "LONG" else entry_price - lock_r * risk
                valid = candidate > stop and candidate < close if side == "LONG" else candidate < stop and candidate > close
                if valid:
                    stop = candidate
                    lock_updates += 1
    if exit_i is None:
        candidates = [i for i in range(entry_i, len(h1)) if h1[i]["dt"] < deadline]
        if not candidates:
            return None
        exit_i = candidates[-1]
        exit_price = float(h1[exit_i]["close"])
    gross_r = (exit_price - entry_price) / risk if side == "LONG" else (entry_price - exit_price) / risk
    return {"symbol": SYMBOL, "timeframe": "H1_EXECUTION_ON_D1_SETUP", "setup": "EXPANSION_BREAKOUT", "side": side, "entry_at": h1[entry_i]["dt"].isoformat(), "exit_at": h1[exit_i]["dt"].isoformat(), "entry_price": round(entry_price, 6), "structural_stop": round(structural_stop, 6), "structural_target": round(structural_target, 6), "final_stop": round(stop, 6), "actual_risk_price": round(risk, 6), "gross_r": round(gross_r, 6), "net_r": round(gross_r - BASE_COST_R, 6), "cost_r": BASE_COST_R, "exit_reason": exit_reason, "entry_reason": entry_reason, "management": management, "profit_lock_updates": lock_updates, "mfe_r": round(max_favorable_r, 6), "mae_r": round(max_adverse_r, 6)}


def panel(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {"base_0_05R": metrics(reprice(trades, 0.05)), "stress_0_10R": metrics(reprice(trades, 0.10)), "severe_0_15R": metrics(reprice(trades, 0.15))}


def replay_boundary(history, boundary: int, cfg) -> dict[str, Any]:
    daily = as_rows(history, boundary)
    ind = indicators(daily)
    daily_index = {row["dt"].isoformat(): i for i, row in enumerate(daily)}
    baseline = period(generate_trades(daily, cfg), CONFIRM_START, CONFIRM_END)
    h1 = h1_rows(history)
    h1_times = [row["dt"] for row in h1]
    h4 = build_h4(h1)
    variants = {f"{entry}+{mgmt}": [] for entry in ENTRY_MODES for mgmt in MANAGEMENT_MODES}
    skips = {key: {"no_fill": 0, "overlap": 0, "invalid": 0} for key in variants}
    last_exit: dict[str, datetime | None] = {key: None for key in variants}
    for base in baseline:
        signal_i = daily_index.get(base["signal_at"])
        if signal_i is None or signal_i + 1 >= len(daily):
            continue
        atr = ind["atr"][signal_i]
        if atr is None or atr <= 0:
            continue
        side = str(base["side"])
        entry_daily_i = signal_i + 1
        baseline_entry = float(daily[entry_daily_i]["open"])
        baseline_risk = float(cfg.stop_atr * atr)
        structural_stop = baseline_entry - baseline_risk if side == "LONG" else baseline_entry + baseline_risk
        structural_target = baseline_entry + cfg.rr * baseline_risk if side == "LONG" else baseline_entry - cfg.rr * baseline_risk
        start = daily[entry_daily_i]["dt"]
        hold_i = min(len(daily) - 1, entry_daily_i + cfg.max_hold)
        deadline = daily[hold_i]["dt"] + timedelta(hours=24)
        for entry_mode in ENTRY_MODES:
            chosen = choose_entry(entry_mode, side=side, baseline_entry=baseline_entry, baseline_risk=baseline_risk, start=start, h1=h1, h1_times=h1_times, h4=h4)
            for management in MANAGEMENT_MODES:
                key = f"{entry_mode}+{management}"
                if chosen is None:
                    skips[key]["no_fill"] += 1
                    continue
                entry_i, entry_price, entry_reason = chosen
                prior_exit = last_exit[key]
                if prior_exit is not None and h1[entry_i]["dt"] <= prior_exit:
                    skips[key]["overlap"] += 1
                    continue
                trade = simulate(side=side, entry_i=entry_i, entry_price=entry_price, structural_stop=structural_stop, structural_target=structural_target, deadline=deadline, h1=h1, management=management, entry_reason=entry_reason)
                if trade is None:
                    skips[key]["invalid"] += 1
                    continue
                trade.update({"signal_at": base["signal_at"], "param_config": cfg.config_id, "entry_mode": entry_mode, "d1_boundary_hour_utc": boundary, "baseline_entry": round(baseline_entry, 6), "baseline_risk_price": round(baseline_risk, 6), "entry_delay_hours": round((h1[entry_i]["dt"] - start).total_seconds() / 3600.0, 3)})
                variants[key].append(trade)
                last_exit[key] = datetime.fromisoformat(trade["exit_at"])
    return {"boundary_hour_utc": boundary, "daily_bars": len(daily), "baseline_signal_count": len(baseline), "variants": {key: {"panel": panel(trades), "coverage_vs_baseline": round(len(trades) / len(baseline), 4) if baseline else 0.0, "skips": skips[key], "trade_count": len(trades), "trades": trades} for key, trades in variants.items()}}


def robust_summary(boundaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    keys = list(boundaries[0]["variants"].keys()) if boundaries else []
    for key in keys:
        stress = [b["variants"][key]["panel"]["stress_0_10R"] for b in boundaries]
        severe = [b["variants"][key]["panel"]["severe_0_15R"] for b in boundaries]
        coverage = [b["variants"][key]["coverage_vs_baseline"] for b in boundaries]
        valid = [x for x in stress if int(x.get("trades", 0) or 0) > 0]
        positive = sum(int(x.get("trades", 0) or 0) >= 8 and float(x.get("expectancy_r", 0.0) or 0.0) > 0 and float(x.get("profit_factor", 0.0) or 0.0) > 1.0 for x in stress)
        severe_positive = sum(int(x.get("trades", 0) or 0) >= 8 and float(x.get("expectancy_r", 0.0) or 0.0) > 0 and float(x.get("profit_factor", 0.0) or 0.0) > 1.0 for x in severe)
        med_exp = statistics.median(float(x.get("expectancy_r", 0.0) or 0.0) for x in valid) if valid else 0.0
        med_pf = statistics.median(float(x.get("profit_factor", 0.0) or 0.0) for x in valid) if valid else 0.0
        med_net = statistics.median(float(x.get("net_r", 0.0) or 0.0) for x in valid) if valid else 0.0
        med_cov = statistics.median(coverage) if coverage else 0.0
        quality = bool(positive >= 2 and severe_positive >= 2 and med_exp >= 0.15 and med_pf >= 1.50 and med_cov >= 0.50)
        score = med_exp + 0.10 * math.log(max(med_pf, 1e-9)) + 0.05 * med_cov
        rows.append({"variant": key, "positive_boundaries_stress": positive, "positive_boundaries_severe": severe_positive, "median_stress_net_r": round(med_net, 6), "median_stress_expectancy_r": round(med_exp, 6), "median_stress_profit_factor": round(med_pf, 4), "median_coverage": round(med_cov, 4), "research_quality_target": quality, "ranking_score": round(score, 6)})
    rows.sort(key=lambda x: (x["research_quality_target"], x["ranking_score"], x["variant"]), reverse=True)
    return rows


def main() -> None:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_V41_RESEARCH_DEMO_ONLY")
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
    boundaries = [replay_boundary(history, boundary, cfg) for boundary in BOUNDARY_HOURS_UTC]
    robustness = robust_summary(boundaries)
    result = {"schema_version": "XAU_EXPANSION_V41_INTRADAY_TIMING", "research_only": True, "execution_influence": False, "live_execution_enabled": False, "promotion_eligible": False, "promotion_block_reason": "2024-2026 broker history is research-reused; fresh untouched forward evidence required", "symbol": SYMBOL, "d1_setup_config": cfg.__dict__, "confirmation_window": [str(CONFIRM_START), str(CONFIRM_END)], "h1_coverage": {"rows": len(history), "start": history[0].timestamp.isoformat() if history else None, "end": history[-1].timestamp.isoformat() if history else None}, "daily_boundaries_utc": list(BOUNDARY_HOURS_UTC), "entry_modes": list(ENTRY_MODES), "management_modes": list(MANAGEMENT_MODES), "runtime_lock_contract": {"activation_r": 0.50, "stages": {"0.50": 0.05, "0.80": 0.25, "1.20": 0.55, "1.80": 1.00, "2.50+": "favorable_r-0.75"}, "bar_close_decision_next_bar_effect": True}, "method": {"fixed_d1_setup": CONFIG_ID, "h1_same_bar_policy": "STOP_FIRST", "pullback_fill_bar_policy": "FILL_THEN_STOP_IF_STOP_TOUCHED", "structural_stop_and_target_frozen_from_d1_signal": True, "entry_window_hours": ENTRY_WINDOW_HOURS, "boundary_results_are_robustness_replicas_not_pooled_independent_samples": True, "costs_r": [0.05, 0.10, 0.15]}, "robustness": robustness, "best_research_variant": robustness[0]["variant"] if robustness else None, "boundaries": boundaries}
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, allow_nan=False))
    for row in robustness:
        print("ROBUST", row["variant"], "pos=", row["positive_boundaries_stress"], "severe_pos=", row["positive_boundaries_severe"], "median_net=", row["median_stress_net_r"], "median_exp=", row["median_stress_expectancy_r"], "median_pf=", row["median_stress_profit_factor"], "coverage=", row["median_coverage"], "quality=", row["research_quality_target"])
    for b in boundaries:
        for key, item in b["variants"].items():
            m = item["panel"]["stress_0_10R"]
            print("BOUNDARY", b["boundary_hour_utc"], key, "n=", m.get("trades"), "wr=", m.get("win_rate"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"), "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"))


if __name__ == "__main__":
    main()
