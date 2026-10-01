from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_sd_liquidity_v345 import evaluate_year, load_price_frame


def run() -> int:
    year = int(os.getenv("XAU_V345_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V345_YEAR_INVALID:{year}")
    price_path = Path(
        os.getenv("XAU_V345_PRICE_CSV", f"/tmp/histdata/xau-v345-{year}.csv")
    )
    output = Path(
        os.getenv(
            "XAU_V345_YEAR_OUTPUT",
            f"artifacts/xau-sd-liquidity-v345-{year}.json",
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
    all_summary = dict(payload["summary"]["ALL"])
    print(
        "XAU_SD_LIQUIDITY_V345_YEAR "
        f"year={year} zones={payload['zone_catalog_count']} "
        f"touches={payload['episode_count']} "
        f"reaction_rate={all_summary.get('reaction_rate')} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
