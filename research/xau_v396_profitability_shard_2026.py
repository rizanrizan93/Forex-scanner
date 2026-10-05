from __future__ import annotations

"""Thin 2026 holdout wrapper around the frozen V394 shard simulator.

This changes metadata only: V394 entry/stop/target/cost logic is reused unchanged.
"""

import argparse
import json
from pathlib import Path

from xau_v394_profitability_execution import run_shard


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--adaptive-json", type=Path, required=True)
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--shard-index", type=int, required=True)
    p.add_argument("--shard-count", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    payload = run_shard(
        adaptive_json=args.adaptive_json,
        csv_path=args.csv,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        output=args.output,
    )
    payload["year"] = 2026
    payload["holdout"] = True
    payload["selection_data_used"] = "2025_ONLY"
    payload["execution_authority"] = False
    payload["demo_auto_execution"] = False
    payload["live_execution_enabled"] = False
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V396_SHARD=" + json.dumps({
        "year": 2026,
        "shard": args.shard_index,
        "shard_count": args.shard_count,
        "sweep_trades": len(dict(payload.get("trades") or {}).get("SWEEP_RECLAIM_M5") or []),
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
