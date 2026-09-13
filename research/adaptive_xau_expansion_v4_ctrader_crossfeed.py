from __future__ import annotations

import json
from datetime import date

from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.research_xau_d1_tsmom_crossfeed_v1 import BOUNDARY_HOURS_UTC
from adaptive_xau_ctrader_crossfeed_v1 import fetch_history, as_rows, period
from adaptive_xau_expansion_v4_walkforward import param_grid, generate_trades, reprice
from adaptive_router_public_backtest import metrics

SYMBOL = "XAUUSD"
PRIMARY_CONFIGS = ("S2R0T0H0", "S2R2T2H0", "S1R1T1H1")
CONFIRM_START = date(2024, 1, 1)
CONFIRM_END = date(2026, 8, 31)


def summarize(trades):
    return {
        "base_0_05R": metrics(reprice(trades, 0.05)),
        "stress_0_10R": metrics(reprice(trades, 0.10)),
        "severe_0_15R": metrics(reprice(trades, 0.15)),
    }


def main() -> None:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_CROSSFEED_DEMO_ONLY")
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        history = fetch_history(feed)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    configs = {c.config_id: c for c in param_grid()}
    boundaries = []
    positive_counts = {k: 0 for k in PRIMARY_CONFIGS}
    for boundary in BOUNDARY_HOURS_UTC:
        rows = as_rows(history, boundary)
        cfg_rows = {}
        for config_id in PRIMARY_CONFIGS:
            cfg = configs[config_id]
            confirm = period(generate_trades(rows, cfg), CONFIRM_START, CONFIRM_END)
            stats = summarize(confirm)
            stress = stats["stress_0_10R"]
            positive = bool(stress.get("trades", 0) >= 8 and (stress.get("expectancy_r") or -9) > 0 and (stress.get("profit_factor") or 0) > 1.0)
            positive_counts[config_id] += int(positive)
            cfg_rows[config_id] = {"config": cfg.__dict__, "confirm": stats, "positive": positive}
        boundaries.append({"boundary_hour_utc": boundary, "daily_bars": len(rows), "configs": cfg_rows})

    primary = "S2R2T2H0"
    result = {
        "schema_version": "XAU_EXPANSION_V4_CTRADER_CROSSFEED",
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "confirmation_source": "cTrader DEMO broker H1 resampled locally",
        "h1_coverage": {"rows": len(history), "start": history[0].timestamp.isoformat() if history else None, "end": history[-1].timestamp.isoformat() if history else None},
        "confirmation_window": [str(CONFIRM_START), str(CONFIRM_END)],
        "daily_boundary_hours_utc": list(BOUNDARY_HOURS_UTC),
        "predefined_configs": list(PRIMARY_CONFIGS),
        "positive_boundary_counts": positive_counts,
        "primary_config": primary,
        "primary_crossfeed_pass": positive_counts[primary] >= 2,
        "boundaries": boundaries,
    }
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    print("PRIMARY_PASS", result["primary_crossfeed_pass"], "positive_boundaries=", positive_counts[primary])
    for row in boundaries:
        for cid in PRIMARY_CONFIGS:
            m = row["configs"][cid]["confirm"]["stress_0_10R"]
            print("BOUNDARY", row["boundary_hour_utc"], cid, "n=", m.get("trades"), "wr=", m.get("win_rate"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"), "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"))


if __name__ == "__main__":
    main()
