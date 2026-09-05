from __future__ import annotations

import os
from typing import Any

from .demo_adaptive_calibration_v2 import build_adaptive_calibration_v2_report
from .storage.supabase_operational import SupabaseOperationalStore

V2_WORKER = "ctrader_demo_adaptive_calibration_v2"
CLOSED_LIMIT = 500
SIGNAL_LIMIT = 1000
GEOMETRY_LIMIT = 1500
TRAJECTORY_LIMIT = 1000
FEATURE_SNAPSHOT_LIMIT = 1500


def _account_id() -> str:
    return str(
        os.getenv("CTRADER_ACCOUNT_ID")
        or os.getenv("CTRADER_TRADER_LOGIN")
        or ""
    ).strip()


def _closed_rows(store: SupabaseOperationalStore, *, account_id: str) -> tuple[dict[str, Any], ...]:
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


def _signal_context(store: SupabaseOperationalStore) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("signals")
        .select(
            "id,observed_at,symbol,direction,setup_type,final_score,"
            "h1_bias,h4_bias,entry_low,entry_high,sl,tp1,tp2,rr1,rr2"
        )
        .order("observed_at", desc=True)
        .limit(SIGNAL_LIMIT)
        .execute()
    )
    return {
        str(row.get("id")): dict(row)
        for row in (response.data or [])
        if row.get("id")
    }


def _event_payload_context(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
    event_type: str,
    limit: int,
) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", account_id)
        .eq("event_type", event_type)
        .order("observed_at", desc=True)
        .limit(int(limit))
        .execute()
    )
    output: dict[str, dict[str, Any]] = {}
    for row in response.data or []:
        signal_id = str(row.get("signal_key") or "").strip()
        payload = row.get("payload")
        if signal_id and signal_id not in output and isinstance(payload, dict):
            output[signal_id] = dict(payload)
    return output


def _geometry_context(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
) -> dict[str, dict[str, Any]]:
    return _event_payload_context(
        store,
        account_id=account_id,
        event_type="DEMO_SIGNAL_GEOMETRY",
        limit=GEOMETRY_LIMIT,
    )


def _feature_snapshot_context(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
) -> dict[str, dict[str, Any]]:
    """Load immutable decision-time Adaptive Calibration v2 features."""
    return _event_payload_context(
        store,
        account_id=account_id,
        event_type="DEMO_SIGNAL_FEATURE_SNAPSHOT_V2",
        limit=FEATURE_SNAPSHOT_LIMIT,
    )


def _trajectory_context(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
) -> dict[str, dict[str, Any]]:
    """Load finalized sampled trajectory evidence keyed by signal UUID.

    Current trajectory extrema are account-currency P&L samples, not R. They are
    attached for attribution only and MUST NOT be silently treated as mae_r/mfe_r.
    """
    return _event_payload_context(
        store,
        account_id=account_id,
        event_type="DEMO_TRADE_TRAJECTORY_FINAL",
        limit=TRAJECTORY_LIMIT,
    )


def _regime_proxy(signal: dict[str, Any]) -> str:
    direction = str(signal.get("direction", "") or "").upper()
    h1 = str(signal.get("h1_bias", "") or "").upper()
    h4 = str(signal.get("h4_bias", "") or "").upper()
    bullish = {"LONG", "BULL", "BULLISH", "UP", "UPTREND"}
    bearish = {"SHORT", "BEAR", "BEARISH", "DOWN", "DOWNTREND"}
    if direction == "LONG" and h1 in bullish and h4 in bullish:
        return "TREND"
    if direction == "SHORT" and h1 in bearish and h4 in bearish:
        return "TREND"
    if h1 and h4 and h1 == h4 and h1 not in bullish | bearish:
        return "RANGE"
    if h1 or h4:
        return "MIXED"
    return "UNKNOWN"


def _attach_trajectory(payload: dict[str, Any], trajectory: dict[str, Any]) -> None:
    if not trajectory:
        return
    for key in (
        "position_id",
        "closing_deal_id",
        "sample_count",
        "sampled_mae_pnl",
        "sampled_mfe_pnl",
        "last_sampled_floating_pnl",
        "sampling_started_at",
        "last_sample_at",
        "trajectory_scope",
        "target_sample_cadence_seconds",
    ):
        value = trajectory.get(key)
        if payload.get(key) is None and value is not None:
            payload[key] = value

    for key in ("mae_r", "mfe_r"):
        value = trajectory.get(key)
        if payload.get(key) is None and value is not None:
            payload[key] = value
    payload["trajectory_metric"] = trajectory.get(
        "metric", "NET_UNREALIZED_PNL_ACCOUNT_CURRENCY"
    )
    payload["trajectory_r_normalization"] = trajectory.get(
        "r_normalization", "DEFERRED_UNTIL_EXACT_BROKER_RISK_DENOMINATOR"
    )
    payload["trajectory_attribution_only"] = bool(
        payload.get("mae_r") is None or payload.get("mfe_r") is None
    )


