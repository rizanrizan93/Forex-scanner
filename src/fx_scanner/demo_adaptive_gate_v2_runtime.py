from __future__ import annotations

from typing import Any

from .demo_adaptive_calibration_v2_runtime import (
    _closed_rows,
    _enrich_rows,
    _feature_snapshot_context,
    _geometry_context,
    _signal_context,
    _trajectory_context,
)
from .demo_adaptive_gate_v2 import AdaptiveGateV2Policy, build_adaptive_gate_v2_policy


def load_adaptive_gate_v2_policy(
    store,
    *,
    account_id: str,
    base_floor: float,
    enabled: bool,
) -> AdaptiveGateV2Policy:
    """Build the DEMO v2 gate from the same immutable evidence used by calibration.

    Current-signal context comes directly from immutable feature-snapshot events
    keyed by signal UUID. Historical closed outcomes are enriched with immutable
    snapshots/geometry/trajectory before cohort statistics are calculated.
    """
    raw_rows = _closed_rows(store, account_id=account_id)
    signals = _signal_context(store)
    geometries = _geometry_context(store, account_id=account_id)
    trajectories = _trajectory_context(store, account_id=account_id)
    snapshots = _feature_snapshot_context(store, account_id=account_id)
    rows = _enrich_rows(raw_rows, signals, geometries, trajectories, snapshots)
    return build_adaptive_gate_v2_policy(
        rows,
        signal_context=snapshots,
        base_floor=base_floor,
        enabled=enabled,
    )


def gate_v2_heartbeat_details(policy: AdaptiveGateV2Policy) -> dict[str, Any]:
    details = policy.details()
    details.update(
        {
            "policy_effect": "DEMO_SCORE_FLOOR_ONLY" if policy.enabled else "LEGACY_FALLBACK",
            "current_signal_context_rows": len(policy.signal_context),
            "automatic_pattern_mutation": False,
            "automatic_sltp_mutation": False,
        }
    )
    return details
