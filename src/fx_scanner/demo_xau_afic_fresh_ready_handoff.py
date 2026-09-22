from __future__ import annotations

import os
from dataclasses import replace
from time import monotonic

from .storage.supabase_operational import SupabaseOperationalStore

from . import demo_fresh_ready_handoff as base
from .demo_execution_fresh_ready_handoff import install_exact_strategy_identity_filter

SYMBOL = "XAUUSD"
AFIC_EXECUTION_STRATEGY_ID = "XAU_AFIC_PATH_EXECUTION_V1"
WORKER_NAME = "ctrader_demo_xau_afic_fast_handoff"
_ALLOWED_AFIC_STRATEGIES_BY_SYMBOL = {
    SYMBOL: frozenset({AFIC_EXECUTION_STRATEGY_ID}),
}

_ORIGINAL_LOAD_DEMO_PROJECT_CONFIG = base.load_demo_project_config


def load_afic_demo_project_config(root=None):
    """Restrict the shared DEMO executor to XAUUSD for the AFIC fast lane."""
    cfg = _ORIGINAL_LOAD_DEMO_PROJECT_CONFIG(root)
    if SYMBOL not in cfg.pair_map:
        raise RuntimeError("AFIC_FAST_HANDOFF_XAUUSD_CONFIG_MISSING")
    return replace(cfg, pairs=(cfg.pair_map[SYMBOL],))


def install_afic_execution_identity_filter(*, max_age_seconds: float) -> None:
    """Allow only fresh AFIC execution geometry through this fast lane."""
    install_exact_strategy_identity_filter(
        allowed_strategies_by_symbol=_ALLOWED_AFIC_STRATEGIES_BY_SYMBOL,
        max_age_seconds=max_age_seconds,
    )


def main() -> int:
    """Execute only fresh AFIC Grade-A confirmed signals on cTrader DEMO."""
    started = monotonic()
    exit_code = 2
    error = None
    try:
        base.load_demo_project_config = load_afic_demo_project_config
        base.install_fresh_execution_ready_handoff = install_afic_execution_identity_filter
        exit_code = int(base.main())
        return exit_code
    except BaseException as exc:
        error = f"{type(exc).__name__}:{exc}"
        raise
    finally:
        try:
            store = SupabaseOperationalStore.from_env()
            store.write_heartbeat(
                WORKER_NAME,
                healthy=error is None and exit_code == 0,
                lag_seconds=0.0,
                details={
                    "strategy_id": AFIC_EXECUTION_STRATEGY_ID,
                    "symbol": SYMBOL,
                    "environment": "DEMO",
                    "execution_mode": "AUTO",
                    "exact_identity_only": True,
                    "shared_demo_safety_stack": True,
                    "live_execution_enabled": False,
                    "exit_code": exit_code,
                    "duration_seconds": round(monotonic() - started, 3),
                    "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
                    "error": error,
                },
            )
        except Exception:
            # Execution result remains authoritative; observability cannot
            # convert a safe broker result into a retry or duplicate order.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
