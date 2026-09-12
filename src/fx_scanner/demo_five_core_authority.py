from __future__ import annotations

"""Canonical Five-Core DEMO execution authority.

The DEMO account is intentionally an execution-data sandbox. Strategies that
have an implemented execution path may place DEMO orders so broker fills,
slippage, protection, exits, and calibration evidence can be collected. This
module does not grant LIVE authority; the existing broker policy still requires
cTrader DEMO and the live lock remains independent and fail-closed.
"""

AUTHORITY_CONTRACT = "FIVE_CORE_DEMO_EXECUTION_SANDBOX_V2"
POLICY_REASON = "DEMO_ACCOUNT_USED_FOR_EXECUTION_DATA_COLLECTION"

# Backward-compatible field for existing telemetry readers. The previous
# rolling-gate demotion is superseded for DEMO only; it remains research evidence
# and must not be interpreted as LIVE promotion evidence.
DEMOTION_REASON = "SUPERSEDED_BY_DEMO_EXECUTION_SANDBOX_POLICY"

# Both currently implemented Five-Core strategies may execute in DEMO when
# their own setup, freshness, geometry, guard, risk, and broker checks pass.
EXECUTION_SYMBOLS = frozenset({"XAUUSD", "USDJPY"})
SHADOW_SYMBOLS = frozenset()


def execution_authorized(symbol: str) -> bool:
    return str(symbol).upper().strip() in EXECUTION_SYMBOLS
