from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_brent_uni_depth_v238b_metrics import (
    build_excursion_metrics,
    grouped_excursion_report,
)
from .research_xau_zone_reversal_depth_v225 import (
    _load_price_frame,
    build_depth_dataset,
    grouped_report,
    hierarchy_report,
    serialize_episode,
)

RESEARCH_VERSION = "BRENT_UNI_DEPTH_V238B_1"
ARTIFACT_CONTRACT = "BRENT_UNI_DEPTH_V238B_1_EVIDENCE_1"


def _year() -> int:
    year = int(os.getenv("BRENT_V238B_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"BRENT_V238B_YEAR_INVALID:{year}")
    return year


def _output_path(year: int) -> Path:
    raw = os.getenv(
        "BRENT_V238B_YEAR_OUTPUT",
        f"artifacts/brent-uni-depth-v238b-{year}.json",
    ).strip()
    if not raw:
        raise SystemExit("BRENT_V238B_YEAR_OUTPUT_REQUIRED")
    return Path(raw)


def _provenance() -> dict[str, Any]:
    raw = os.getenv("BRENT_V238B_PRICE_PROVENANCE", "").strip()
    if not raw:
        return {}
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"BRENT_V238B_PRICE_PROVENANCE_NOT_FOUND:{path}")
    return dict(json.loads(path.read_text()) or {})


def _write(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def run() -> int:
    year = _year()
    output = _output_path(year)
    provenance = _provenance()
    price_raw = os.getenv("BRENT_V238B_PRICE_CSV", "").strip()
    price_path = Path(price_raw) if price_raw else None

    if not bool(provenance.get("available")) or price_path is None or not price_path.exists():
        payload = {
            "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
            "research_version": RESEARCH_VERSION,
            "instrument": "BRENT",
            "histdata_pair": "BCOUSD",
            "method_source": "XAU_ZONE_REVERSAL_DEPTH_V225_2_CAUSAL_GEOMETRY",
            "year": year,
            "available": False,
            "price_provenance": provenance,
            "zone_count": 0,
            "episode_count": 0,
            "summary": {},
            "excursion_summary": {},
            "hierarchy": {},
            "episodes": [],
            "excursions": [],
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "live_execution_enabled": False,
        }
        _write(payload, output)
        print(
            "BRENT_UNI_DEPTH_V238B_YEAR "
            f"year={year} available=0 episodes=0 execution_authority=0"
        )
        return 0

    price = _load_price_frame(str(price_path))
    zones, episodes = build_depth_dataset(price, target_year=year)
    excursions = build_excursion_metrics(price, episodes)
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "instrument": "BRENT",
        "histdata_pair": "BCOUSD",
        "method_source": "XAU_ZONE_REVERSAL_DEPTH_V225_2_CAUSAL_GEOMETRY",
        "year": year,
        "available": True,
        "price_source": "HISTDATA_BCOUSD_M1_FIXED_EST_NORMALIZED_UTC",
        "price_provenance": provenance,
        "price_rows": len(price),
        "price_start": price["timestamp"].iloc[0].isoformat(),
        "price_end": price["timestamp"].iloc[-1].isoformat(),
        "zone_count": len(zones),
        "episode_count": len(episodes),
        "summary": grouped_report(episodes),
        "excursion_summary": grouped_excursion_report(excursions),
        "hierarchy": hierarchy_report(episodes),
        "episodes": [serialize_episode(row) for row in episodes],
        "excursions": excursions,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "live_execution_enabled": False,
    }
    _write(payload, output)
    print(
        "BRENT_UNI_DEPTH_V238B_YEAR "
        f"year={year} available=1 zones={len(zones)} episodes={len(episodes)} "
        f"h4={payload['summary']['H4']['ALL']['touches']} "
        f"h1={payload['summary']['H1']['ALL']['touches']} "
        f"m15={payload['summary']['M15']['ALL']['touches']} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
