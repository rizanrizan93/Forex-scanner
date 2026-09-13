from __future__ import annotations

"""Canonical Five-Core DEMO runtime authority.

XAUUSD D1_TSMOM_60_200 was previously demoted after its preregistered rolling
stability gate failed. The frozen strategy subsequently passed an independent
cTrader cross-feed robustness study and the user explicitly authorized adding
it back to DEMO execution on 2026-09-13.

This module grants authority only to the exact frozen XAU TSMOM strategy path.
USDJPY remains shadow-only. LIVE execution is controlled elsewhere and remains
locked.
"""

AUTHORITY_CONTRACT = "FIVE_CORE_AUTHORITY_TSMOM_DEMO_REPROMOTION_V2"
PREVIOUS_DEMOTION_REASON = "PREREGISTERED_XAU_ROLLING_STABILITY_GATE_FAILED"
PROMOTION_REASON = "USER_AUTHORIZED_AFTER_INDEPENDENT_CTRADER_CROSSFEED"
DEMOTION_REASON = "SUPERSEDED_BY_EXPLICIT_DEMO_REPROMOTION"

# Exact Five-Core DEMO authority: XAUUSD only. The router binds XAUUSD to
# D1_TSMOM_60_200; no other Five-Core strategy receives broker-order authority.
EXECUTION_SYMBOLS = frozenset({"XAUUSD"})

# USDJPY remains research/shadow only.
SHADOW_SYMBOLS = frozenset({"USDJPY"})


def execution_authorized(symbol: str) -> bool:
    return str(symbol).upper().strip() in EXECUTION_SYMBOLS
