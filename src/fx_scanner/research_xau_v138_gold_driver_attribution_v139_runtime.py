from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_v138_gold_driver_attribution_v139 import (
    FRED_SERIES,
    evaluate_v139,
)

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


def _load_series(series_id: str) -> tuple[dict[date, float], dict]:
    url = _fred_url(series_id)
    frame = pd.read_csv(url)
    if frame.empty or frame.shape[1] < 2:
        raise RuntimeError(f"FRED_EMPTY:{series_id}")
    date_col, value_col = frame.columns[:2]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    frame = frame.dropna(subset=[date_col, value_col]).sort_values(date_col)
    values = {
        ts.date(): float(v)
        for ts, v in zip(frame[date_col], frame[value_col], strict=True)
    }
    if not values:
        raise RuntimeError(f"FRED_ONLY_MISSING:{series_id}")
    latest = max(values)
    return values, {
        "series_id": series_id,
        "url": url,
        "rows": len(values),
        "first_observation": min(values).isoformat(),
        "latest_observation": latest.isoformat(),
        "latest_value": values[latest],
    }


def _load_macro():
    series = {}
    metadata = {}
    for key, series_id in FRED_SERIES.items():
        values, meta = _load_series(series_id)
        series[key] = values
        metadata[key] = meta
    return series, metadata


def _compact(block, horizon="5d"):
    return {
        k: {
            "n": v[horizon]["n"],
            "mean": v[horizon]["mean"],
            "hit_rate": v[horizon]["hit_rate"],
        }
        for k, v in block.items()
    }


def _print_era(label, block):
    print(
        "V139_ERA "
        + json.dumps(
            {
                "era": label,
                "rows": block["rows"],
                "all_5d": block["all"]["5d"],
                "all_20d": block["all"]["20d"],
                "opp_5d": _compact(block["opportunity_cost"], "5d"),
                "risk_5d": _compact(block["risk"], "5d"),
                "momentum_5d": _compact(block["momentum"], "5d"),
            },
            sort_keys=True,
        )
    )


def run():
    bars = _fetch(CONT)
    macro, metadata = _load_macro()
    data = evaluate_v139(
        bars,
        macro_series=macro,
        evaluation_end=CONT["end"],
    )
    data["macro_source_metadata"] = metadata

    path = Path(
        os.getenv(
            "V139_EVIDENCE_OUTPUT",
            "artifacts/xau-v138-gold-driver-attribution-v139.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    for key, meta in metadata.items():
        print("V139_SOURCE " + json.dumps({"key": key, **meta}, sort_keys=True))
    _print_era("2012_2018", data["era_2012_2018"])
    _print_era("2019_2024", data["era_2019_2024"])
    _print_era("2025_2026", data["era_2025_2026"])
    print("V139_DECISION " + json.dumps({"diagnostic_only": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