def _attach_feature_snapshot(payload: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Attach immutable decision-time features without overriding trade truth."""
    if not snapshot:
        return
    for key, value in snapshot.items():
        if key in {"signal_id", "run_id", "source"}:
            continue
        if payload.get(key) is None and value is not None:
            payload[key] = value
    payload["v2_feature_snapshot_version"] = snapshot.get("snapshot_version", 2)
    payload["v2_feature_snapshot_complete"] = bool(
        snapshot.get("snapshot_complete_for_regime", False)
    )
    payload["v2_regime_source"] = (
        "DEMO_SIGNAL_FEATURE_SNAPSHOT_V2"
        if str(snapshot.get("regime", "") or "").strip()
        else "FALLBACK"
    )


def _enrich_rows(
    rows: tuple[dict[str, Any], ...],
    signals: dict[str, dict[str, Any]],
    geometries: dict[str, dict[str, Any]],
    trajectories: dict[str, dict[str, Any]] | None = None,
    feature_snapshots: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    trajectories = trajectories or {}
    feature_snapshots = feature_snapshots or {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = dict(item.get("payload")) if isinstance(item.get("payload"), dict) else {}
        signal_id = str(item.get("signal_key") or payload.get("signal_id") or "").strip()
        signal = signals.get(signal_id, {})
        geometry = geometries.get(signal_id, {})
        trajectory = trajectories.get(signal_id, {})
        feature_snapshot = feature_snapshots.get(signal_id, {})

        # Closed-trade payload is always authoritative. The immutable feature
        # snapshot then outranks older geometry/signal fallbacks for decision-time
        # context such as regime, ATR, evidence components, and structure.
        _attach_feature_snapshot(payload, feature_snapshot)
        for key, value in geometry.items():
            if payload.get(key) is None and value is not None:
                payload[key] = value

        for target, source in (
            ("symbol", "symbol"),
            ("direction", "direction"),
            ("setup_type", "setup_type"),
            ("final_score", "final_score"),
            ("entry_low", "entry_low"),
            ("entry_high", "entry_high"),
            ("planned_sl", "sl"),
            ("planned_tp1", "tp1"),
            ("planned_tp2", "tp2"),
            ("rr1", "rr1"),
            ("rr2", "rr2"),
        ):
            if payload.get(target) is None and signal.get(source) is not None:
                payload[target] = signal.get(source)

        _attach_trajectory(payload, trajectory)

        if not str(payload.get("regime", "") or "").strip() and signal:
            payload["regime"] = _regime_proxy(signal)
            payload["v2_regime_source"] = "SIGNALS_H1_H4_PROXY"
        if signal:
            payload.setdefault("h1_bias", signal.get("h1_bias"))
            payload.setdefault("h4_bias", signal.get("h4_bias"))
        sources = ["DEMO_TRADE_CLOSED"]
        if feature_snapshot:
            sources.append("DEMO_SIGNAL_FEATURE_SNAPSHOT_V2")
        if geometry:
            sources.append("DEMO_SIGNAL_GEOMETRY")
        if signal:
            sources.append("SIGNALS")
        if trajectory:
            sources.append("DEMO_TRADE_TRAJECTORY_FINAL")
        payload["v2_context_source"] = "+".join(sources)
        item["payload"] = payload
        enriched.append(item)
    return tuple(enriched)


def run() -> int:
    account_id = _account_id()
    if not account_id:
        raise SystemExit("CTRADER_DEMO_ADAPTIVE_V2_ACCOUNT_ID_MISSING")

    store = SupabaseOperationalStore.from_env()
    raw_rows = _closed_rows(store, account_id=account_id)
    signals = _signal_context(store)
    geometries = _geometry_context(store, account_id=account_id)
    trajectories = _trajectory_context(store, account_id=account_id)
    feature_snapshots = _feature_snapshot_context(store, account_id=account_id)
    rows = _enrich_rows(
        raw_rows,
        signals,
        geometries,
        trajectories,
        feature_snapshots,
    )
    report = build_adaptive_calibration_v2_report(rows)
    details = report.details()
    trajectory_joined = sum(
        1
        for row in rows
        if "DEMO_TRADE_TRAJECTORY_FINAL"
        in str((row.get("payload") or {}).get("v2_context_source", ""))
    )
    trajectory_r_ready = sum(
        1
        for row in rows
        if (row.get("payload") or {}).get("mae_r") is not None
        and (row.get("payload") or {}).get("mfe_r") is not None
    )
    feature_snapshot_joined = sum(
        1
        for row in rows
        if "DEMO_SIGNAL_FEATURE_SNAPSHOT_V2"
        in str((row.get("payload") or {}).get("v2_context_source", ""))
    )
    feature_snapshot_complete = sum(
        1
        for row in rows
        if bool((row.get("payload") or {}).get("v2_feature_snapshot_complete", False))
    )
    details.update(
        {
            "data_source": "DEMO_TRADE_CLOSED+DEMO_SIGNAL_FEATURE_SNAPSHOT_V2+DEMO_SIGNAL_GEOMETRY+SIGNALS+DEMO_TRADE_TRAJECTORY_FINAL",
            "closed_rows_scanned": len(raw_rows),
            "signal_context_rows": len(signals),
            "geometry_context_rows": len(geometries),
            "feature_snapshot_context_rows": len(feature_snapshots),
            "feature_snapshot_joined_closed_rows": feature_snapshot_joined,
            "feature_snapshot_complete_closed_rows": feature_snapshot_complete,
            "trajectory_context_rows": len(trajectories),
            "trajectory_joined_closed_rows": trajectory_joined,
            "trajectory_r_ready_closed_rows": trajectory_r_ready,
            "trajectory_currency_pnl_is_not_r": True,
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
        f"feature_snapshots={len(feature_snapshots)} feature_joined={feature_snapshot_joined} "
        f"geometry_rows={len(geometries)} trajectory_rows={len(trajectories)} "
        f"trajectory_joined={trajectory_joined} trajectory_r_ready={trajectory_r_ready} "
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