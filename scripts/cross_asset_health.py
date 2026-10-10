"""Read-only operational checks. Never loads broker tokens or places orders."""

import json
from datetime import UTC, datetime

from fx_scanner.storage.backend import create_backend_client


def run():
    c = create_backend_client()
    now = datetime.now(UTC)
    workers = [
        "ctrader_demo_eurusd_frozen_dd37",
        "ctrader_demo_xau_sd_liquidity_v342",
        "ctrader_demo_xau_v351_executor",
    ]
    rows = (
        c.table("runtime_heartbeats")
        .select("worker_name,healthy,observed_at,details")
        .in_("worker_name", workers)
        .execute()
        .data
    )
    status = []
    for worker in workers:
        found = [r for r in rows if r["worker_name"] == worker]
        row = max(found, key=lambda r: r["observed_at"]) if found else {}
        at = datetime.fromisoformat(row["observed_at"]) if row else None
        age = (now - at).total_seconds() if at and at.tzinfo else None
        healthy = row.get("healthy") is True and age is not None and 0 <= age <= 300
        status.append({"worker": worker, "healthy": healthy, "age_seconds": age})
    # Query verifies live Turso connectivity without changing schema/state.
    assert c.execute("SELECT 1").data == [{"1": 1}]
    result = {
        "database": "HEALTHY",
        "runtime": status,
        "cross_asset": "RESEARCH_ONLY_NO_EXECUTION",
        "execution_authority": False,
        "checked_at": now.isoformat(),
    }
    print(json.dumps(result))
    if not all(r["healthy"] for r in status):
        raise SystemExit("PRIMARY_RUNTIME_STALE_OR_UNHEALTHY")


if __name__ == "__main__":
    run()
