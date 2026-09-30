from __future__ import annotations

import json
import os
from pathlib import Path

from .research_xau_entry_tp_precision_v284 import RESEARCH_VERSION, walk_forward


def run() -> int:
    root = Path(os.getenv("XAU_V284_SHARD_DIR", "/tmp/v284-shards"))
    output = Path(os.getenv("XAU_V284_FULL_OUTPUT", "artifacts/xau-entry-tp-precision-v284-full.json"))
    paths = sorted(root.rglob("xau-entry-tp-precision-v284-20*.json"))
    if not paths:
        raise SystemExit("V284_NO_YEAR_SHARDS")
    shards = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(shard.get("research_version") != RESEARCH_VERSION for shard in shards):
        raise SystemExit("V284_SHARD_VERSION_MISMATCH")
    years = [int(shard["year"]) for shard in shards]
    if len(years) != len(set(years)):
        raise SystemExit("V284_DUPLICATE_YEAR")
    result = walk_forward([row for shard in shards for row in shard["rows"]])
    result["years"] = sorted(years)
    result["price_end_by_year"] = {str(shard["year"]): shard["price_end"] for shard in shards}
    result["source_sha256_by_year"] = {
        str(shard["year"]): shard["price_provenance"]["sha256"] for shard in shards
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"V284_FULL years={len(years)} plans={result['plans']} eligible_folds={sum(row['eligible'] for row in result['folds'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
