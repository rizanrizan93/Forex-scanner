"""Read-only, fail-closed sidecar join for the manual reversal dashboard.

Never imports the trading bridge, order execution, account state or secrets.
Candidate-A WATCH/WAIT and structural zone geometry remain unchanged.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from .reversal_liquidity_fusion import evaluate_zone_orderflow

SIDECAR_CONTRACT = "RIZAN_REVERSAL_ORDERFLOW_SIDECAR_V1"


def zone_liquidity_state(
    zone: Mapping[str, Any],
    sidecar: Mapping[str, Any] | None,
    *, symbol: str = "XAUUSD", now: datetime | str | None = None,
    max_age_seconds: float = 90.0,
) -> dict[str, Any]:
    """Join one matching observation by zone id.

    90-second age is for the one-minute manual *display*, never live execution.
    """
    now = now if now is not None else datetime.now(UTC)
    if (not isinstance(sidecar, Mapping)
            or sidecar.get("contract") != SIDECAR_CONTRACT
            or sidecar.get("symbol") != symbol
            or sidecar.get("execution_authority") is not False
            or sidecar.get("execution_influence") is not False
            or not isinstance(sidecar.get("observations"), list)):
        return evaluate_zone_orderflow(zone, None, symbol=symbol, now=now)
    matches = [item for item in sidecar["observations"]
               if isinstance(item, Mapping) and item.get("zone_id") == zone.get("zone_id")]
    if len(matches) != 1:
        return evaluate_zone_orderflow(zone, None, symbol=symbol, now=now)
    try:
        return evaluate_zone_orderflow(
            zone, matches[0], symbol=symbol, now=now,
            max_age_seconds=max_age_seconds,
        )
    except (ValueError, TypeError, OverflowError):
        result = evaluate_zone_orderflow(zone, None, symbol=symbol, now=now)
        result["reason"] = "INVALID_ORDERFLOW_EVIDENCE"
        return result


def summarize_plan_liquidity(
    plan: Mapping[str, Any], sidecar: Mapping[str, Any] | None,
    *, symbol: str = "XAUUSD", now: datetime | str | None = None,
) -> dict[str, Any]:
    return zone_liquidity_state(plan["anchor"], sidecar, symbol=symbol, now=now)
