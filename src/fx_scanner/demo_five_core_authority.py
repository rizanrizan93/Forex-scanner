from __future__ import annotations

"""Canonical Five-Core runtime authority after the preregistered stability gate.

Strategy evaluators remain intact so research and forward evidence can continue.
This module controls whether a validated strategy may influence DEMO order
production. It deliberately grants no Five-Core strategy execution authority
until a future, separately preregistered re-promotion gate passes.
"""

AUTHORITY_CONTRACT = "FIVE_CORE_AUTHORITY_AFTER_XAU_ROLLING_GATE_V1"
DEMOTION_REASON = "PREREGISTERED_XAU_ROLLING_STABILITY_GATE_FAILED"

# No Five-Core strategy currently has DEMO order authority.
EXECUTION_SYMBOLS = frozenset()

# XAU keeps its frozen D1 evaluator and forward evidence, but cannot emit an
# execution-ready signal. USDJPY was already shadow-only.
SHADOW_SYMBOLS = frozenset({"XAUUSD", "USDJPY"})


def execution_authorized(symbol: str) -> bool:
    return str(symbol).upper().strip() in EXECUTION_SYMBOLS
