from __future__ import annotations

import json
import os
from pathlib import Path

from .research_xau_zone_touch_decay_v352 import aggregate_years


def run() -> int:
    root = Path(os.getenv("XAU_V352_SHARD_DIR", "/tmp/v352-shards"))
    output = Path(
        os.getenv(
            "XAU_V352_FULL_OUTPUT",
            "artifacts/xau-zone-touch-decay-v352-full.json",
        )
    )
    shards = []
    for path in sorted(root.rglob("xau-zone-touch-decay-v352-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "year" in payload:
            shards.append(payload)
    if not shards:
        raise SystemExit("XAU_V352_NO_SHARDS")
    payload = aggregate_years(shards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    full = payload["periods"]["full_2012_2026"]["summary"]
    oos = payload["periods"]["oos_2025_2026"]["summary"]
    def rate(block, tf, bucket):
        return (((block.get(tf) or {}).get("ALL") or {}).get(bucket) or {}).get("reversal_rate")
    print(
        "XAU_ZONE_TOUCH_DECAY_V352_FULL "
        f"years={payload['year_count']} episodes={payload['episode_count']} "
        f"H4_t0={rate(full,'H4','0')} H4_t1={rate(full,'H4','1')} H4_t2={rate(full,'H4','2')} "
        f"H2_t0={rate(full,'H2','0')} H1_t0={rate(full,'H1','0')} "
        f"OOS_H4_t0={rate(oos,'H4','0')} OOS_H2_t0={rate(oos,'H2','0')} OOS_H1_t0={rate(oos,'H1','0')} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
