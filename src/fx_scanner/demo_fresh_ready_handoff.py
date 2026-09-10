from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Iterable

from .config import load_project_config as _load_project_config
from .execution.policy import ExecutionPolicy, load_execution_policy as _load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
DEMO_POSITION_CAP_ENV = "CTRADER_DEMO_MAX_CONCURRENT_POSITIONS"
DEMO_POSITION_CAP_CEILING = 10
DEMO_ORDER_LOT_CAP_ENV = "CTRADER_DEMO_MAX_ORDER_LOTS"
DEMO_ORDER_LOT_CAP_CEILING = 0.01
DEMO_STACKING_ENV = "CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING"
DEMO_STACK_MIN_SCORE_ENV = "CTRADER_DEMO_STACK_MIN_SCORE"
DEMO_STACK_MIN_COVERAGE_ENV = "CTRADER_DEMO_STACK_MIN_COVERAGE"
DEMO_STACK_MIN_RR2_ENV = "CTRADER_DEMO_STACK_MIN_RR2"
DEMO_STACK_MAX_POSITIONS_ENV = "CTRADER_DEMO_MAX_SAME_SYMBOL_POSITIONS"
DEMO_STACK_MIN_SPACING_ENV = "CTRADER_DEMO_MIN_STACK_SPACING_SECONDS"
DEMO_PORTFOLIO_RISK_CAP_ENV = "CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT"
DEMO_MARGIN_USAGE_CAP_ENV = "CTRADER_DEMO_MAX_MARGIN_FREE_USAGE_PCT"
DEMO_MIN_LIVE_RR_ENV = "CTRADER_DEMO_MIN_LIVE_RR"
DEMO_MIN_LIVE_RR_FLOOR = 1.0


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _bounded_float_env(
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not isfinite(value) or not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be in [{minimum},{maximum}]")
    return value


def _bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be in [{minimum},{maximum}]")
    return value


def _bool_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip().upper()
    if value in {"1", "TRUE", "YES", "ON"}:
        return True
    if value in {"0", "FALSE", "NO", "OFF"}:
        return False
    raise RuntimeError(f"{name} must be boolean-like 0/1")


def load_demo_project_config(root=None):
    """Load canonical project config plus a bounded DEMO-only live-RR floor.

    Discovery/plan generation keeps the canonical minimum TP2 RR contract. Only
    the DEMO autotrade handoff may accept fresh broker-price deterioration down
    to 1:1. Entry, SL and TP geometry are never rewritten by this override.
    """
    cfg = _load_project_config(root)
    strategy = dict(cfg.strategy)
    trade_plan = dict(strategy.get("trade_plan", {}))
    canonical_min_rr = float(trade_plan["minimum_tp2_rr"])
    demo_min_live_rr = _bounded_float_env(
        DEMO_MIN_LIVE_RR_ENV,
        default=DEMO_MIN_LIVE_RR_FLOOR,
        minimum=DEMO_MIN_LIVE_RR_FLOOR,
        maximum=canonical_min_rr,
    )
    trade_plan["minimum_tp2_rr"] = demo_min_live_rr
    strategy["trade_plan"] = trade_plan
    return replace(cfg, strategy=strategy)


def load_demo_execution_policy(root=None) -> ExecutionPolicy:
    """Load canonical policy plus an explicit bounded DEMO runtime profile.

    DEMO may opt into up to ten total positions with a hard 0.01 lot/order cap.
    Broker-native stop-loss loss, aggregate risk, margin, spread, correlation and
    geometry checks remain authoritative. Same-symbol stacking remains behind
    independent high-conviction gates. LIVE remains untouched.
    """
    policy = _load_execution_policy(root)
    demo_safety = dict(policy.demo_safety)

    default_cap = int(demo_safety["max_concurrent_positions"])
    demo_safety["max_concurrent_positions"] = _bounded_int_env(
        DEMO_POSITION_CAP_ENV,
        default=default_cap,
        minimum=1,
        maximum=DEMO_POSITION_CAP_CEILING,
    )

    default_lots = float(demo_safety["max_order_lots"])
    max_order_lots = _bounded_float_env(
        DEMO_ORDER_LOT_CAP_ENV,
        default=default_lots,
        minimum=0.01,
        maximum=DEMO_ORDER_LOT_CAP_CEILING,
    )
    demo_safety["max_order_lots"] = max_order_lots

    allow_stacking = _bool_env(DEMO_STACKING_ENV, default=False)
    demo_safety["allow_same_symbol_stacking"] = allow_stacking
    demo_safety["stack_min_score"] = _bounded_float_env(
        DEMO_STACK_MIN_SCORE_ENV,
        default=85.0,
        minimum=70.0,
        maximum=100.0,
    )
    demo_safety["stack_min_coverage"] = _bounded_float_env(
        DEMO_STACK_MIN_COVERAGE_ENV,
        default=0.90,
        minimum=0.80,
        maximum=1.0,
    )
    demo_safety["stack_min_rr2"] = _bounded_float_env(
        DEMO_STACK_MIN_RR2_ENV,
        default=2.0,
        minimum=1.5,
        maximum=5.0,
    )
    max_same_symbol_positions = _bounded_int_env(
        DEMO_STACK_MAX_POSITIONS_ENV,
        default=3,
        minimum=1,
        maximum=3,
    )
    demo_safety["max_same_symbol_positions"] = max_same_symbol_positions
    demo_safety["min_stack_spacing_seconds"] = _bounded_float_env(
        DEMO_STACK_MIN_SPACING_ENV,
        default=300.0,
        minimum=0.0,
        maximum=3600.0,
    )
    demo_safety["max_same_symbol_lots"] = max_order_lots * max_same_symbol_positions
    demo_safety["max_portfolio_risk_pct"] = _bounded_float_env(
        DEMO_PORTFOLIO_RISK_CAP_ENV,
        default=6.0,
        minimum=0.5,
        maximum=12.0,
    )
    demo_safety["max_margin_free_usage_pct"] = _bounded_float_env(
        DEMO_MARGIN_USAGE_CAP_ENV,
        default=25.0,
        minimum=5.0,
        maximum=50.0,
    )
    return replace(policy, demo_safety=demo_safety)


def fresh_execution_ready_rows(
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    """Return newest durable EXECUTION_READY rows that are still executable by time.

    This is intentionally a handoff filter only. It never promotes WATCH/ARMED/
    SETUP_FORMING rows and never changes score, guards, entry, SL, TP or RR.
    """
    current = now.astimezone(UTC)
    cutoff = current - timedelta(seconds=float(max_age_seconds))
    fresh: list[tuple[datetime, dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        if str(row.get("state", "")).upper() != "EXECUTION_READY":
            continue
        observed = _dt(row.get("observed_at"))
        expires = _dt(row.get("expires_at"))
        if observed is None or observed < cutoff or observed > current + timedelta(seconds=1):
            continue
        if expires is not None and current > expires:
            continue
        fresh.append((observed, row))
    fresh.sort(key=lambda item: item[0], reverse=True)
    return tuple(row for _observed, row in fresh[: max(0, int(limit))])


def install_fresh_execution_ready_handoff(*, max_age_seconds: float) -> None:
    """Replace the DEMO read boundary with a freshness-aware durable query.

    The executor still performs its own timestamp, quote, RR and geometry checks.
    This only prevents an old EXECUTION_READY backlog from occupying the bounded
    executor poll while a newer signal is waiting behind it.
    """
    age_limit = float(max_age_seconds)
    if age_limit <= 0:
        raise ValueError("max_age_seconds must be positive")

    def _list_execution_ready_signals(self, *, limit: int = 10):
        requested = max(1, int(limit))
        fetch_limit = max(50, min(250, requested * 10))
        response = (
            self.client.table("signals")
            .select("*")
            .eq("state", "EXECUTION_READY")
            .order("observed_at", desc=True)
            .limit(fetch_limit)
            .execute()
        )
        rows = tuple(dict(row) for row in (response.data or []))
        return fresh_execution_ready_rows(
            rows,
            now=datetime.now(tz=UTC),
            max_age_seconds=age_limit,
            limit=requested,
        )

    SupabaseOperationalStore.list_execution_ready_signals = _list_execution_ready_signals


def main() -> int:
    policy = load_demo_execution_policy(None)
    max_age_seconds = float(policy.order.get("max_signal_age_seconds", 300))
    install_fresh_execution_ready_handoff(max_age_seconds=max_age_seconds)

    from . import demo_calibration_autotrade as calibration_runtime

    calibration_runtime.load_execution_policy = load_demo_execution_policy
    calibration_runtime.load_project_config = load_demo_project_config

    from .demo_broker_risk_sizing import install_demo_broker_native_risk_sizing
    from .demo_conditional_stacking import install_demo_conditional_stacking
    from .demo_conviction_sizing import install_demo_conviction_sizing

    install_demo_conviction_sizing()
    install_demo_broker_native_risk_sizing()
    install_demo_conditional_stacking()

    demo_cfg = load_demo_project_config(None)
    print(
        "CTRADER_DEMO_DYNAMIC_EXECUTION_POLICY "
        f"max_order_lots={float(policy.demo_safety['max_order_lots']):.2f} "
        f"portfolio_risk_cap_pct={float(policy.demo_safety['max_portfolio_risk_pct']):.2f} "
        f"margin_free_usage_cap_pct={float(policy.demo_safety['max_margin_free_usage_pct']):.2f} "
        f"min_live_rr={float(demo_cfg.strategy['trade_plan']['minimum_tp2_rr']):.2f} "
        f"stacking={int(bool(policy.demo_safety['allow_same_symbol_stacking']))} "
        f"stack_min_score={float(policy.demo_safety['stack_min_score']):.2f} "
        f"stack_min_coverage={float(policy.demo_safety['stack_min_coverage']):.2f} "
        f"stack_min_rr2={float(policy.demo_safety['stack_min_rr2']):.2f} "
        f"max_same_symbol_positions={int(policy.demo_safety['max_same_symbol_positions'])} "
        f"min_stack_spacing_seconds={float(policy.demo_safety['min_stack_spacing_seconds']):.0f} "
        "broker_native_risk=1 live_unlock=0"
    )
    return calibration_runtime.main()


if __name__ == "__main__":
    raise SystemExit(main())
