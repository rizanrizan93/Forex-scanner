from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from .research_xau_entry_tp_precision_v284 import (
    EXECUTION_AUTHORITY, EXECUTION_INFLUENCE, RESEARCH_VERSION, replay_plan,
)
from .research_xau_v229_historical_v242 import price_arrays, simulate_year
from .research_xau_v229_historical_v242_year_runtime import _download, _year


def run() -> int:
    year = _year()
    csv = Path(os.getenv("XAU_V284_PRICE_CSV", f"/tmp/histdata/xau-v284-{year}.csv"))
    provenance_path = Path(os.getenv("XAU_V284_PROVENANCE", f"artifacts/xau-v284-provenance-{year}.json"))
    output = Path(os.getenv("XAU_V284_OUTPUT", f"artifacts/xau-entry-tp-precision-v284-{year}.json"))
    provenance = _download(year, csv, provenance_path)
    price = pd.read_csv(csv)
    price["timestamp"] = pd.to_datetime(price["timestamp"], utc=True)
    for name in ("open", "high", "low", "close"):
        price[name] = pd.to_numeric(price[name], errors="raise")
    v242 = simulate_year(price, target_year=year)
    px = price_arrays(price)
    rows = [replay_plan(plan, px) for plan in v242["plans"]]
    payload = {
        "research_version": RESEARCH_VERSION, "year": year,
        "price_provenance": provenance, "price_end": px.timestamps[-1].isoformat(),
        "parent_plans": len(v242["plans"]), "censored_plans": sum(bool(row["censored"]) for row in rows),
        "rows": rows, "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"V284_YEAR year={year} plans={len(rows)} censored={payload['censored_plans']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
