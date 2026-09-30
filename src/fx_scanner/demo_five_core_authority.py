from __future__ import annotations

"""Canonical cTrader DEMO execution authority.

V298 freezes the operational scanner to XAUUSD only. Historical strategy code
and evidence for other pairs remain available in the repository, but no
non-XAU symbol is authorized for the active DEMO execution lane. LIVE remains
locked elsewhere.
"""

AUTHORITY_CONTRACT = "XAUUSD_ONLY_DEMO_AUTHORITY_V298"
PREVIOUS_DEMOTION_REASON = "PAIR_SPECIFIC_DEMO_AUTHORITY_V4_EURAUD_GBPAUD"
PROMOTION_REASON = "USER_REQUESTED_XAUUSD_ONLY_OPERATIONAL_FOCUS"
DEMOTION_REASON = "NON_XAU_RUNTIME_PAUSED_V298"

# Fail closed: the only broker-authorized symbol is XAUUSD.
EXECUTION_SYMBOLS = frozenset({"XAUUSD"})

SHADOW_SYMBOLS = frozenset()


def execution_authorized(symbol: str) -> bool:
    return str(symbol).upper().strip() in EXECUTION_SYMBOLS
