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
from .research_xau_v132_h1_confirmation_v134 import evaluate_v134

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _net(m):
    return float(m["gross_profit_r"]) - float(m["gross_loss_r"])


def _passes(row):
    full = row["full_metrics"]
    pre = row["pre2025_metrics"]
    if int(full["completed_trades"]) < 100:
        return False
    if full["profit_factor"] is None or float(full["profit_factor"]) < 1.15:
        return False
    if full["expectancy_r"] is None or float(full["expectancy_r"]) < 0.05:
        return False
    if float(full["max_drawdown_r"]) > 20.0:
        return False
    if int(pre["completed_trades"]) < 50:
        return False
    if pre["expectancy_r"] is None or float(pre["expectancy_r"]) < 0.0:
        return False
    for era in ("2012_2018", "2019_2024"):
        m = row["eras"][era]["metrics"]
        if int(m["completed_trades"]) > 0 and (
            m["expectancy_r"] is None or float(m["expectancy_r"]) < 0.0
        ):
            return False
    recent = row["eras"]["2025_2026YTD"]
    rm = recent["metrics"]
    if int(rm["completed_trades"]) < 100:
        return False
    if rm["profit_factor"] is None or float(rm["profit_factor"]) < 1.30:
        return False
    if rm["expectancy_r"] is None or float(rm["expectancy_r"]) < 0.10:
        return False
    sim = recent["scenarios"]["LIVE_100_1_100_CAP50"]
    sm = sim["accepted_metrics"]
    if int(sim["opened"]) < 30:
        return False
    if sm["profit_factor"] is None or float(sm["profit_factor"]) < 1.20:
        return False
    if sm["expectancy_r"] is None or float(sm["expectancy_r"]) <= 0.0:
        return False
    if float(sim["ending_balance_usd"]) <= 100.0:
        return False
    return True


def run():
    bars = _fetch(CONT)
    data = evaluate_v134(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    path = Path(
        os.getenv("V134_EVIDENCE_OUTPUT", "artifacts/xau-v132-h1-confirmation-v134.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    for cid, row in data["candidates"].items():
        m = row["full_metrics"]
        pre = row["pre2025_metrics"]
        print(
            "V134_FULL "
            + json.dumps(
                {
                    "candidate": cid,
                    "n": m["completed_trades"],
                    "pf": m["profit_factor"],
                    "exp": m["expectancy_r"],
                    "net_r": _net(m),
                    "dd_r": m["max_drawdown_r"],
                    "pre_n": pre["completed_trades"],
                    "pre_exp": pre["expectancy_r"],
                    "passes": _passes(row),
                },
                sort_keys=True,
            )
        )
        for era in ("2012_2018", "2019_2024", "2025_2026YTD"):
            e = row["eras"][era]
            mm = e["metrics"]
            out = {
                "candidate": cid,
                "era": era,
                "n": mm["completed_trades"],
                "pf": mm["profit_factor"],
                "exp": mm["expectancy_r"],
                "net_r": _net(mm),
                "dd_r": mm["max_drawdown_r"],
            }
            if era == "2025_2026YTD":
                sim = e["scenarios"]["LIVE_100_1_100_CAP50"]
                sm = sim["accepted_metrics"]
                out.update(
                    {
                        "live100_opened": sim["opened"],
                        "live100_ending": sim["ending_balance_usd"],
                        "live100_pf": sm["profit_factor"],
                        "live100_exp": sm["expectancy_r"],
                    }
                )
            print("V134_ERA " + json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
