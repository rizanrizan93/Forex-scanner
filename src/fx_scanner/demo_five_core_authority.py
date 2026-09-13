from __future__ import annotations

"""Canonical Five-Core DEMO runtime authority.

This authority is DEMO-only. XAUUSD D1_TSMOM_60_200 remains authorized after
its independent cTrader cross-feed study. On 2026-09-13 the user additionally
authorized the frozen public-history leads USDJPY D1_DONCHIAN55_200 and
GBPUSD H4_MEAN_REVERT_Z2_TO_SMA20 for DEMO forward collection.

EURUSD and AUDUSD remain non-execution research lanes. LIVE execution is
controlled elsewhere and remains locked.
"""

AUTHORITY_CONTRACT = "FIVE_CORE_AUTHORITY_PAIR_SPECIFIC_DEMO_V3"
PREVIOUS_DEMOTION_REASON = "PREREGISTERED_XAU_ROLLING_STABILITY_GATE_FAILED"
PROMOTION_REASON = "USER_AUTHORIZED_DEMO_AFTER_PUBLIC_HISTORY_ROBUSTNESS_SEARCH"
DEMOTION_REASON = "SUPERSEDED_BY_PAIR_SPECIFIC_DEMO_AUTHORITY_V3"

# Exact pair-specific DEMO authority. The router binds each symbol to one frozen
# strategy identity; unknown or legacy strategies remain fail-closed.
EXECUTION_SYMBOLS = frozenset({"XAUUSD", "USDJPY", "GBPUSD"})

# No Five-Core pair is shadow-only after this explicit DEMO promotion. AUDUSD
# remains research WATCH but not execution-authorized and is classified NO_TRADE
# by the router until its regime edge is independently confirmed.
SHADOW_SYMBOLS = frozenset()


def execution_authorized(symbol: str) -> bool:
    return str(symbol).upper().strip() in EXECUTION_SYMBOLS
