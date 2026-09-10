from __future__ import annotations

from dataclasses import replace

from . import demo_technical_producer as base

_ORIGINAL_APPLY_DEMO_MARKET_SCHEDULE = base.apply_demo_market_schedule


def _apply_xau_only_market_schedule(cfg, *, now=None):
    """Validate the canonical calendar first, then narrow the scheduled universe.

    Weekdays retain the frozen 20-instrument validation contract and are reduced
    to XAUUSD only after validation. On weekends XAUUSD is not in the canonical
    scheduled universe, so this wrapper exits cleanly without re-enabling crypto
    execution for the XAU-only strategy.
    """
    scheduled, mode = _ORIGINAL_APPLY_DEMO_MARKET_SCHEDULE(cfg, now=now)
    pair = next((item for item in scheduled.pairs if item.symbol == "XAUUSD"), None)
    if pair is None:
        raise SystemExit(f"XAUUSD_MARKET_SCHEDULE_CLOSED:{mode}")
    return replace(scheduled, pairs=(pair,)), f"{mode}_XAUUSD_ONLY"


def run() -> int:
    """Run XAUUSD-only discovery after canonical market-calendar validation."""
    base.apply_demo_market_schedule = _apply_xau_only_market_schedule
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
