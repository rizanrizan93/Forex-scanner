from __future__ import annotations

import argparse
import os

from .storage.supabase_operational import SupabaseOperationalStore


_STATUSES = frozenset({"RUNNING", "SUCCESS", "FAILED", "BLOCKED"})


def record_runtime_heartbeat(worker_name: str, status: str) -> None:
    worker = str(worker_name).strip()
    normalized = str(status).strip().upper()
    if not worker or not worker.replace("_", "").isalnum():
        raise ValueError("runtime heartbeat worker name is invalid")
    if normalized not in _STATUSES:
        raise ValueError("runtime heartbeat status is invalid")
    SupabaseOperationalStore.from_env().write_heartbeat(
        worker,
        healthy=normalized in {"RUNNING", "SUCCESS"},
        lag_seconds=0.0,
        details={
            "status": normalized,
            "environment": "DEMO",
            "live_unlock": False,
            "git_sha": str(os.getenv("GITHUB_SHA") or "").strip() or None,
            "run_id": str(os.getenv("GITHUB_RUN_ID") or "").strip() or None,
            "event": str(os.getenv("GITHUB_EVENT_NAME") or "").strip() or None,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist bounded Forex DEMO runtime health")
    parser.add_argument("worker_name")
    parser.add_argument("status", choices=sorted(_STATUSES))
    args = parser.parse_args()
    record_runtime_heartbeat(args.worker_name, args.status)
    print(
        "CTRADER_DEMO_RUNTIME_HEARTBEAT_OK "
        f"worker={args.worker_name} status={args.status} live_unlock=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
