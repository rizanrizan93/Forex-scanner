from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .research_xau_zone_touch_decay_v352 import evaluate_year, load_price_frame


def run() -> int:
    year = int(os.getenv("XAU_V352_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V352_YEAR_INVALID:{year}")
    price_path = Path(
        os.getenv("XAU_V352_PRICE_CSV", f"/tmp/histdata/xau-v352-{year}.csv")
    )
    output = Path(
        os.getenv(
            "XAU_V352_YEAR_OUTPUT",
            f"artifacts/xau-zone-touch-decay-v352-{year}.json",
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
    print(
        "XAU_ZONE_TOUCH_DECAY_V352_YEAR "
        f"year={year} zones={payload['zone_count']} episodes={payload['episode_count']} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
