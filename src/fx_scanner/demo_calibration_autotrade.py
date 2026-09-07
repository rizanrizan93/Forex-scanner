from __future__ import annotations

import argparse
import os
from dataclasses import replace

from .cli import _apply_demo_technical_only_profile, _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_adaptive_calibration import (
    build_adaptive_policy_from_rows,
    load_adaptive_policy,
)
from .demo_adaptive_gate_v2 import (
    CompositeAdaptiveScorePolicy,
    build_adaptive_gate_v2_policy,
)
from .demo_adaptive_gate_v2_runtime import (
    gate_v2_heartbeat_details,
    load_adaptive_gate_v2_policy,
)
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_calibration import apply_demo_calibration_risk, apply_demo_calibration_threshold
from .demo_market_schedule import apply_demo_market_schedule
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import CTraderDemoAutoExecutor, SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore


def _safe_skip_fields(value: str) -> tuple[str, str, str | None]:
    """Return bounded, non-secret skip telemetry for GitHub Actions logs."""
    parts = str(value).split(":")
    signal_id = parts[0].strip() if parts and parts[0].strip() else "UNKNOWN"
    reason = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "UNKNOWN"
    detail = None
    if reason in {"BROKER_CAPACITY_FULL", "BROKER_SYMBOL_ALREADY_OPEN", "NOT_ELIGIBLE"}:
        if len(parts) > 2 and parts[2].strip():
            detail = parts[2].strip()
    elif reason in {
        "INTENT_ERROR",
        "BROKER_POSITION_RECONCILIATION_FAILED",
        "BROKER_SYMBOL_RECONCILIATION_FAILED",
        "EXECUTION_BLOCKED",
        "TRANSIENT_REQUEUED",
        "TRANSIENT_REQUEUE_FAILED",
        "OUTCOME_UNCERTAIN",
        "CLAIM_ERROR",
    }:
        if len(parts) > 2 and parts[2].strip():
            detail = parts[2].strip()
    return signal_id, reason, detail


def _demo_account_id(policy) -> str | None:
    account_env = str(policy.ctrader.get("account_id_env", "CTRADER_ACCOUNT_ID"))
    login_env = str(policy.ctrader.get("trader_login_env", "CTRADER_TRADER_LOGIN"))
    value = str(os.getenv(account_env) or os.getenv(login_env) or "").strip()
    return value or None


