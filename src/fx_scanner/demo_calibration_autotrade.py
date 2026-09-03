from __future__ import annotations

import argparse
from dataclasses import replace

from .cli import _apply_demo_technical_only_profile, _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_calibration import apply_demo_calibration_risk, apply_demo_calibration_threshold
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import CTraderDemoAutoExecutor, SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore


def run(*, limit: int = 10) -> int:
    cfg = load_project_config(None)
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
        open_before = int(gateway.position_count())
        max_positions = int(policy.demo_safety["max_concurrent_positions"])
        print(
            "CTRADER_DEMO_BROKER_EXPOSURE "
            f"open_positions={open_before} max_positions={max_positions} "
            f"free_slots={max(0, max_positions - open_before)} source=CTRADER_LIVE phase=BEFORE"
        )

        report = executor.poll_once(limit=int(limit))

        open_after = int(gateway.position_count())
        print(
            "CTRADER_DEMO_BROKER_EXPOSURE "
            f"open_positions={open_after} max_positions={max_positions} "
            f"free_slots={max(0, max_positions - open_after)} source=CTRADER_LIVE phase=AFTER"
        )

        store.write_heartbeat(
            "ctrader_demo_autotrade",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "AUTO",
                "environment": "DEMO",
                "calibration_threshold": demo_execution_min,
                "risk_per_trade_pct": demo_risk_pct,
                "max_risk_pct": float(policy.demo_safety["max_risk_pct"]),
                "open_positions": open_after,
                "max_positions": max_positions,
                "free_slots": max(0, max_positions - open_after),
                "broker_exposure_source": "CTRADER_LIVE",
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
            f"risk_pct={demo_risk_pct:g} max_risk_pct={float(policy.demo_safety['max_risk_pct']):g} "
            f"open_positions={open_after} free_slots={max(0, max_positions - open_after)} "
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
