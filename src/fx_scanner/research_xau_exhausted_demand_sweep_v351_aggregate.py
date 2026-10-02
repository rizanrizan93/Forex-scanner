from __future__ import annotations

import json
import os
from pathlib import Path

from .research_xau_exhausted_demand_sweep_v351 import aggregate_years


def run() -> int:
    root = Path(os.getenv("XAU_V351_SHARD_DIR", "/tmp/v351-shards"))
    output = Path(
        os.getenv(
            "XAU_V351_FULL_OUTPUT",
            "artifacts/xau-exhausted-demand-sweep-v351-full.json",
        )
    )
    shards = []
    for path in sorted(root.rglob("xau-exhausted-demand-sweep-v351-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "year" in payload:
            shards.append(payload)
    if not shards:
        raise SystemExit("XAU_V351_NO_SHARDS")
    payload = aggregate_years(shards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    full = dict(payload["periods"]["full_2012_2026"]["summary"])
    oos = dict(payload["periods"]["oos_2025_2026"]["summary"])
    print(
        "XAU_EXHAUSTED_DEMAND_SWEEP_V351_FULL "
        f"years={payload['year_count']} events={payload['event_count']} "
        f"h2_before_rebound_full={full.get('h2_before_rebound_rate')} "
        f"confirm_full={full.get('confirmation_rate_after_h2')} "
        f"supply_full={full.get('clean_supply_rate_after_confirmation')} "
        f"supply_oos={oos.get('clean_supply_rate_after_confirmation')} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
