from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_rizan_strategy_v230 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    summarize_signal_records,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "research_xau_rizan_strategy_v230"
ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows = []
    for file in sorted(path.rglob("xau-rizan-strategy-v230-*.json")):
        payload = json.loads(file.read_text())
        if payload.get("year") is not None:
            rows.append(payload)
    rows.sort(key=lambda row: int(row["year"]))
    return rows


def _selected_records(
    shards: list[dict[str, Any]], start: int | None = None, end: int | None = None
) -> list[dict[str, Any]]:
    out = []
    for shard in shards:
        year = int(shard["year"])
        if start is not None and year < start:
            continue
        if end is not None and year > end:
            continue
        out.extend(dict(row) for row in list(shard.get("records") or []))
    return out


def _direction_summary(records: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    return summarize_signal_records(
        [row for row in records if str(row.get("direction") or "").upper() == direction]
    )


def run() -> int:
    shard_dir = Path(os.getenv("XAU_V230_SHARD_DIR", "/tmp/v230-shards"))
    shards = _load_shards(shard_dir)
    if len(shards) < 15:
        raise SystemExit(f"XAU_V230_INCOMPLETE_SHARDS:{len(shards)}")

    all_records = _selected_records(shards)
    overall = summarize_signal_records(all_records)
    overall["LONG"] = _direction_summary(all_records, "LONG")
    overall["SHORT"] = _direction_summary(all_records, "SHORT")

    yearly = {
        str(int(shard["year"])): dict(shard.get("summary") or {})
        for shard in shards
    }
    eras = {}
    for name, (start, end) in ERAS.items():
        records = _selected_records(shards, start, end)
        summary = summarize_signal_records(records)
        summary["LONG"] = _direction_summary(records, "LONG")
        summary["SHORT"] = _direction_summary(records, "SHORT")
        eras[name] = {"years": [start, end], "summary": summary}

    observed_at = datetime.now(tz=UTC)
    output = Path(
        os.getenv(
            "XAU_V230_FULL_OUTPUT",
            "artifacts/xau-rizan-strategy-v230-full.json",
        )
    )
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "observed_at": observed_at.isoformat(),
        "years": [int(shard["year"]) for shard in shards],
        "year_count": len(shards),
        "overall": overall,
        "eras": eras,
        "yearly": yearly,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "lookahead_policy": "CAUSAL_ZONE_AVAILABILITY_AND_COMPLETED_M5_ONLY",
        "calibration_scope": "FROZEN_V2252_FULL_2012_2026_PRIORS_IN_SAMPLE_REPLAY",
        "interpretation": (
            "V230 replays the current V229 2+2 child-order design using causal zone "
            "availability, causal H4 focus selection, completed M5 evidence for reserve "
            "slots, structural M15/H1/H4 targets, conservative same-minute SL precedence, "
            "and a 10-child account cap. Frozen V225.2 priors were estimated on the same "
            "2012-2026 period, so this is retrospective strategy evidence rather than an "
            "unbiased out-of-sample estimate."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    store = SupabaseOperationalStore.from_env()
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details={
            "contract": payload["artifact_contract"],
            "research_version": RESEARCH_VERSION,
            "year_count": len(shards),
            "years": payload["years"],
            "overall": overall,
            "eras": eras,
            "policy_effect": "RESEARCH_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "lookahead_policy": payload["lookahead_policy"],
            "calibration_scope": payload["calibration_scope"],
            "artifact_path": str(output),
            "observed_at": observed_at.isoformat(),
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "XAU_RIZAN_STRATEGY_V230_FULL "
        f"years={len(shards)} signals={overall['signals']} "
        f"fills={overall['account_cap_accepted_children']} "
        f"pnl_usd={overall['total_pnl_usd_0p01_standard_contract']:.2f} "
        f"end200={overall['illustrative_end_balance_usd']:.2f} "
        f"pf={overall['profit_factor_r']} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
