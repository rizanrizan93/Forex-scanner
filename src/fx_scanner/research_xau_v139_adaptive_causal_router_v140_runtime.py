from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC, COST_SCENARIOS, LEVERAGE_TIERS, _fetch
from .research_xau_v135_macro_regime_v136_runtime import _load_macro
from .research_xau_v137_cftc_positioning_forensic_v138_runtime import _load_cftc
from .research_xau_v138_driver_interaction_forensic_v139_runtime import _load_driver_series
from .research_xau_v139_adaptive_causal_router_v140 import evaluate_v140

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _compact(m):
    return {
        "n": m["completed_trades"],
        "pf": m["profit_factor"],
        "exp": m["expectancy_r"],
        "dd_r": m["max_drawdown_r"],
    }


def run():
    bars = _fetch(CONT)
    macro, macro_meta = _load_macro()
    drivers, driver_meta = _load_driver_series()
    cot_rows, cot_meta = _load_cftc()

    data = evaluate_v140(
        bars,
        macro_series=macro,
        driver_series=drivers,
        cot_raw_rows=cot_rows,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    data["macro_source_metadata"] = macro_meta
    data["driver_source_metadata"] = driver_meta
    data["cftc_source_metadata"] = cot_meta

    path = Path(os.getenv("V140_EVIDENCE_OUTPUT", "artifacts/xau-v139-adaptive-causal-router-v140.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    for cid, block in data["candidates"].items():
        live = block["full_live100"]
        recent = block["eras"]["2025_2026YTD"]
        rlive = recent["live100"]
        print("V140_CANDIDATE " + json.dumps({
            "candidate": cid,
            **_compact(block["full_metrics"]),
            "live100_opened": live["opened"],
            "live100_ending": live["ending_balance_usd"],
            "live100_return_pct": live["return_pct"],
            "live100_max_dd_pct": live["max_realized_drawdown_pct"],
            "recent_n": recent["metrics"]["completed_trades"],
            "recent_pf": recent["metrics"]["profit_factor"],
            "recent_exp": recent["metrics"]["expectancy_r"],
            "recent_live100_opened": rlive["opened"],
            "recent_live100_ending": rlive["ending_balance_usd"],
        }, sort_keys=True))
        for start, row in block["start_sensitivity"].items():
            print("V140_START " + json.dumps({
                "candidate": cid,
                "start": start,
                **_compact(row["metrics"]),
                "live100_opened": row["live100"]["opened"],
                "live100_ending": row["live100"]["ending_balance_usd"],
            }, sort_keys=True))
    print("V140_DECISION " + json.dumps({"research_only": True, "production_promotion": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
