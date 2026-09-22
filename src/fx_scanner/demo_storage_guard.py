from __future__ import annotations

import os
from typing import Any

from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_storage_guard"
CONTRACT = "FOREX_SCANNER_STORAGE_GUARD_V1"
ABSOLUTE_CEILING_MIB = 500.0
CRITICAL_MIB = 475.0


def _result_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return dict(raw[0])
    return {}


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    error: str | None = None
    result: dict[str, Any] = {}
    try:
        response = store.client.rpc(
            "fx_storage_guard_v1",
            {"p_apply": True},
        ).execute()
        result = _result_payload(response.data)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    after_mib = result.get("database_mib_after")
    try:
        after_value = float(after_mib) if after_mib is not None else None
    except (TypeError, ValueError):
        after_value = None
    mode = str(result.get("mode") or "UNKNOWN").upper()
    healthy = (
        error is None
        and after_value is not None
        and after_value < CRITICAL_MIB
        and mode != "CRITICAL"
    )
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "absolute_ceiling_mib": ABSOLUTE_CEILING_MIB,
            "critical_mib": CRITICAL_MIB,
            "result": result,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "critical_execution_events_pruned": False,
            "xau_outcome_ledger_pruned": False,
        },
    )
    print(
        "CTRADER_DEMO_STORAGE_GUARD "
        f"healthy={healthy} mode={mode} database_mib_after={after_value} "
        f"ceiling_mib={ABSOLUTE_CEILING_MIB} error={error or 'NONE'}"
    )
    if error is not None:
        return 2
    if after_value is None:
        return 3
    if after_value >= ABSOLUTE_CEILING_MIB:
        return 4
    if after_value >= CRITICAL_MIB or mode == "CRITICAL":
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
