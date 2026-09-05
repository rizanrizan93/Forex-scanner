from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .demo_broker_pnl import TRAJECTORY_WORKER
from .storage.supabase_operational import SupabaseOperationalStore


@dataclass(frozen=True, slots=True)
class TrajectoryFinalizeReport:
    closed_scanned: int
    finalized: int
    duplicates: int
    missing_trajectory: int


def _account_id() -> str:
    return str(
        os.getenv("CTRADER_ACCOUNT_ID")
        or os.getenv("CTRADER_TRADER_LOGIN")
        or ""
    ).strip()


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _trajectory_positions(store: SupabaseOperationalStore) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("details")
        .eq("worker_name", TRAJECTORY_WORKER)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows or not isinstance(rows[0].get("details"), dict):
        return {}
    positions = rows[0]["details"].get("positions")
    if not isinstance(positions, dict):
        return {}
    return {
        str(position_id): dict(payload)
        for position_id, payload in positions.items()
        if isinstance(payload, dict)
    }


def _closed_events(store: SupabaseOperationalStore, *, account_id: str, limit: int = 100):
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,broker_order_id,code,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", account_id)
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(int(limit))
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _already_finalized(store: SupabaseOperationalStore, *, account_id: str, event_key: str) -> bool:
    response = (
        store.client.table("broker_order_events")
        .select("id")
        .eq("backend", "CTRADER")
        .eq("account_id", account_id)
        .eq("broker_order_id", event_key)
        .eq("event_type", "DEMO_TRADE_TRAJECTORY_FINAL")
        .limit(1)
        .execute()
    )
    return bool(response.data or [])


