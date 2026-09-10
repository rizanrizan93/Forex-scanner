from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from . import demo_technical_producer as base
from .demo_impulse_retest_v2 import EXECUTION_SYMBOLS

_ORIGINAL_APPLY_DEMO_MARKET_SCHEDULE = base.apply_demo_market_schedule


def _apply_execution_market_schedule(cfg, *, now: datetime | None = None):
    """Validate the canonical DEMO schedule, then narrow to execution-authorized pairs."""
    scheduled_cfg, mode = _ORIGINAL_APPLY_DEMO_MARKET_SCHEDULE(cfg, now=now)
    pairs = tuple(item for item in scheduled_cfg.pairs if item.symbol in EXECUTION_SYMBOLS)
    symbols = {item.symbol for item in pairs}
    missing = set(EXECUTION_SYMBOLS) - symbols
    if missing:
        raise SystemExit(f"DEMO_EXECUTION_SYMBOL_NOT_SCHEDULED:{','.join(sorted(missing))}")
    return replace(scheduled_cfg, pairs=pairs), f"{mode}_PAIR_SPECIFIC_EXECUTION"


def run() -> int:
    """Run discovery for the pair-specific DEMO execution registry only."""
    base.apply_demo_market_schedule = _apply_execution_market_schedule
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
