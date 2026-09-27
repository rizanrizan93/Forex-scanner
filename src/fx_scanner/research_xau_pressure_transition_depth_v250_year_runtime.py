from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_pressure_transition_depth_v250 import ARTIFACT_CONTRACT, RESEARCH_VERSION, build_transition_depth_rows, serialize_row
from .research_xau_zone_reversal_depth_v225 import _load_price_frame, build_depth_dataset


def run() -> int:
    year = int(os.getenv("XAU_V250_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V250_YEAR_INVALID:{year}")
    price_path = Path(os.environ["XAU_V250_PRICE_CSV"])
    output = Path(os.getenv("XAU_V250_YEAR_OUTPUT", f"artifacts/xau-pressure-transition-depth-v250-{year}.json"))
    price = _load_price_frame(str(price_path))
    _zones, episodes = build_depth_dataset(price, target_year=year)
    rows = build_transition_depth_rows(price, episodes)
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "year": year,
        "historical_pressure_source": "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM",
        "episode_count": len(rows),
        "episodes": [serialize_row(row) for row in rows],
        "execution_influence": False,
        "execution_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"XAU_PRESSURE_TRANSITION_DEPTH_V250 year={year} episodes={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())