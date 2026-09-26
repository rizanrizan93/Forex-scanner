from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_nested_m5_v228 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    _load_price_frame,
    build_year_records,
)


def _year() -> int:
    year = int(os.getenv("XAU_V228_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V228_YEAR_INVALID:{year}")
    return year


def run() -> int:
    year = _year()
    price_path = Path(os.getenv("XAU_V228_PRICE_CSV", "").strip())
    if not price_path.exists():
        raise SystemExit(f"XAU_V228_PRICE_CSV_NOT_FOUND:{price_path}")
    output = Path(
        os.getenv(
            "XAU_V228_YEAR_OUTPUT",
            f"artifacts/xau-nested-m5-depth-v228-{year}.json",
        )
    )
    price = _load_price_frame(str(price_path))
    summary, records = build_year_records(price, target_year=year)
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "year": year,
        "price_rows": len(price),
        "summary": summary,
        "records": records,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_NESTED_M5_V228_YEAR "
        f"year={year} m15_nested={summary['m15_nested']} "
        f"m5_available={summary['m5_available_given_m15']} "
        f"selected_capture={summary['selected_m5_capture_given_m15']} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
