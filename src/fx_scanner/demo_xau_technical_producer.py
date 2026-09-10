from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from . import demo_technical_producer as base

_ORIGINAL_APPLY_DEMO_MARKET_SCHEDULE = base.apply_demo_market_schedule


def _apply_xau_only_market_schedule(cfg, *, now: datetime | None = None):
    """Validate the normal DEMO schedule first, then narrow discovery to XAUUSD.

    The weekday schedule contract deliberately validates the complete configured
    20-instrument universe. Narrowing to XAUUSD before that validation makes the
    specialized discovery wrapper fail closed with count=1 even when the base
    configuration is valid.
    """
    scheduled_cfg, mode = _ORIGINAL_APPLY_DEMO_MARKET_SCHEDULE(cfg, now=now)
    pair = next((item for item in scheduled_cfg.pairs if item.symbol == "XAUUSD"), None)
    if pair is None:
        raise SystemExit("XAUUSD_NOT_SCHEDULED")
    return replace(scheduled_cfg, pairs=(pair,)), f"{mode}_XAUUSD_ONLY"


def run() -> int:
    """Run discovery on XAUUSD only; IMPULSE_RETEST_V2 remains the sole strategy authority."""
    base.apply_demo_market_schedule = _apply_xau_only_market_schedule
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
