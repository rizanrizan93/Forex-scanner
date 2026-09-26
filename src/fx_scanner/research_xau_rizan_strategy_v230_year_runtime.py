from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_rizan_strategy_v230 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    _load_price_frame,
    simulate_year,
)


def _year() -> int:
    year = int(os.getenv("XAU_V230_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V230_YEAR_INVALID:{year}")
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
    price_path = _path_env("XAU_V230_PRICE_CSV")
    output = Path(
        os.getenv(
            "XAU_V230_YEAR_OUTPUT",
            f"artifacts/xau-rizan-strategy-v230-{year}.json",
        )
    )
    provenance_raw = os.getenv("XAU_V230_PRICE_PROVENANCE", "").strip()
    provenance: dict[str, Any] = {}
    if provenance_raw:
        path = Path(provenance_raw)
        if path.exists():
            provenance = dict(json.loads(path.read_text()) or {})

    price = _load_price_frame(str(price_path))
    summary, records = simulate_year(price, target_year=year)
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "year": year,
        "price_source": "HISTDATA_XAUUSD_M1_FIXED_EST_NORMALIZED_UTC",
        "price_provenance": provenance,
        "price_rows": len(price),
        "summary": summary,
        "records": records,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "lookahead_policy": "CAUSAL_ZONE_AVAILABILITY_AND_COMPLETED_M5_ONLY",
        "calibration_scope": "FROZEN_V2252_FULL_2012_2026_PRIORS_IN_SAMPLE_REPLAY",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_RIZAN_STRATEGY_V230_YEAR "
        f"year={year} signals={summary['signals']} "
        f"fills={summary['account_cap_accepted_children']} "
        f"pnl_usd={summary['total_pnl_usd_0p01_standard_contract']:.2f} "
        f"total_r={summary['total_r']:.3f} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
