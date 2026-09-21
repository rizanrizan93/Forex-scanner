from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
)
from .research_xau_v134_h3_robustness_v135 import evaluate_v135

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _net(m):
    return float(m["gross_profit_r"]) - float(m["gross_loss_r"])


def _positive_if_exposed(m):
    return int(m["completed_trades"]) == 0 or (
        m["expectancy_r"] is not None and float(m["expectancy_r"]) >= 0.0
    )


def _start_slices_pass(block):
    for row in block["start_sensitivity"].values():
        m = row["metrics"]
        if int(m["completed_trades"]) >= 100:
            if m["expectancy_r"] is None or float(m["expectancy_r"]) <= 0.0:
                return False
            if m["profit_factor"] is None or float(m["profit_factor"]) <= 1.0:
                return False
    return True


def _passes(data):
    b = data["baseline"]
    s = data["super_stress"]
    l = data["one_h1_bar_lag"]

    bfull = b["full_metrics"]
    if int(bfull["completed_trades"]) != 494:
        return False
    if bfull["profit_factor"] is None or abs(float(bfull["profit_factor"]) - 1.3049416149604438) > 1e-9:
        return False
    if bfull["expectancy_r"] is None or abs(float(bfull["expectancy_r"]) - 0.10983223713497409) > 1e-9:
        return False

    if int(b["full_live100"]["opened"]) < 30 or float(b["full_live100"]["ending_balance_usd"]) <= 100.0:
        return False

    sm = s["full_metrics"]
    if sm["expectancy_r"] is None or float(sm["expectancy_r"]) <= 0.0:
        return False
    if float(sm["max_drawdown_r"]) > 20.0:
        return False
    if not _positive_if_exposed(s["pre2025_metrics"]):
        return False
    sr = s["recent_metrics"]
    if sr["expectancy_r"] is None or float(sr["expectancy_r"]) < 0.08:
        return False

    lm = l["full_metrics"]
    if lm["expectancy_r"] is None or float(lm["expectancy_r"]) <= 0.0:
        return False
    if not _positive_if_exposed(l["pre2025_metrics"]):
        return False
    lr = l["recent_metrics"]
    if lr["expectancy_r"] is None or float(lr["expectancy_r"]) < 0.08:
        return False

    return _start_slices_pass(b) and _start_slices_pass(s) and _start_slices_pass(l)


def _line(label, block):
    full = block["full_metrics"]
    pre = block["pre2025_metrics"]
    recent = block["recent_metrics"]
    live = block["full_live100"]
    rlive = block["recent_live100"]
    print(
        "V135_BLOCK "
        + json.dumps(
            {
                "block": label,
                "n": full["completed_trades"],
                "pf": full["profit_factor"],
                "exp": full["expectancy_r"],
                "net_r": _net(full),
                "dd_r": full["max_drawdown_r"],
                "pre_n": pre["completed_trades"],
                "pre_pf": pre["profit_factor"],
                "pre_exp": pre["expectancy_r"],
                "recent_n": recent["completed_trades"],
                "recent_pf": recent["profit_factor"],
                "recent_exp": recent["expectancy_r"],
                "full_live100_opened": live["opened"],
                "full_live100_ending": live["ending_balance_usd"],
                "recent_live100_opened": rlive["opened"],
                "recent_live100_ending": rlive["ending_balance_usd"],
            },
            sort_keys=True,
        )
    )
    for start, row in block["start_sensitivity"].items():
        m = row["metrics"]
        sim = row["live100"]
        print(
            "V135_START "
            + json.dumps(
                {
                    "block": label,
                    "start": start,
                    "n": m["completed_trades"],
                    "pf": m["profit_factor"],
                    "exp": m["expectancy_r"],
                    "dd_r": m["max_drawdown_r"],
                    "live100_opened": sim["opened"],
                    "live100_ending": sim["ending_balance_usd"],
                },
                sort_keys=True,
            )
        )


def run():
    bars = _fetch(CONT)
    super_stress = COST_SCENARIOS["V24_STRESS_4675"].stressed(
        spread_multiplier=1.25,
        slippage_multiplier=1.25,
    )
    data = evaluate_v135(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        baseline_costs=COST_SCENARIOS["V24_STRESS_4675"],
        super_stress_costs=super_stress,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    path = Path(
        os.getenv("V135_EVIDENCE_OUTPUT", "artifacts/xau-v134-h3-robustness-v135.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    _line("BASELINE", data["baseline"])
    _line("SUPER_STRESS", data["super_stress"])
    _line("H1_LAG_1BAR", data["one_h1_bar_lag"])
    print("V135_DECISION " + json.dumps({"passes": _passes(data)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
