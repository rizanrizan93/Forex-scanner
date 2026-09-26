from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_nested_m5_v228 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    summarize_records,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "research_xau_nested_m5_v228"
ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows = []
    for file in sorted(path.rglob("xau-nested-m5-depth-v228-*.json")):
        payload = json.loads(file.read_text())
        if payload.get("year") is not None:
            rows.append(payload)
    rows.sort(key=lambda x: int(x["year"]))
    return rows


def _aggregate(selected: list[dict[str, Any]]) -> dict[str, Any]:
    records = [dict(r) for shard in selected for r in list(shard.get("records") or [])]
    return summarize_records(
        records,
        h4_successes=sum(int(dict(s.get("summary") or {}).get("h4_successes") or 0) for s in selected),
        h1_nested=sum(int(dict(s.get("summary") or {}).get("h1_nested") or 0) for s in selected),
        m15_nested=sum(int(dict(s.get("summary") or {}).get("m15_nested") or 0) for s in selected),
        m5_zone_count=sum(int(dict(s.get("summary") or {}).get("m5_zone_count") or 0) for s in selected),
    )


def run() -> int:
    shard_dir = Path(os.getenv("XAU_V228_SHARD_DIR", "/tmp/v228-shards"))
    shards = _load_shards(shard_dir)
    if not shards:
        raise SystemExit("XAU_V228_NO_SHARDS")
    overall = _aggregate(shards)
    eras = {}
    for name, (start, end) in ERAS.items():
        selected = [s for s in shards if start <= int(s["year"]) <= end]
        eras[name] = {"years": [start, end], "summary": _aggregate(selected)}
    observed_at = datetime.now(tz=UTC)
    output = Path(
        os.getenv("XAU_V228_FULL_OUTPUT", "artifacts/xau-nested-m5-depth-v228-full.json")
    )
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "observed_at": observed_at.isoformat(),
        "years": [int(s["year"]) for s in shards],
        "year_count": len(shards),
        "overall": overall,
        "eras": eras,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V228 tests whether a causal pre-touch M5 child can narrow the existing "
            "H4→H1→M15 depth hierarchy. Selected M5 uses only availability/active state, "
            "width and recency at the H4 touch; the study remains conditional on V225's "
            "descriptive M15 parent and therefore is evidence for prospective V229, not "
            "automatic execution authority."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=len(shards) >= 15,
            lag_seconds=0.0,
            details={
                "contract": payload["artifact_contract"],
                "research_version": RESEARCH_VERSION,
                "year_count": len(shards),
                "years": payload["years"],
                "overall": overall,
                "eras": eras,
                "policy_effect": "SHADOW_ONLY",
                "execution_influence": False,
                "execution_authority": False,
                "promotion_authority": False,
                "artifact_path": str(output),
                "observed_at": observed_at.isoformat(),
                "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            },
        )
    except Exception as exc:
        print(f"V228_HEARTBEAT_WRITE_WARNING:{type(exc).__name__}:{exc}")
    print(
        "XAU_NESTED_M5_V228_FULL "
        f"years={len(shards)} m15_nested={overall['m15_nested']} "
        f"m5_available={overall['m5_available_given_m15']} "
        f"selected_capture={overall['selected_m5_capture_given_m15']} "
        f"artifact={output} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