def run(*, limit: int = 10) -> int:
    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    base_policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(base_policy)
    if str(base_policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_CALIBRATION_EXECUTOR_DEMO_ONLY")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(cfg, max_risk_pct=1.0)
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])

    demo_safety = dict(base_policy.demo_safety)
    demo_safety["max_risk_pct"] = 1.0
    policy = replace(base_policy, mode=ExecutionMode.AUTO, demo_safety=demo_safety)

    symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()

    adaptive_enabled = os.getenv("CTRADER_DEMO_ADAPTIVE_CALIBRATION_ENABLED", "0").strip() == "1"
    account_id = _demo_account_id(policy)

    # Preserve the proven legacy bounded policy as fallback. Adaptive v2 does not
    # stack on top of it: once v2 is evidence-ready, v2 supersedes this floor.
    adaptive_error = None
    try:
        legacy_adaptive_policy = load_adaptive_policy(
            store,
            account_id=account_id,
            base_floor=demo_execution_min,
            enabled=adaptive_enabled,
        )
    except Exception as exc:
        adaptive_error = type(exc).__name__
        legacy_adaptive_policy = build_adaptive_policy_from_rows(
            (),
            base_floor=demo_execution_min,
            enabled=False,
        )

    adaptive_details = legacy_adaptive_policy.details()
    if adaptive_error is not None:
        adaptive_details["load_error"] = adaptive_error
    store.write_heartbeat(
        "ctrader_demo_adaptive_calibration",
        healthy=adaptive_error is None,
        lag_seconds=0.0,
        details=adaptive_details,
    )
    effective_global_floor = min(
        legacy_adaptive_policy.max_floor,
        legacy_adaptive_policy.base_floor + legacy_adaptive_policy.global_penalty,
    )
    print(
        "CTRADER_DEMO_ADAPTIVE_CALIBRATION "
        f"enabled={int(legacy_adaptive_policy.enabled)} "
        f"wave_decisive={legacy_adaptive_policy.wave_stats.decisive_system} "
        f"wave_wins={legacy_adaptive_policy.wave_stats.wins} wave_losses={legacy_adaptive_policy.wave_stats.losses} "
        f"legacy_decisive={legacy_adaptive_policy.legacy_stats.decisive_system} "
        f"legacy_wins={legacy_adaptive_policy.legacy_stats.wins} legacy_losses={legacy_adaptive_policy.legacy_stats.losses} "
        f"global_penalty={legacy_adaptive_policy.global_penalty:.2f} "
        f"effective_global_floor={effective_global_floor:.2f} "
        f"root_cause={legacy_adaptive_policy.root_cause} "
        f"load_error={adaptive_error or 'NONE'}"
    )

    v2_error = None
    try:
        if account_id:
            v2_policy = load_adaptive_gate_v2_policy(
                store,
                account_id=account_id,
                base_floor=demo_execution_min,
                enabled=adaptive_enabled,
            )
        else:
            v2_policy = build_adaptive_gate_v2_policy(
                (),
                signal_context={},
                base_floor=demo_execution_min,
                enabled=False,
            )
            v2_error = "ACCOUNT_ID_MISSING"
    except Exception as exc:
        v2_error = type(exc).__name__
        v2_policy = build_adaptive_gate_v2_policy(
            (),
            signal_context={},
            base_floor=demo_execution_min,
            enabled=False,
        )

    v2_details = gate_v2_heartbeat_details(v2_policy)
    if v2_error is not None:
        v2_details["load_error"] = v2_error
    store.write_heartbeat(
        "ctrader_demo_adaptive_gate_v2",
        healthy=v2_error is None,
        lag_seconds=0.0,
        details=v2_details,
    )
    adaptive_policy = CompositeAdaptiveScorePolicy(
        legacy_policy=legacy_adaptive_policy,
        v2_policy=v2_policy,
    )
    composite_details = adaptive_policy.details()
    print(
        "CTRADER_DEMO_ADAPTIVE_GATE_V2 "
        f"enabled={int(v2_policy.enabled)} wave_decisive={v2_policy.wave_decisive} "
        f"snapshot_coverage={v2_policy.snapshot_coverage:.3f} "
        f"max_penalty={v2_policy.max_penalty:.2f} "
        f"active_policy={'V2' if v2_policy.enabled else 'LEGACY_FALLBACK'} "
        f"penalty_stacking=0 root_cause={v2_policy.root_cause} "
        f"load_error={v2_error or 'NONE'}"
    )

    gate = ControlPlaneGate(
        max_age_seconds=float(policy.live_safety.get("control_state_max_age_seconds", 5))
    )
    router = ExecutionRouter(
        policy,
        gateway=gateway,
        session=session,
        control_gate=gate,
        audit_sink=SupabaseOrderAuditSink(store),
    )
    executor = CTraderDemoAutoExecutor(
        cfg=cfg,
        policy=policy,
        gateway=gateway,
        router=router,
        store=store,
        adaptive_policy=adaptive_policy,
    )
    control_worker = ControlPlaneRefreshWorker(
        store,
        gate,
        interval_seconds=min(
            1.0,
            max(0.25, float(policy.live_safety.get("control_state_max_age_seconds", 5)) / 3.0),
        ),
    )
    control_worker.refresh_once()
    control_worker.start()
    try:
        open_positions_before = int(gateway.position_count())
        max_positions = int(policy.demo_safety["max_concurrent_positions"])
        weekend_crypto_only = market_schedule_mode == "WEEKEND_CRYPTO_24X7"
        poll_limit = 100 if weekend_crypto_only else int(limit)
        print(
            "CTRADER_DEMO_MARKET_SCHEDULE "
            f"mode={market_schedule_mode} universe={','.join(symbols)} poll_limit={poll_limit}"
        )
        print(
            "CTRADER_DEMO_BROKER_EXPOSURE "
            f"open_positions={open_positions_before} max_positions={max_positions} "
            f"free_slots={max(0, max_positions - open_positions_before)} "
            "source=CTRADER_LIVE phase=BEFORE"
        )
        print(
            "CTRADER_DEMO_LIVE_ENTRY_REVALIDATION "
            f"max_entry_drift_r={executor.max_entry_drift_r:g} "
            f"minimum_tp2_rr={float(cfg.strategy['trade_plan']['minimum_tp2_rr']):g} "
            "fresh_quote=REQUIRED"
        )

        report = executor.poll_once(limit=poll_limit)

        for skipped in report.skipped[:20]:
            signal_id, reason, detail = _safe_skip_fields(skipped)
            line = f"CTRADER_DEMO_SKIP_DETAIL signal_id={signal_id} reason={reason}"
            if detail is not None:
                line += f" detail={detail}"
            print(line)

        pnl_snapshot = capture_ctrader_demo_snapshot(
            session=session,
            store=store,
            phase="AFTER",
        )
        snapshot_positions_after = len(pnl_snapshot.positions)
        open_positions_after = int(gateway.position_count())
        free_slots_after = max(0, max_positions - open_positions_after)
        print(
            "CTRADER_DEMO_BROKER_EXPOSURE "
            f"open_positions={open_positions_after} max_positions={max_positions} "
            f"free_slots={free_slots_after} snapshot_positions={snapshot_positions_after} "
            "source=CTRADER_LIVE phase=AFTER"
        )

        account = pnl_snapshot.account
        position_floating = {
            position.symbol: float(position.profit)
            for position in pnl_snapshot.positions
            if position.profit is not None
        }
        store.write_heartbeat(
            "ctrader_demo_autotrade",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "AUTO",
                "environment": "DEMO",
                "market_schedule_mode": market_schedule_mode,
                "active_universe": symbols,
                "calibration_threshold": demo_execution_min,
                "adaptive_calibration": adaptive_details,
                "adaptive_gate_v2": v2_details,
                "adaptive_score_policy": composite_details,
                "risk_per_trade_pct": demo_risk_pct,
                "max_risk_pct": float(policy.demo_safety["max_risk_pct"]),
                "max_entry_drift_r": executor.max_entry_drift_r,
                "open_positions": open_positions_after,
                "max_positions": max_positions,
                "free_slots": free_slots_after,
                "broker_snapshot_positions": snapshot_positions_after,
                "broker_position_source": "CTRADER_RECONCILE_ACCOUNT_WIDE",
                "broker_exposure_source": "CTRADER_LIVE",
                "balance": float(account.balance),
                "equity": float(account.equity),
                "floating_pnl": float(account.floating_profit or 0.0),
                "margin": float(account.margin or 0.0),
                "margin_free": float(account.margin_free or 0.0),
                "position_floating_pnl": position_floating,
                "broker_snapshot_id": pnl_snapshot.snapshot_id,
                "manual_close_detection": "NEXT_POLL",
                "scanned": report.scanned,
                "eligible": report.eligible,
                "claimed": report.claimed,
                "executed": report.executed,
                "skipped": list(report.skipped[:20]),
            },
        )
        print(
            "CTRADER_DEMO_CALIBRATION_AUTOTRADE_OK "
            f"threshold={demo_execution_min:g} production_default={production_execution_min:g} "
            f"adaptive_enabled={int(adaptive_enabled)} "
            f"adaptive_global_floor={effective_global_floor:.2f} "
            f"adaptive_policy={'V2' if v2_policy.enabled else 'LEGACY_FALLBACK'} "
            f"risk_pct={demo_risk_pct:g} max_risk_pct={float(policy.demo_safety['max_risk_pct']):g} "
            f"max_entry_drift_r={executor.max_entry_drift_r:g} "
            f"market_schedule={market_schedule_mode} "
            f"open_positions={open_positions_after} free_slots={free_slots_after} "
            f"snapshot_positions={snapshot_positions_after} "
            f"floating_pnl={float(account.floating_profit or 0.0):.8g} "
            f"equity={float(account.equity):.8g} "
            f"scanned={report.scanned} eligible={report.eligible} "
            f"claimed={report.claimed} executed={report.executed} "
            f"skipped={len(report.skipped)}"
        )
        return 0
    finally:
        control_worker.stop()
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    return run(limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())