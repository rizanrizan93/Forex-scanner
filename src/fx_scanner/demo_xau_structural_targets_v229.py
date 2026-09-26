from __future__ import annotations

from math import isfinite
from typing import Any, Sequence

CONTRACT = "XAU_STRUCTURAL_TARGET_LADDER_V229_1"
TIMEFRAME_ORDER = ("M15", "H1", "H4", "D1")
FRONT_RUN_ZONE_FRACTION = 0.10
FRONT_RUN_MAX_USD = 1.0


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _active(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    if lifecycle and lifecycle.get("active") is False:
        return False
    status = str(zone.get("status") or "").upper()
    return "BROKEN" not in status and "INVALID" not in status


def _front_run_price(zone: dict[str, Any], direction: str) -> tuple[float, float] | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None or high <= low:
        return None
    buffer = min(FRONT_RUN_MAX_USD, (high - low) * FRONT_RUN_ZONE_FRACTION)
    if direction == "LONG":
        return low - buffer, buffer
    if direction == "SHORT":
        return high + buffer, buffer
    return None


def _ahead(zone: dict[str, Any], *, direction: str, entry: float) -> bool:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return False
    if direction == "LONG":
        return low > entry
    if direction == "SHORT":
        return high < entry
    return False


def _opposing(zone: dict[str, Any], direction: str) -> bool:
    wanted = "SHORT" if direction == "LONG" else "LONG"
    return str(zone.get("direction") or "").upper() == wanted


def _distance(zone: dict[str, Any], *, direction: str, entry: float) -> float:
    low = float(zone["low"])
    high = float(zone["high"])
    return low - entry if direction == "LONG" else entry - high


def _nearest_per_timeframe(
    zones: Sequence[dict[str, Any]],
    *,
    direction: str,
    entry: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for timeframe in TIMEFRAME_ORDER:
        candidates = [
            dict(zone)
            for zone in zones
            if str(zone.get("timeframe") or "").upper() == timeframe
            and _active(zone)
            and _opposing(zone, direction)
            and _ahead(zone, direction=direction, entry=entry)
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda zone: (
                _distance(zone, direction=direction, entry=entry),
                -float(_f(zone.get("research_score")) or 0.0),
            )
        )
        output.append(candidates[0])
    return output


def build_structural_target_plan(
    *,
    direction: str,
    entry: float,
    stop: float,
    m15_zones: Sequence[dict[str, Any]] = (),
    htf_zones: Sequence[dict[str, Any]] = (),
    minimum_rr: float = 1.5,
) -> dict[str, Any]:
    """Map scale-out targets to opposing M15 -> H1 -> H4 structure.

    D1 is retained as an optional macro terminal. A zone is mapped even when it
    is too close for execution; RR is a validation gate, not the target source.
    """
    side = str(direction or "").upper()
    if side not in {"LONG", "SHORT"}:
        return {}
    entry_f = _f(entry)
    stop_f = _f(stop)
    min_rr = _f(minimum_rr)
    if entry_f is None or stop_f is None or min_rr is None or min_rr <= 0:
        return {}
    risk = entry_f - stop_f if side == "LONG" else stop_f - entry_f
    if risk <= 0:
        return {}

    zones = [dict(zone) for zone in list(m15_zones) + list(htf_zones)]
    selected = _nearest_per_timeframe(zones, direction=side, entry=entry_f)
    mapped: list[dict[str, Any]] = []
    for zone in selected:
        front = _front_run_price(zone, side)
        if front is None:
            continue
        target, buffer = front
        reward = target - entry_f if side == "LONG" else entry_f - target
        if reward <= 0:
            continue
        rr = reward / risk
        timeframe = str(zone.get("timeframe") or "").upper()
        mapped.append(
            {
                "timeframe": timeframe,
                "zone_id": zone.get("zone_id"),
                "zone_low": float(zone["low"]),
                "zone_high": float(zone["high"]),
                "proximal_edge": float(zone["low"] if side == "LONG" else zone["high"]),
                "front_run_buffer": float(buffer),
                "target_price": float(target),
                "rr": float(rr),
                "minimum_rr": float(min_rr),
                "rr_eligible": bool(rr + 1e-12 >= min_rr),
                "role": "MACRO_TERMINAL" if timeframe == "D1" else f"{timeframe}_SCALE_OUT",
                "source": "OPPOSING_SUPPLY_DEMAND",
            }
        )

    broker = [
        item
        for item in mapped
        if bool(item["rr_eligible"]) and str(item["timeframe"]) in {"M15", "H1", "H4"}
    ]
    macro = next(
        (
            item
            for item in mapped
            if str(item["timeframe"]) == "D1" and bool(item["rr_eligible"])
        ),
        None,
    )
    return {
        "contract": CONTRACT,
        "direction": side,
        "entry": float(entry_f),
        "stop": float(stop_f),
        "risk_points": float(risk),
        "minimum_rr": float(min_rr),
        "front_run_rule": {
            "zone_fraction": FRONT_RUN_ZONE_FRACTION,
            "max_usd": FRONT_RUN_MAX_USD,
        },
        "mapped_targets": mapped,
        "broker_scaleout_targets": broker,
        "macro_terminal_target": macro,
        "structural_target_available": bool(broker),
        "target_timeframe_order": list(TIMEFRAME_ORDER),
        "execution_influence": False,
        "execution_authority": False,
        "note": (
            "Opposing supply/demand determines target location. RR only validates whether "
            "a mapped target is far enough to become a broker scale-out. D1 remains an "
            "optional macro terminal rather than a mandatory take-profit."
        ),
    }
