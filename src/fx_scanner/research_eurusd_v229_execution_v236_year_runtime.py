from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_eurusd_v229_execution_v236 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    _load_price_frame,
    simulate_year,
)


def _year() -> int:
    year = int(os.getenv("EURUSD_V236_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"EURUSD_V236_YEAR_INVALID:{year}")
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
    price_path = _path_env("EURUSD_V236_PRICE_CSV")
    output = Path(
        os.getenv(
            "EURUSD_V236_YEAR_OUTPUT",
            f"artifacts/eurusd-v229-v236-{year}.json",
        ).strip()
    )
    provenance_raw = os.getenv("EURUSD_V236_PRICE_PROVENANCE", "").strip()
    provenance: dict[str, Any] = {}
    if provenance_raw and Path(provenance_raw).exists():
        provenance = dict(json.loads(Path(provenance_raw).read_text()) or {})

    price = _load_price_frame(str(price_path))
    variants = {
        "current_literal": simulate_year(
            price,
            target_year=year,
            prior_mode="CURRENT",
            arm_mode="LITERAL",
        ),
        "current_healthy": simulate_year(
            price,
            target_year=year,
            prior_mode="CURRENT",
            arm_mode="HEALTHY_1ATR",
        ),
        "seed_healthy": simulate_year(
            price,
            target_year=year,
            prior_mode="SEED_2012_2018",
            arm_mode="HEALTHY_1ATR",
        ),
    }
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "pair": "EURUSD",
        "year": year,
        "price_source": "HISTDATA_EURUSD_M1_FIXED_EST_NORMALIZED_UTC",
        "price_provenance": provenance,
        "price_rows": len(price),
        "price_start": price["timestamp"].iloc[0].isoformat(),
        "price_end": price["timestamp"].iloc[-1].isoformat(),
        "variants": variants,
        "execution_influence": False,
        "execution_authority": False,
        "live_execution_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "EURUSD_V229_V236_YEAR "
        f"year={year} "
        f"literal_plans={variants['current_literal']['plan_count']} "
        f"healthy_plans={variants['current_healthy']['plan_count']} "
        f"healthy_closed={variants['current_healthy']['closed_children']} "
        f"seed_closed={variants['seed_healthy']['closed_children']} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
