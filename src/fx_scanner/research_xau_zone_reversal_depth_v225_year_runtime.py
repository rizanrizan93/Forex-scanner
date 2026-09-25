from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_zone_reversal_depth_v225 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    build_depth_dataset,
    grouped_report,
    hierarchy_report,
    serialize_episode,
    _load_price_frame,
)


def _year() -> int:
    year = int(os.getenv("XAU_V225_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V225_YEAR_INVALID:{year}")
    return year


def _path_env(name: str) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise SystemExit(f"{name}_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"{name}_NOT_FOUND:{path}")
    return path


def _output_path(year: int) -> Path:
    raw = os.getenv(
        "XAU_V225_YEAR_OUTPUT",
        f"artifacts/xau-zone-reversal-depth-v225-{year}.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_V225_YEAR_OUTPUT_REQUIRED")
    return Path(raw)


def run() -> int:
    year = _year()
    price_path = _path_env("XAU_V225_PRICE_CSV")
    output_path = _output_path(year)
    provenance_path_raw = os.getenv("XAU_V225_PRICE_PROVENANCE", "").strip()
    provenance: dict[str, Any] = {}
    if provenance_path_raw:
        path = Path(provenance_path_raw)
        if path.exists():
            provenance = dict(json.loads(path.read_text()) or {})

    price = _load_price_frame(str(price_path))
    zones, episodes = build_depth_dataset(price, target_year=year)

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "contains_secrets": False,
        "year": year,
        "price_source": "HISTDATA_XAUUSD_M1_FIXED_EST_NORMALIZED_UTC",
        "price_provenance": provenance,
        "price_rows": len(price),
        "price_start": price["timestamp"].iloc[0].isoformat(),
        "price_end": price["timestamp"].iloc[-1].isoformat(),
        "zone_count": len(zones),
        "episode_count": len(episodes),
        "summary": grouped_report(episodes),
        "hierarchy": hierarchy_report(episodes),
        "episodes": [serialize_episode(row) for row in episodes],
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        "XAU_ZONE_REVERSAL_DEPTH_V225_YEAR "
        f"year={year} zones={len(zones)} episodes={len(episodes)} "
        f"h4={payload['summary']['H4']['ALL']['touches']} "
        f"h1={payload['summary']['H1']['ALL']['touches']} "
        f"m15={payload['summary']['M15']['ALL']['touches']} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
