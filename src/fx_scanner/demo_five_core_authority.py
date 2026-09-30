from __future__ import annotations

"""Canonical pair-specific cTrader DEMO runtime authority.

This authority is DEMO-only. Existing XAUUSD, USDJPY and GBPUSD strategies
remain authorized. On 2026-09-14 the user explicitly authorized the frozen
EURAUD and GBPAUD research survivors for actual DEMO broker execution so
forward fills and lifecycle outcomes can be collected.

EURUSD and AUDUSD remain non-execution research/component lanes. LIVE
execution is controlled elsewhere and remains locked.
"""

AUTHORITY_CONTRACT = "PAIR_SPECIFIC_DEMO_AUTHORITY_V4_EURAUD_GBPAUD"
PREVIOUS_DEMOTION_REASON = "PREREGISTERED_XAU_ROLLING_STABILITY_GATE_FAILED"
PROMOTION_REASON = "USER_AUTHORIZED_DEMO_TRADING_DATA_COLLECTION"
DEMOTION_REASON = "SUPERSEDED_BY_PAIR_SPECIFIC_DEMO_AUTHORITY_V4"

# Exact pair-specific DEMO authority. Unknown or legacy strategy identities are
# still rejected by the downstream exact strategy-identity handoff.
EXECUTION_SYMBOLS = frozenset(
    {"XAUUSD", "USDJPY", "GBPUSD", "EURAUD", "GBPAUD"}
)

SHADOW_SYMBOLS = frozenset()


def execution_authorized(symbol: str) -> bool:
    return str(symbol).upper().strip() in EXECUTION_SYMBOLS
