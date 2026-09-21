from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch
from .research_xau_v135_macro_regime_v136_runtime import _load_fred_series, _load_macro
from .research_xau_v137_cftc_positioning_forensic_v138_runtime import _load_cftc
from .research_xau_v138_driver_interaction_forensic_v139 import DRIVER_SERIES, evaluate_v139

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _load_driver_series():
    series = {}
    meta = {}
    for key, series_id in DRIVER_SERIES.items():
        values, source = _load_fred_series(series_id)
        series[key] = values
        meta[key] = source
    return series, meta


def _compact(m):
    return {
        "n": m["completed_trades"],
        "pf": m["profit_factor"],
        "exp": m["expectancy_r"],
        "dd": m["max_drawdown_r"],
    }


def _line(label, block):
    ext = block["extended_strong_bull"]
    print(
        "V139_PERIOD "
        + json.dumps(
            {
                "period": label,
                "all": _compact(block["metrics"]),
                "opportunity": {k: _compact(v) for k, v in block["by_opportunity"].items()},
                "risk": {k: _compact(v) for k, v in block["by_risk"].items()},
                "inflation": {k: _compact(v) for k, v in block["by_inflation"].items()},
                "extended_strong": {
                    "n": ext["count"],
                    "all": _compact(ext["metrics"]),
                    "opportunity_x_risk": {
                        k: _compact(v) for k, v in ext["opportunity_x_risk"].items()
                    },
                    "risk_x_cot": {
                        k: _compact(v) for k, v in ext["risk_x_cot"].items()
                    },
                    "risk_x_cot_x_oi": {
                        k: _compact(v) for k, v in ext["risk_x_cot_x_oi"].items()
                    },
                },
            },
            sort_keys=True,
        )
    )


def run():
    bars = _fetch(CONT)
    macro, macro_meta = _load_macro()
    drivers, driver_meta = _load_driver_series()
    cot_rows, cot_meta = _load_cftc()

    data = evaluate_v139(
        bars,
        macro_series=macro,
        driver_series=drivers,
        cot_raw_rows=cot_rows,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
    )
    data["macro_source_metadata"] = macro_meta
    data["driver_source_metadata"] = driver_meta
    data["cftc_source_metadata"] = cot_meta

    path = Path(
        os.getenv(
            "V139_EVIDENCE_OUTPUT",
            "artifacts/xau-v138-driver-interaction-forensic-v139.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    _line("FULL", data["full"])
    _line("PRE2025", data["pre2025"])
    _line("RECENT", data["recent"])
    print("V139_DECISION " + json.dumps({"diagnostic_only": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
