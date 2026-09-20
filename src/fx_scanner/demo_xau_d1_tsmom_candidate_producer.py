from __future__ import annotations

"""XAU-only DEMO execution producer for the frozen D1 TSMOM 60/EMA200 rule.

This module deliberately reuses the existing five-core implementation so the
DEMO broker path cannot drift from the already-tested D1 signal, ATR stop/target,
geometry, duplicate guard, and evidence persistence contracts.
"""

from . import demo_five_core_candidate_producer as base
from .demo_five_core_router import PAIR_STRATEGY_IDS

SYMBOL = "XAUUSD"
STRATEGY_ID = PAIR_STRATEGY_IDS[SYMBOL]


def run() -> int:
    # Restrict the existing pair-specific producer to XAU only. No strategy
    # threshold, entry, stop, target, risk or execution guard is relaxed here.
    base.FIVE_CORE_SYMBOLS = (SYMBOL,)
    base.NO_TRADE_SYMBOLS = frozenset()
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
