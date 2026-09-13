from __future__ import annotations

import json
from datetime import datetime, timezone

from adaptive_router_public_backtest import fetch_daily, metrics
from adaptive_xau_expansion_v4_walkforward import (
    SYMBOL, param_grid, generate_trades, choose, period, reprice,
)

VERSION = "XAU_EXPANSION_V4_TRAILING_EDGE_GATE"
LOOKBACK = 8
EDGE_COST_R = 0.10


def edge_stats(trades):
    xs = reprice(trades, EDGE_COST_R)
    rs = [float(x["net_r"]) for x in xs]
    if not rs:
        return {"n": 0, "exp": 0.0, "pf": 0.0}
    gp = sum(x for x in rs if x > 0)
    gl = abs(sum(x for x in rs if x <= 0))
    return {"n": len(rs), "exp": sum(rs) / len(rs), "pf": gp / gl if gl > 0 else 99.0}


def apply_gate(stream, start, end):
    start_dt = datetime.fromisoformat(start + "T00:00:00+00:00")
    end_dt = datetime.fromisoformat(end + "T23:59:59+00:00")
    selected = []
    skipped = []
    for t in stream:
        signal = datetime.fromisoformat(t["signal_at"])
        if signal < start_dt or signal > end_dt:
            continue
        prior = [x for x in stream if datetime.fromisoformat(x["exit_at"]) < signal]
        recent = prior[-LOOKBACK:]
        st = edge_stats(recent)
        gate_open = st["n"] < LOOKBACK or (st["exp"] > 0.0 and st["pf"] > 1.0)
        x = dict(t)
        x["edge_gate"] = {"lookback": LOOKBACK, "n": st["n"], "exp": round(st["exp"], 6), "pf": round(st["pf"], 4), "open": gate_open}
        (selected if gate_open else skipped).append(x)
    return selected, skipped


def panel(trades):
    return {
        "base_0_05R": metrics(reprice(trades, 0.05)),
        "stress_0_10R": metrics(reprice(trades, 0.10)),
        "severe_0_15R": metrics(reprice(trades, 0.15)),
    }


def main():
    rows, source = fetch_daily(SYMBOL)
    configs = param_grid()
    streams = {c.config_id: generate_trades(rows, c) for c in configs}
    folds = [
        ("F1", "2016-12-31", "2017-02-01", "2018-12-31"),
        ("F2", "2018-12-31", "2019-02-01", "2020-12-31"),
        ("F3", "2020-12-31", "2021-02-01", "2022-12-31"),
        ("F4", "2022-12-31", "2023-02-01", "2024-12-31"),
        ("F5", "2024-12-31", "2025-02-01", "2026-09-30"),
    ]
    gated_all = []
    ungated_all = []
    fold_rows = []
    for fold_id, train_end, test_start, test_end in folds:
        chosen, selection = choose(configs, streams, train_end)
        if chosen is None:
            fold_rows.append({"fold": fold_id, "chosen_config": "NO_TRADE", "selected": {"trades": 0}, "skipped": 0})
            continue
        ungated = period(streams[chosen.config_id], test_start, test_end)
        gated, skipped = apply_gate(streams[chosen.config_id], test_start, test_end)
        for x in gated:
            y = dict(x); y["fold"] = fold_id; gated_all.append(y)
        for x in ungated:
            y = dict(x); y["fold"] = fold_id; ungated_all.append(y)
        fold_rows.append({
            "fold": fold_id,
            "chosen_config": chosen.config_id,
            "selection": selection,
            "ungated_stress": metrics(reprice(ungated, 0.10)),
            "gated_stress": metrics(reprice(gated, 0.10)),
            "skipped": len(skipped),
            "skipped_shadow_net_r_stress": round(sum(float(x["gross_r"]) - 0.10 for x in skipped), 4),
        })
        gm = fold_rows[-1]["gated_stress"]
        print("FOLD", fold_id, chosen.config_id, "gated_n=", gm.get("trades"), "net_r=", gm.get("net_r"), "exp=", gm.get("expectancy_r"), "pf=", gm.get("profit_factor"), "skipped=", len(skipped))

    result = {
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": source,
        "gate": {"lookback_completed_shadow_trades": LOOKBACK, "edge_cost_r": EDGE_COST_R, "allow_when": "warmup OR trailing expectancy > 0 and PF > 1.0", "shadow_updates_while_suspended": True},
        "method_note": "Exploratory overlay designed after observing V4 F3 weakness; not an untouched holdout. Gate itself uses only outcomes completed before each signal.",
        "folds": fold_rows,
        "ungated_oos": panel(ungated_all),
        "gated_oos": panel(gated_all),
        "gated_trade_count": len(gated_all),
        "gated_trades": gated_all,
    }
    print("RESULT_JSON=" + json.dumps(result, separators=(",", ":"), default=str))
    for label, m in (("UNGATED", result["ungated_oos"]["stress_0_10R"]), ("GATED", result["gated_oos"]["stress_0_10R"])):
        print(label, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"), "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"))


if __name__ == "__main__":
    main()
