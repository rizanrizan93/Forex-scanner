from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_rizan_four_child_v230 import (
    ARTIFACT_CONTRACT,
    FROZEN_PRIOR_VERSION,
    RESEARCH_VERSION,
    load_price_frame,
    simulate_year,
)
from .storage.supabase_operational import SupabaseOperationalStore

PRIOR_WORKER = "research_xau_zone_reversal_depth_v225"


def _year() -> int:
    year = int(os.getenv("XAU_V230_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V230_YEAR_INVALID:{year}")
    return year


def _prior(store: SupabaseOperationalStore) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", PRIOR_WORKER)
        .eq("healthy", True)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if len(rows) != 1:
        raise RuntimeError("V230_FROZEN_PRIOR_HEARTBEAT_MISSING")
    details = dict(rows[0].get("details") or {})
    if str(details.get("research_version") or "") != FROZEN_PRIOR_VERSION:
        raise RuntimeError("V230_FROZEN_PRIOR_VERSION_MISMATCH")
    if int(details.get("year_count") or 0) < 15:
        raise RuntimeError("V230_FROZEN_PRIOR_INCOMPLETE")
    return details


def run() -> int:
    year = _year()
    price_path = Path(os.getenv("XAU_V230_PRICE_CSV", "").strip())
    if not price_path.exists():
        raise SystemExit(f"XAU_V230_PRICE_CSV_NOT_FOUND:{price_path}")
    output = Path(
        os.getenv(
            "XAU_V230_YEAR_OUTPUT",
            f"artifacts/xau-rizan-four-child-v230-{year}.json",
        )
    )
    store = SupabaseOperationalStore.from_env()
    history = _prior(store)
    price = load_price_frame(str(price_path))
    summary, parents, children = simulate_year(
        price,
        target_year=year,
        history_details=history,
    )
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "contains_secrets": False,
        "year": year,
        "price_rows": len(price),
        "price_start": price["timestamp"].iloc[0].isoformat(),
        "price_end": price["timestamp"].iloc[-1].isoformat(),
        "prior_contract": history.get("contract"),
        "prior_research_version": history.get("research_version"),
        "prior_mode": "FROZEN_FULL_2012_2026_RETROSPECTIVE",
        "summary": summary,
        "parents": parents,
        "children": children,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_RIZAN_FOUR_CHILD_V230_YEAR "
        f"year={year} parents={summary['parents']} "
        f"filled={summary['children_filled']} tp={summary['tp']} sl={summary['sl']} "
        f"pnl={summary['gross_pnl_usd_001']:.4f} "
        "prior=FROZEN_FULL_2012_2026 execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
