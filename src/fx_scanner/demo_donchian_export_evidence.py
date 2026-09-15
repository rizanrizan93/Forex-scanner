from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .storage.supabase_operational import SupabaseOperationalStore

ALLOWED_WORKERS = frozenset({
    "ctrader_demo_donchian_adaptive_tournament",
    "ctrader_demo_donchian_forward_shadow",
})


def export_latest(worker_name: str, output_path: str) -> dict[str, Any]:
    worker = str(worker_name).strip()
    if worker not in ALLOWED_WORKERS:
        raise SystemExit("DONCHIAN_EVIDENCE_WORKER_NOT_ALLOWED")
    destination = Path(output_path)
    if not destination.name or destination.suffix.lower() != ".json":
        raise SystemExit("DONCHIAN_EVIDENCE_OUTPUT_MUST_BE_JSON")

    store = SupabaseOperationalStore.from_env()
    response = (
        store.client.table("runtime_heartbeats")
        .select("worker_name,observed_at,healthy,lag_seconds,details")
        .eq("worker_name", worker)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if len(rows) != 1:
        raise SystemExit(f"DONCHIAN_EVIDENCE_HEARTBEAT_COUNT:{len(rows)}")
    row = dict(rows[0])
    row["artifact_contract"] = "DONCHIAN_RUNTIME_EVIDENCE_V1"
    row["contains_secrets"] = False
    row["source"] = "runtime_heartbeats"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(row, indent=2, sort_keys=True, default=str) + "\n")
    return row


def run() -> int:
    worker = os.getenv("DONCHIAN_EVIDENCE_WORKER", "").strip()
    output = os.getenv("DONCHIAN_EVIDENCE_OUTPUT", "donchian-evidence.json").strip()
    row = export_latest(worker, output)
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    decision = details.get("decision") if isinstance(details, dict) else {}
    print(
        "DONCHIAN_EVIDENCE_EXPORTED "
        f"worker={worker} healthy={bool(row.get('healthy'))} "
        f"stage={decision.get('stage') if isinstance(decision, dict) else None} "
        f"path={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
