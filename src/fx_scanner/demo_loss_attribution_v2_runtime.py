from __future__ import annotations

from .demo_adaptive_calibration_v2_runtime import (
    _account_id,
    _closed_rows,
    _enrich_rows,
    _feature_snapshot_context,
    _geometry_context,
    _signal_context,
    _trajectory_context,
)
from .demo_loss_attribution_v2 import build_loss_attribution_v2
from .storage.supabase_operational import SupabaseOperationalStore

WORKER = "ctrader_demo_loss_attribution_v2"


def run() -> int:
    account_id = _account_id()
    if not account_id:
        raise SystemExit("CTRADER_DEMO_LOSS_ATTRIBUTION_V2_ACCOUNT_ID_MISSING")
    store = SupabaseOperationalStore.from_env()
    raw_rows = _closed_rows(store, account_id=account_id)
    signals = _signal_context(store)
    geometries = _geometry_context(store, account_id=account_id)
    trajectories = _trajectory_context(store, account_id=account_id)
    snapshots = _feature_snapshot_context(store, account_id=account_id)
    rows = _enrich_rows(raw_rows, signals, geometries, trajectories, snapshots)
    findings = build_loss_attribution_v2(rows)

    details = {
        "mode": "DEMO_LOSS_ATTRIBUTION_V2",
        "closed_rows_scanned": len(raw_rows),
        "findings": [item.as_dict() for item in findings[:50]],
        "finding_count": len(findings),
        "minimum_scope_evidence": 3,
        "causality_claimed": False,
        "policy_effect": "SHADOW_ONLY",
        "risk_mutation": False,
        "sltp_mutation": False,
        "production_mutation": False,
        "live_unlock": False,
    }
    store.write_heartbeat(WORKER, healthy=True, lag_seconds=0.0, details=details)
    print(
        "CTRADER_DEMO_LOSS_ATTRIBUTION_V2 "
        f"closed_rows={len(raw_rows)} findings={len(findings)} "
        "causality=CORRELATION_ONLY policy=SHADOW_ONLY"
    )
    for item in findings[:20]:
        print(
            "CTRADER_DEMO_LOSS_ATTRIBUTION_V2_FINDING "
            f"code={item.code} scope={item.scope} evidence={item.evidence_count} "
            f"losses={item.eligible_losses} rate={item.rate:.3f} severity={item.severity}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
