from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_rizan_axy_delta_v323 import evaluate_year
from .research_xau_zone_reversal_depth_v225 import (
    _load_price_frame,
    build_depth_dataset,
)


def run() -> int:
    year = int(os.getenv("XAU_V323_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V323_YEAR_INVALID:{year}")

    price_path = Path(
        os.getenv(
            "XAU_V323_PRICE_CSV",
            f"/tmp/histdata/xau-v323-{year}.csv",
        )
    )
    output = Path(
        os.getenv(
            "XAU_V323_YEAR_OUTPUT",
            f"artifacts/xau-rizan-axy-delta-v323-{year}.json",
        )
    )
    price = _load_price_frame(str(price_path))
    _zones, episodes = build_depth_dataset(price, target_year=year)
    report = evaluate_year(price, episodes)
    payload = {
        **report,
        "year": year,
        "price_rows": len(price),
        "year_episode_count": len(episodes),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"XAU_RIZAN_AXY_DELTA_V323_YEAR year={year} "
        f"episodes={report['episodes']} candidates={len(report['candidates'])} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
