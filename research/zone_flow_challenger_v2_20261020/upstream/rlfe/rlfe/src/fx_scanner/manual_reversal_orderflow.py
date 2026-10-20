"""Read-only, fail-closed sidecar join for the manual reversal dashboard.

This deliberately consumes no bridge, broker/order, secret, or trading state.
The independent manual-reversal map remains authoritative for zone geometry
and Candidate-A WATCH/WAIT. A missing order-flow source is never substituted
with candle-derived features or a fabricated Bookmap feed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from .reversal_liquidity_fusion import evaluate_zone_orderflow

SIDECAR_CONTRACT = "RIZAN_REVERSAL_ORDERFLOW_SIDECAR_V1"


def zone_liquidity_state(
    zone: Mapping[str, Any],
    sidecar: Mapping[str, Any] | None,
    *,
    symbol: str = "XAUUSD",
    now: datetime | str | None = None,
    max_age_seconds: float = 90.0,
) -> dict[str, Any]:
    """Match a source observation by *exact* zone id; never enable trades.

    The 90-second allowance is for a manual display refreshing ~60 seconds,
    not a claim that 90-second data is adequate for market order execution.
    """
    now = now if now is not None else datetime.now(UTC)
    if (not isinstance(sidecar, Mapping)
            or sidecar.get("contract") != SIDECAR_CONTRACT
            or sidecar.get("symbol") != symbol
            or sidecar.get("execution_authority") is not False
            or sidecar.get("execution_influence") is not False
            or not isinstance(sidecar.get("observations"), list)):
        return evaluate_zone_orderflow(zone, None, symbol=symbol, now=now)
    zone_id = zone.get("zone_id")
    matches = [item for item in sidecar["observations"]
               if isinstance(item, Mapping) and item.get("zone_id") == zone_id]
    if len(matches) != 1:  # duplicate observations cannot be resolved by last-write wins
        return evaluate_zone_orderflow(zone, None, symbol=symbol, now=now)
    try:
        return evaluate_zone_orderflow(
            zone, matches[0], symbol=symbol, now=now,
            max_age_seconds=max_age_seconds,
        )
    except (ValueError, TypeError, OverflowError):
        # Corrupt, future-dated, wrong-market, or ill-formed data cannot block
        # the original manual map; show a visible absence instead.
        result = evaluate_zone_orderflow(zone, None, symbol=symbol, now=now)
        result["reason"] = "INVALID_ORDERFLOW_EVIDENCE"
        return result


def summarize_plan_liquidity(
    plan: Mapping[str, Any],
    sidecar: Mapping[str, Any] | None,
    *,
    symbol: str = "XAUUSD",
    now: datetime | str | None = None,
) -> dict[str, Any]:
    zone = plan["anchor"]
    return zone_liquidity_state(zone, sidecar, symbol=symbol, now=now)
