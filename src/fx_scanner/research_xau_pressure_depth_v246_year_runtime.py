from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_pressure_depth_v246 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    condition_depth_episodes,
    pressure_depth_report,
    serialize_pressure_episode,
)
from .research_xau_zone_reversal_depth_v225 import _load_price_frame, build_depth_dataset


def _year() -> int:
    year = int(os.getenv("XAU_V246_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V246_YEAR_INVALID:{year}")
    return year


def _path_env(name: str) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise SystemExit(f"{name}_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"{name}_NOT_FOUND:{path}")
    return path


def run() -> int:
    year = _year()
    price_path = _path_env("XAU_V246_PRICE_CSV")
    output = Path(
        os.getenv(
            "XAU_V246_YEAR_OUTPUT",
            f"artifacts/xau-pressure-depth-v246-{year}.json",
        )
    )

    provenance: dict[str, Any] = {}
    raw_provenance = os.getenv("XAU_V246_PRICE_PROVENANCE", "").strip()
    if raw_provenance and Path(raw_provenance).exists():
        provenance = dict(json.loads(Path(raw_provenance).read_text()) or {})

    price = _load_price_frame(str(price_path))
    _zones, depth_episodes = build_depth_dataset(price, target_year=year)
    rows = condition_depth_episodes(price, depth_episodes)

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "year": year,
        "price_source": "HISTDATA_XAUUSD_M1_FIXED_EST_NORMALIZED_UTC",
        "price_provenance": provenance,
        "source_limitation": (
            "Historical source contains OHLC only. Buyer/seller strength is a causal "
            "M1 pressure proxy built from completed bars before first touch, not DOM."
        ),
        "depth_episode_count": len(depth_episodes),
        "conditioned_episode_count": len(rows),
        "summary": pressure_depth_report(rows),
        "episodes": [serialize_pressure_episode(row) for row in rows],
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    print(
        "XAU_PRESSURE_DEPTH_V246_YEAR "
        f"year={year} depth_episodes={len(depth_episodes)} conditioned={len(rows)} "
        "historical_dom=0 execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
