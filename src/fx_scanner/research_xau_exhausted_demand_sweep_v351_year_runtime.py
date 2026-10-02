from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_exhausted_demand_sweep_v351 import evaluate_year, load_price_frame


def run() -> int:
    year = int(os.getenv("XAU_V351_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V351_YEAR_INVALID:{year}")
    price_path = Path(
        os.getenv("XAU_V351_PRICE_CSV", f"/tmp/histdata/xau-v351-{year}.csv")
    )
    output = Path(
        os.getenv(
            "XAU_V351_YEAR_OUTPUT",
            f"artifacts/xau-exhausted-demand-sweep-v351-{year}.json",
        )
    )
    price = load_price_frame(price_path)
    payload = evaluate_year(price, target_year=year)
    payload["price_rows"] = len(price)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = dict(payload.get("summary") or {})
    print(
        "XAU_EXHAUSTED_DEMAND_SWEEP_V351_YEAR "
        f"year={year} events={payload['event_count']} "
        f"fresh_h1={summary.get('with_fresh_h1_below')} "
        f"h2_reached={summary.get('h2_reached')} "
        f"confirmed={summary.get('confirmation_after_h2')} "
        f"clean_supply_hits={summary.get('clean_opposing_supply_hits')} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
