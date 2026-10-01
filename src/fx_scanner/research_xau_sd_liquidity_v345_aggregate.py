from __future__ import annotations

import json
import os
from pathlib import Path

from .research_xau_sd_liquidity_v345 import aggregate_years


def run() -> int:
    root = Path(os.getenv("XAU_V345_SHARD_DIR", "/tmp/v345-shards"))
    output = Path(
        os.getenv(
            "XAU_V345_FULL_OUTPUT",
            "artifacts/xau-sd-liquidity-v345-full.json",
        )
    )
    shards = []
    for path in sorted(root.rglob("xau-sd-liquidity-v345-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "year" in payload:
            shards.append(payload)
    if not shards:
        raise SystemExit("XAU_V345_NO_SHARDS")
    payload = aggregate_years(shards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    full = dict(payload["periods"]["full_2012_2026"]["summary"]["ALL"])
    oos = dict(payload["periods"]["oos_2025_2026"]["summary"]["ALL"])
    print(
        "XAU_SD_LIQUIDITY_V345_FULL "
        f"years={payload['year_count']} zones={payload['zone_catalog_count']} "
        f"touches={payload['episode_count']} "
        f"reaction_full={full.get('reaction_rate')} reaction_oos={oos.get('reaction_rate')} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
