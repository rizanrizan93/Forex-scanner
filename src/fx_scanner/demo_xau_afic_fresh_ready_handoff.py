from __future__ import annotations

from dataclasses import replace

from . import demo_fresh_ready_handoff as base
from .demo_execution_fresh_ready_handoff import install_exact_strategy_identity_filter

SYMBOL = "XAUUSD"
AFIC_EXECUTION_STRATEGY_ID = "XAU_AFIC_PATH_EXECUTION_V1"
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
    base.load_demo_project_config = load_afic_demo_project_config
    base.install_fresh_execution_ready_handoff = install_afic_execution_identity_filter
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
