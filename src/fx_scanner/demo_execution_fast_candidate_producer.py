from __future__ import annotations

import os

from . import demo_fast_candidate_producer as base
from .demo_impulse_retest_execution import scan_demo_deep_candidates_report
from .demo_impulse_retest_v2 import EXECUTION_SYMBOLS


def _execution_recent_candidate_symbols(store, cfg, *, now, lookback_minutes, max_symbols):
    """Revalidate every execution-authorized symbol each fast cycle."""
    return tuple(symbol for symbol in sorted(EXECUTION_SYMBOLS) if symbol in cfg.pair_map)


def run() -> int:
    """Run fast DEMO revalidation for XAUUSD and EURUSD pair-specific execution."""
    os.environ["CTRADER_DEMO_FAST_MAX_SYMBOLS"] = str(len(EXECUTION_SYMBOLS))
    base.scan_demo_deep_candidates_report = scan_demo_deep_candidates_report
    base.recent_candidate_symbols = _execution_recent_candidate_symbols
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
