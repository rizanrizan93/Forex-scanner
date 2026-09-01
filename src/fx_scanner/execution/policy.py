from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..exceptions import ConfigurationError
from .models import ExecutionMode


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    mode: ExecutionMode
    scheduler: dict[str, float]
    order: dict[str, Any]
    live_safety: dict[str, Any]
    runtime: dict[str, Any] = field(default_factory=dict)
    broker: dict[str, Any] = field(default_factory=dict)
    ctrader: dict[str, Any] = field(default_factory=dict)
    mt5: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    adaptive_cadence: dict[str, float] = field(default_factory=dict)


def load_execution_policy(root: str | Path | None = None) -> ExecutionPolicy:
    root_path = Path(root) if root else Path(__file__).resolve().parents[3]
    path = root_path / "config" / "execution.yaml"
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    try:
        mode = ExecutionMode(str(raw["mode"]).upper())
    except Exception as exc:
        raise ConfigurationError("invalid execution mode") from exc

    scheduler = {k: float(v) for k, v in raw.get("scheduler", {}).items()}
    required = {
        "heavy_scan_seconds",
        "fast_setup_seconds",
        "execution_watch_seconds",
        "position_monitor_seconds",
    }
    if set(scheduler) != required or any(v <= 0 for v in scheduler.values()):
        raise ConfigurationError("execution scheduler is incomplete or invalid")
    if scheduler["heavy_scan_seconds"] < scheduler["fast_setup_seconds"]:
        raise ConfigurationError("heavy scan should not be faster than setup watcher")
    if scheduler["fast_setup_seconds"] < scheduler["execution_watch_seconds"]:
        raise ConfigurationError("setup watcher should not be faster than execution watcher")
    if scheduler["fast_setup_seconds"] > 15:
        raise ConfigurationError("fast setup watcher cannot exceed 15 seconds in v0.9")
    if scheduler["execution_watch_seconds"] > 0.25:
        raise ConfigurationError("execution watcher cannot exceed 250ms in v0.9")

    order = dict(raw.get("order", {}))
    live_safety = dict(raw.get("live_safety", {}))
    runtime = dict(raw.get("runtime", {}))
    broker = dict(raw.get("broker", {}))
    ctrader = dict(raw.get("ctrader", {}))
    mt5 = dict(raw.get("mt5", {}))
    reconciliation = dict(raw.get("reconciliation", {}))
    adaptive_cadence = {str(k).upper(): float(v) for k, v in raw.get("adaptive_cadence", {}).items()}

    for key in ("live_enable_env", "live_enable_value", "account_allowlist_env", "kill_switch_env"):
        if not live_safety.get(key):
            raise ConfigurationError(f"missing live safety config: {key}")
    if not order.get("require_broker_preflight", False):
        raise ConfigurationError("broker preflight cannot be disabled")
    if not order.get("require_server_side_sl", False):
        raise ConfigurationError("server-side SL is mandatory")
    if not order.get("require_server_side_tp", False):
        raise ConfigurationError("server-side TP is mandatory")
    if float(order.get("max_preflight_entry_drift_r", 0)) <= 0:
        raise ConfigurationError("max_preflight_entry_drift_r must be positive")
    if live_safety.get("require_control_plane", False):
        if float(live_safety.get("control_state_max_age_seconds", 0)) <= 0:
            raise ConfigurationError("control_state_max_age_seconds must be positive")
    if live_safety.get("require_persistent_idempotency", False):
        if not str(live_safety.get("idempotency_state_path_env", "")).strip():
            raise ConfigurationError("idempotency_state_path_env is required")

    lag = dict(runtime.get("max_lag_seconds", {}))
    required_lag = {"heavy_scan", "fast_setup", "execution_watch", "position_monitor"}
    if set(lag) != required_lag or any(float(v) < 0 for v in lag.values()):
        raise ConfigurationError("runtime max_lag_seconds is incomplete or invalid")
    if float(runtime.get("supervisor_tick_seconds", 0)) <= 0:
        raise ConfigurationError("supervisor_tick_seconds must be positive")
    if int(runtime.get("execution_queue_maxsize", 0)) <= 0:
        raise ConfigurationError("execution_queue_maxsize must be positive")
    if int(runtime.get("concurrent_workers", 0)) < 4:
        raise ConfigurationError("concurrent_workers must be >= 4 for four cadence tiers")
    if float(runtime.get("execution_worker_poll_seconds", 0)) <= 0:
        raise ConfigurationError("execution_worker_poll_seconds must be positive")

    reconnect = dict(runtime.get("reconnect", {}))
    if int(reconnect.get("max_attempts", 0)) <= 0:
        raise ConfigurationError("reconnect max_attempts must be positive")
    if float(reconnect.get("backoff_initial_seconds", 0)) <= 0:
        raise ConfigurationError("backoff_initial_seconds must be positive")
    if float(reconnect.get("backoff_multiplier", 0)) < 1:
        raise ConfigurationError("backoff_multiplier must be >= 1")
    if float(reconnect.get("backoff_max_seconds", 0)) < float(reconnect.get("backoff_initial_seconds", 0)):
        raise ConfigurationError("backoff max must be >= initial")

    breaker = dict(runtime.get("circuit_breaker", {}))
    if int(breaker.get("failure_threshold", 0)) <= 0 or float(breaker.get("recovery_seconds", 0)) <= 0:
        raise ConfigurationError("circuit breaker configuration is invalid")

    research_backend = str(broker.get("research", broker.get("preferred", "CTRADER"))).upper()
    execution_backend = str(broker.get("execution", "MT5")).upper()
    if research_backend not in {"CTRADER", "MT5"} or execution_backend not in {"CTRADER", "MT5"}:
        raise ConfigurationError("invalid broker backend configuration")
    if bool(broker.get("automatic_fallback", False)):
        raise ConfigurationError("automatic cross-broker fallback is forbidden")
    if bool(broker.get("dual_feed_single_execution", False)):
        if research_backend != "CTRADER" or execution_backend != "MT5":
            raise ConfigurationError("dual-feed v0.5 requires CTRADER research and MT5 execution")
        if not live_safety.get("require_revalidation", False):
            raise ConfigurationError("dual-feed live execution requires revalidation")

    if research_backend == "CTRADER":
        if str(ctrader.get("environment", "DEMO")).upper() not in {"DEMO", "LIVE"}:
            raise ConfigurationError("cTrader environment must be DEMO or LIVE")
        for key in (
            "client_id_env", "client_secret_env", "access_token_env",
            "refresh_token_env", "token_state_path_env", "account_id_env",
            "trader_login_env",
        ):
            if not ctrader.get(key):
                raise ConfigurationError(f"missing cTrader config: {key}")
        if not bool(ctrader.get("require_demo", False)):
            raise ConfigurationError("cTrader demo-only account lock cannot be disabled")
        if str(ctrader.get("environment", "DEMO")).upper() != "DEMO":
            raise ConfigurationError("cTrader phone-only runtime is locked to DEMO")
        if float(ctrader.get("request_timeout_seconds", 0)) <= 0:
            raise ConfigurationError("cTrader request timeout must be positive")
        if float(ctrader.get("max_quote_age_seconds", 0)) <= 0:
            raise ConfigurationError("cTrader quote age must be positive")

    if execution_backend == "MT5":
        for key in ("terminal_path_env", "login_env", "server_env", "password_env"):
            if not mt5.get(key):
                raise ConfigurationError(f"missing MT5 config: {key}")
        if float(mt5.get("initialize_timeout_ms", 0)) <= 0:
            raise ConfigurationError("MT5 initialize timeout must be positive")
        if float(mt5.get("max_quote_age_seconds", 0)) <= 0:
            raise ConfigurationError("MT5 quote age must be positive")
        suffixes = mt5.get("symbol_suffix_candidates", [])
        if not isinstance(suffixes, list) or not suffixes:
            raise ConfigurationError("MT5 symbol suffix candidates are required")

    if bool(broker.get("dual_feed_single_execution", False)):
        positive = (
            "research_quote_max_age_seconds",
            "execution_quote_max_age_seconds",
            "max_mid_divergence_pips",
            "max_execution_spread_pips",
            "max_spread_ratio_vs_research",
            "max_entry_drift_pips",
            "max_entry_drift_r",
            "min_rr",
            "max_internal_revalidation_ms",
            "expected_fx_contract_size",
        )
        for key in positive:
            if float(reconciliation.get(key, 0)) <= 0:
                raise ConfigurationError(f"invalid reconciliation config: {key}")
        if float(reconciliation["min_rr"]) < 1.5:
            raise ConfigurationError("dual-feed minimum RR cannot be below 1.5")
        if str(reconciliation.get("expected_account_currency", "")).upper() != "USC":
            raise ConfigurationError("HFM Cent execution account currency must be USC")
        if abs(float(reconciliation["expected_fx_contract_size"]) - 1000.0) > 1e-9:
            raise ConfigurationError("HFM Cent FX contract size must be 1000 units")

    required_states = {
        "NO_TRADE", "WATCH", "SETUP_FORMING", "ARMED",
        "EXECUTION_READY", "MISSED", "INVALIDATED", "COOLDOWN",
    }
    if set(adaptive_cadence) != required_states or any(v <= 0 for v in adaptive_cadence.values()):
        raise ConfigurationError("adaptive cadence is incomplete or invalid")
    if not (
        adaptive_cadence["EXECUTION_READY"]
        <= adaptive_cadence["ARMED"]
        <= adaptive_cadence["SETUP_FORMING"]
        <= adaptive_cadence["WATCH"]
    ):
        raise ConfigurationError("adaptive cadence must accelerate toward execution")
    if adaptive_cadence["WATCH"] > 1.0:
        raise ConfigurationError("WATCH cadence cannot exceed 1 second in v0.9")
    if adaptive_cadence["SETUP_FORMING"] > 0.5:
        raise ConfigurationError("SETUP_FORMING cadence cannot exceed 500ms in v0.9")
    if adaptive_cadence["ARMED"] > 0.25 or adaptive_cadence["EXECUTION_READY"] > 0.25:
        raise ConfigurationError("ARMED/EXECUTION_READY cadence cannot exceed 250ms in v0.9")

    return ExecutionPolicy(
        mode, scheduler, order, live_safety, runtime, broker, ctrader, mt5,
        reconciliation, adaptive_cadence
    )
