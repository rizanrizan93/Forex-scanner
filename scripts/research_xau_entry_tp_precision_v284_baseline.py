"""Summarize existing V242 yearly JSON shards for $5 entry/TP baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_scanner.research_xau_entry_tp_precision_v284 import baseline_from_v242_shards


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(args.shards.glob("xau-v229-historical-v242-*.json"))
    if not paths:
        parser.error("no V242 yearly JSON shards found")
    shards = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(not str(shard.get("research_version") or "").startswith("XAU_V229_HISTORICAL_EXECUTION_V242") for shard in shards):
        parser.error("input includes a non-V242 shard")
    result = baseline_from_v242_shards(shards)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"V284 baseline years={result['year_count']} plans={result['parent_plans']} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
