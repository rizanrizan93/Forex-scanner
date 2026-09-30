"""Offline V280 replay. Usage: --plans YEAR_SHARD.json --m1 YEAR_M1.csv --output report.json.

For a fold covering year Y, include plan shards from earlier years and M1
history continuing at least 30 days beyond each plan's expiry. Repeating
--plans and --m1 pairs is supported. No database or broker calls are made.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_scanner.research_xau_joint_entry_tp_v280 import replay_plan, walk_forward
from fx_scanner.research_xau_zone_reversal_depth_v225 import _load_price_frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", action="append", type=Path, required=True)
    parser.add_argument("--m1", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.plans) != len(args.m1):
        parser.error("one --m1 file is required for each --plans shard")
    rows = []
    for plan_path, m1_path in zip(args.plans, args.m1):
        shard = json.loads(plan_path.read_text(encoding="utf-8"))
        if not str(shard.get("research_version") or "").startswith("XAU_V229_HISTORICAL_EXECUTION_V242"):
            parser.error(f"not a V242 plan shard: {plan_path}")
        frame = _load_price_frame(str(m1_path))
        for plan in shard.get("plans", []):
            rows.append(replay_plan(plan, frame))
    report = walk_forward(rows)
    report["source_plan_files"] = [str(path) for path in args.plans]
    report["source_price_files"] = [str(path) for path in args.m1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"V280 plans={report['plans']} folds={len(report['folds'])} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
