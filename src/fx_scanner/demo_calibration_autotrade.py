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
    cfg, demo_risk_pct = apply_demo_calibration_risk(cfg, max_risk_pct=3.0)
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])

    demo_safety = dict(base_policy.demo_safety)
    demo_safety["max_risk_pct"] = 3.0
    policy = replace(base_policy, mode=ExecutionMode.AUTO, demo_safety=demo_safety)

    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    store.execution_ready_score_floor = demo_execution_min
    adaptive_policy = None
    adaptive_policy_error = None
    try:
        rows = store.fetch_completed_demo_trades(limit=500)
        adaptive_policy = build_adaptive_policy_from_rows(
            rows,
            base_score_floor=demo_execution_min,
        )
    except Exception as exc:
        adaptive_policy_error = exc.__class__.__name__
    adaptive_gate_v2 = None
    adaptive_gate_v2_error = None
    try:
        adaptive_gate_v2 = load_adaptive_gate_v2_policy(
            store,
            base_score_floor=demo_execution_min,
        )
    except Exception as exc:
        adaptive_gate_v2_error = exc.__class__.__name__
    if adaptive_gate_v2 is None and adaptive_policy is not None:
        adaptive_gate_v2 = CompositeAdaptiveScorePolicy(
            legacy=adaptive_policy,
            v2=build_adaptive_gate_v2_policy(
                [],
                base_score_floor=demo_execution_min,
            ),
        )
    elif adaptive_gate_v2 is not None and adaptive_policy is not None:
        adaptive_gate_v2 = CompositeAdaptiveScorePolicy(
            legacy=adaptive_policy,
            v2=adaptive_gate_v2,
        )

    print(
        "CTRADER_DEMO_CALIBRATION_EXECUTOR "
        f"market_schedule={market_schedule_mode} "
        f"execution_floor={demo_execution_min:g} "
        f"production_default={production_execution_min:g} "
        f"risk_pct={demo_risk_pct:g} "
        f"adaptive_policy={'ACTIVE' if adaptive_policy is not None else 'NONE'} "
        f"adaptive_policy_error={adaptive_policy_error or 'NONE'} "
        f"adaptive_gate_v2={'ACTIVE' if adaptive_gate_v2 is not None else 'NONE'} "
        f"adaptive_gate_v2_error={adaptive_gate_v2_error or 'NONE'}"
    )

    account_id = _demo_account_id(policy)
    if account_id:
        try:
            capture_ctrader_demo_snapshot(policy=policy, store=store, account_id=account_id)
        except Exception as exc:
            print(f"CTRADER_DEMO_ACCOUNT_SNAPSHOT_WARN error={exc.__class__.__name__}")

    gateway = build_broker_gateway(policy)
    sink = SupabaseOrderAuditSink(store, backend="CTRADER", account_id=account_id)
    executor = CTraderDemoAutoExecutor(
        gateway,
        policy=policy,
        idempotency=None,
        audit_sink=sink,
        adaptive_policy=adaptive_gate_v2,
    )
    router = ExecutionRouter(
        mode=ExecutionMode.AUTO,
        mt5_gateway=None,
        demo_executor=executor,
        confirmation_callback=None,
        demo_backend="CTRADER",
    )

    control_gate = ControlPlaneGate(None, policy=policy)
    refresher = ControlPlaneRefreshWorker(control_gate)
    refresher.start()
    try:
        return load_adaptive_policy(
            store=store,
            router=router,
            policy=policy,
            limit=limit,
        )
    finally:
        refresher.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded cTrader DEMO calibration autotrade")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    raise SystemExit(run(limit=max(1, int(args.limit))))


if __name__ == "__main__":
    main()
