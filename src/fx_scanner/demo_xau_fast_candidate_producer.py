from __future__ import annotations

import os

from . import demo_fast_candidate_producer as base
from .demo_impulse_retest_execution import scan_demo_deep_candidates_report


def _xau_only_recent_candidate_symbols(store, cfg, *, now, lookback_minutes, max_symbols):
    """Force the DEMO fast lane to revalidate XAUUSD whenever durable discovery ranked it."""
    return ("XAUUSD",) if "XAUUSD" in cfg.pair_map else ()


def run() -> int:
    """Run the fast DEMO lane with XAUUSD-only IMPULSE_RETEST_V2 authority."""
    os.environ["CTRADER_DEMO_FAST_MAX_SYMBOLS"] = "1"
    base.scan_demo_deep_candidates_report = scan_demo_deep_candidates_report
    base.recent_candidate_symbols = _xau_only_recent_candidate_symbols
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
