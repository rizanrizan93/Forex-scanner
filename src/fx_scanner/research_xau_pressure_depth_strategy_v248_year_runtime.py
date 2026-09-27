from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_pressure_depth_strategy_v248 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    build_variant_results,
    summarize_variants,
)
from .research_xau_zone_reversal_depth_v225 import _load_price_frame, build_depth_dataset


def _year() -> int:
    value = int(os.getenv("XAU_V248_YEAR", "0") or 0)
    if value < 2012 or value > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V248_YEAR_INVALID:{value}")
    return value


def run() -> int:
    year = _year()
    price_path = Path(os.environ["XAU_V248_PRICE_CSV"])
    output = Path(os.getenv("XAU_V248_YEAR_OUTPUT", f"artifacts/xau-pressure-depth-strategy-v248-{year}.json"))
    price = _load_price_frame(str(price_path))
    _zones, episodes = build_depth_dataset(price, target_year=year)
    results = build_variant_results(price, episodes)
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "year": year,
        "price_source": "HISTDATA_XAUUSD_M1",
        "historical_pressure_source": "CAUSAL_M1_OHLC_PROXY_NOT_DOM",
        "episode_count": len(episodes),
        "variants": summarize_variants(results),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"XAU_PRESSURE_DEPTH_STRATEGY_V248 year={year} episodes={len(episodes)} variants={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
