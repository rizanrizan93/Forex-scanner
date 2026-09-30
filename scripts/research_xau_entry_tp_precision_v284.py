"""Offline V284: repeat --plans V242_YEAR.json --m1 M1_WITH_30D_FOLLOWUP.csv."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_scanner.research_xau_entry_tp_precision_v284 import replay_plan, walk_forward
from fx_scanner.research_xau_zone_reversal_depth_v225 import _load_price_frame
from fx_scanner.research_xau_v229_historical_v242 import price_arrays


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, action="append", required=True)
    parser.add_argument("--m1", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.plans) != len(args.m1):
        parser.error("one --m1 file is required for each --plans shard")
    rows = []
    for plans, price in zip(args.plans, args.m1):
        shard = json.loads(plans.read_text(encoding="utf-8"))
        if not str(shard.get("research_version") or "").startswith("XAU_V229_HISTORICAL_EXECUTION_V242"):
            parser.error(f"not a V242 plan shard: {plans}")
        px = price_arrays(_load_price_frame(str(price)))
        rows.extend(replay_plan(row, px) for row in shard.get("plans", []))
    report = walk_forward(rows)
    report["source_plan_files"] = [str(path) for path in args.plans]
    report["source_m1_files"] = [str(path) for path in args.m1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"V284 plans={report['plans']} folds={len(report['folds'])} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
