from __future__ import annotations

import os
from typing import Any

from .demo_adaptive_calibration_v2 import build_adaptive_calibration_v2_report
from .storage.supabase_operational import SupabaseOperationalStore

V2_WORKER = "ctrader_demo_adaptive_calibration_v2"
CLOSED_LIMIT = 500


def _account_id() -> str:
    return str(
        os.getenv("CTRADER_ACCOUNT_ID")
        or os.getenv("CTRADER_TRADER_LOGIN")
        or ""
    ).strip()


def _rows(store: SupabaseOperationalStore, *, account_id: str) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,code,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", account_id)
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(CLOSED_LIMIT)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def run() -> int:
    account_id = _account_id()
    if not account_id:
        raise SystemExit("CTRADER_DEMO_ADAPTIVE_V2_ACCOUNT_ID_MISSING")

    store = SupabaseOperationalStore.from_env()
    rows = _rows(store, account_id=account_id)
    report = build_adaptive_calibration_v2_report(rows)
    details = report.details()
    details.update(
        {
            "data_source": "DEMO_TRADE_CLOSED",
            "closed_rows_scanned": len(rows),
            "policy_effect": "SHADOW_ONLY",
            "risk_mutation": False,
            "sltp_mutation": False,
            "production_mutation": False,
            "live_unlock": False,
        }
    )
    store.write_heartbeat(
        V2_WORKER,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )

    print(
        "CTRADER_DEMO_ADAPTIVE_CALIBRATION_V2 "
        f"stage={report.stage} decisive={report.decisive} "
        f"snapshot_coverage={report.snapshot_coverage:.3f} "
        f"cohorts={len(report.cohorts)} diagnostics={len(report.diagnostics)} "
        "policy=SHADOW_ONLY sltp_mutation=0 risk_mutation=0 production_mutation=0"
    )
    for item in report.diagnostics[:20]:
        print(
            "CTRADER_DEMO_ADAPTIVE_V2_DIAGNOSTIC "
            f"code={item.code} severity={item.severity} evidence={item.evidence_count} "
            f"scope={item.scope}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
