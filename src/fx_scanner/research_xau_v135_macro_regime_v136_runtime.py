from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
)
from .research_xau_v135_macro_regime_v136 import FRED_SERIES, evaluate_v136

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _fred_url(series_id: str) -> str:
    query = urlencode(
        {
            "id": series_id,
            "cosd": "2011-01-01",
            "coed": CONT["end"].date().isoformat(),
        }
    )
    return "https://fred.stlouisfed.org/graph/fredgraph.csv?" + query


def _load_fred_series(series_id: str) -> tuple[dict[date, float], dict]:
    url = _fred_url(series_id)
    frame = pd.read_csv(url)
    if frame.empty or frame.shape[1] < 2:
        raise RuntimeError(f"FRED series {series_id} returned no usable rows")
    date_col = frame.columns[0]
    value_col = frame.columns[1]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    frame = frame.dropna(subset=[date_col, value_col]).sort_values(date_col)
    values = {
        ts.date(): float(value)
        for ts, value in zip(frame[date_col], frame[value_col], strict=True)
    }
    if not values:
        raise RuntimeError(f"FRED series {series_id} had only missing observations")
    latest = max(values)
    return values, {
        "series_id": series_id,
        "url": url,
        "rows": len(values),
        "first_observation": min(values).isoformat(),
        "latest_observation": latest.isoformat(),
        "latest_value": values[latest],
    }


def _load_macro() -> tuple[dict[str, dict[date, float]], dict]:
    series = {}
    metadata = {}
    for key, series_id in FRED_SERIES.items():
        values, meta = _load_fred_series(series_id)
        series[key] = values
        metadata[key] = meta
    return series, metadata


def _positive_if_exposed(m):
    return int(m["completed_trades"]) == 0 or (
        m["expectancy_r"] is not None and float(m["expectancy_r"]) >= 0.0
    )


def _gt_zero(m):
    return m["expectancy_r"] is not None and float(m["expectancy_r"]) > 0.0


def _min_exp(m, floor):
    return m["expectancy_r"] is not None and float(m["expectancy_r"]) >= floor


def _passes(data):
    b = data["baseline"]
    s = data["super_stress"]
    l = data["one_h1_bar_lag"]

    coverage = b["macro_full"]["coverage"]
    if coverage is None or float(coverage) < 0.95:
        return False
    if b["retention"] is None or float(b["retention"]) < 0.50:
        return False

    if not _gt_zero(b["gated_metrics"]):
        return False
    if not _positive_if_exposed(b["gated_pre2025_metrics"]):
        return False
    if not _min_exp(b["gated_recent_metrics"], 0.10):
        return False

    if not _gt_zero(s["gated_metrics"]):
        return False
    if not _positive_if_exposed(s["gated_pre2025_metrics"]):
        return False
    if not _min_exp(s["gated_recent_metrics"], 0.08):
        return False

    if not _gt_zero(l["gated_metrics"]):
        return False
    if not _positive_if_exposed(l["gated_pre2025_metrics"]):
        return False
    if not _min_exp(l["gated_recent_metrics"], 0.08):
        return False

    if float(s["gated_full_live100"]["ending_balance_usd"]) <= 100.0:
        return False
    if float(l["gated_full_live100"]["ending_balance_usd"]) <= 100.0:
        return False
    return True


def _print_block(label, block):
    m = block["gated_metrics"]
    pre = block["gated_pre2025_metrics"]
    recent = block["gated_recent_metrics"]
    live = block["gated_full_live100"]
    macro = block["macro_full"]
    print(
        "V136_BLOCK "
        + json.dumps(
            {
                "block": label,
                "gated_n": m["completed_trades"],
                "gated_pf": m["profit_factor"],
                "gated_exp": m["expectancy_r"],
                "gated_dd_r": m["max_drawdown_r"],
                "pre_n": pre["completed_trades"],
                "pre_pf": pre["profit_factor"],
                "pre_exp": pre["expectancy_r"],
                "recent_n": recent["completed_trades"],
                "recent_pf": recent["profit_factor"],
                "recent_exp": recent["expectancy_r"],
                "retention": block["retention"],
                "macro_coverage": macro["coverage"],
                "supportive": macro["supportive"],
                "mixed": macro["mixed"],
                "hostile": macro["hostile"],
                "unknown": macro["unknown"],
                "live100_opened": live["opened"],
                "live100_ending": live["ending_balance_usd"],
            },
            sort_keys=True,
        )
    )


def run():
    bars = _fetch(CONT)
    macro_series, macro_metadata = _load_macro()
    super_stress = COST_SCENARIOS["V24_STRESS_4675"].stressed(
        spread_multiplier=1.25,
        slippage_multiplier=1.25,
    )
    data = evaluate_v136(
        bars,
        macro_series=macro_series,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        baseline_costs=COST_SCENARIOS["V24_STRESS_4675"],
        super_stress_costs=super_stress,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    data["macro_source_metadata"] = macro_metadata
    data["decision"] = {"passes": _passes(data)}

    path = Path(
        os.getenv(
            "V136_EVIDENCE_OUTPUT",
            "artifacts/xau-v135-macro-regime-v136.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    for key, meta in macro_metadata.items():
        print("V136_SOURCE " + json.dumps({"key": key, **meta}, sort_keys=True))
    _print_block("BASELINE", data["baseline"])
    _print_block("SUPER_STRESS", data["super_stress"])
    _print_block("H1_LAG_1BAR", data["one_h1_bar_lag"])
    print("V136_DECISION " + json.dumps(data["decision"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