def finalize_trajectories(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
    limit: int = 100,
) -> TrajectoryFinalizeReport:
    trajectories = _trajectory_positions(store)
    closed = _closed_events(store, account_id=account_id, limit=limit)
    finalized = duplicates = missing = 0

    for event in reversed(closed):
        payload = event.get("payload")
        payload = dict(payload) if isinstance(payload, dict) else {}
        signal_id = str(event.get("signal_key") or payload.get("signal_id") or "").strip()
        position_id = str(payload.get("position_id") or "").strip()
        deal_id = str(payload.get("closing_deal_id") or "").strip()
        if not signal_id or not position_id or not deal_id:
            missing += 1
            continue
        trajectory = trajectories.get(position_id)
        if not trajectory or int(trajectory.get("sample_count", 0) or 0) <= 0:
            missing += 1
            continue
        event_key = f"TRAJECTORY:{deal_id}"
        if _already_finalized(store, account_id=account_id, event_key=event_key):
            duplicates += 1
            continue

        sampled_mae_r = _finite(trajectory.get("sampled_mae_r"))
        sampled_mfe_r = _finite(trajectory.get("sampled_mfe_r"))
        r_ready = sampled_mae_r is not None and sampled_mfe_r is not None
        r_normalization = (
            "ACTUAL_BROKER_OPEN_TO_ACTIVE_SL_PRICE_R"
            if r_ready
            else "DEFERRED_UNTIL_EXACT_BROKER_RISK_DENOMINATOR"
        )
        final_payload = {
            "signal_id": signal_id,
            "position_id": position_id,
            "closing_deal_id": deal_id,
            "symbol": payload.get("symbol") or trajectory.get("symbol"),
            "direction": payload.get("direction"),
            "setup_type": payload.get("setup_type"),
            "entry_mode": payload.get("entry_mode", "LEGACY"),
            "confirmation": payload.get("confirmation", "LEGACY"),
            "exit_type": payload.get("exit_type") or event.get("code"),
            "net_pnl_estimate": payload.get("net_pnl_estimate"),
            "sample_count": int(trajectory.get("sample_count", 0) or 0),
            "sampled_mae_pnl": trajectory.get("sampled_mae_pnl"),
            "sampled_mfe_pnl": trajectory.get("sampled_mfe_pnl"),
            "last_sampled_floating_pnl": trajectory.get("last_floating_pnl"),
            "sampling_started_at": trajectory.get("sampling_started_at"),
            "last_sample_at": trajectory.get("last_sample_at"),
            "trajectory_scope": trajectory.get("trajectory_scope", "SINCE_FIRST_OBSERVED"),
            "metric": trajectory.get("metric", "NET_UNREALIZED_PNL_ACCOUNT_CURRENCY"),
            "target_sample_cadence_seconds": trajectory.get("target_sample_cadence_seconds", 120),
            "initial_risk_price": trajectory.get("initial_risk_price"),
            "last_price_r": trajectory.get("last_price_r"),
            "mae_r": sampled_mae_r,
            "mfe_r": sampled_mfe_r,
            "r_metric": trajectory.get("r_metric", "BROKER_EXECUTABLE_PRICE_R_EXCLUDING_COSTS"),
            "r_normalization": r_normalization,
            "r_ready": r_ready,
            "automatic_exit_mutation": False,
            "source": "CTRADER_PIPELINE_SAMPLED_TRAJECTORY",
        }
        store.record_order_event(
            backend="CTRADER",
            account_id=account_id,
            signal_key=signal_id,
            event_type="DEMO_TRADE_TRAJECTORY_FINAL",
            broker_order_id=event_key,
            accepted=True,
            code="SAMPLED_MAE_MFE_R" if r_ready else "SAMPLED_MAE_MFE",
            message="sampled trade trajectory finalized",
            payload=final_payload,
        )
        finalized += 1
        print(
            "CTRADER_DEMO_TRADE_TRAJECTORY_FINAL "
            f"signal_id={signal_id} symbol={final_payload['symbol']} position_id={position_id} "
            f"samples={final_payload['sample_count']} "
            f"sampled_mae_pnl={final_payload['sampled_mae_pnl']} "
            f"sampled_mfe_pnl={final_payload['sampled_mfe_pnl']} "
            f"mae_r={final_payload['mae_r']} mfe_r={final_payload['mfe_r']} "
            f"r_ready={int(r_ready)} exit_type={final_payload['exit_type']} "
            f"entry_mode={final_payload['entry_mode']}"
        )

    return TrajectoryFinalizeReport(len(closed), finalized, duplicates, missing)


def run() -> int:
    account_id = _account_id()
    if not account_id:
        raise SystemExit("CTRADER_DEMO_TRAJECTORY_ACCOUNT_ID_MISSING")
    store = SupabaseOperationalStore.from_env()
    try:
        report = finalize_trajectories(store, account_id=account_id)
        store.write_heartbeat(
            "ctrader_demo_trajectory_finalizer",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "SAMPLED_MAE_MFE_R",
                "closed_scanned": report.closed_scanned,
                "finalized": report.finalized,
                "duplicates": report.duplicates,
                "missing_trajectory": report.missing_trajectory,
                "metric": "NET_UNREALIZED_PNL_ACCOUNT_CURRENCY",
                "r_metric": "BROKER_EXECUTABLE_PRICE_R_EXCLUDING_COSTS",
                "trajectory_scope": "SINCE_FIRST_OBSERVED",
                "r_normalization": "ACTUAL_BROKER_OPEN_TO_ACTIVE_SL_PRICE_R_WHEN_AVAILABLE",
                "automatic_exit_mutation": False,
            },
        )
        print(
            "CTRADER_DEMO_TRAJECTORY_FINALIZER_OK "
            f"closed_scanned={report.closed_scanned} finalized={report.finalized} "
            f"duplicates={report.duplicates} missing={report.missing_trajectory}"
        )
        return 0
    except Exception as exc:
        print(f"CTRADER_DEMO_TRAJECTORY_FINALIZER_ERROR type={type(exc).__name__}")
        raise


if __name__ == "__main__":
    raise SystemExit(run())