from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any

CONTRACT = "XAU_TRADE_MANAGEMENT_CENTER_V195"


def _f(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def _side(value: Any) -> str:
    text = str(value or "").upper().strip()
    return text if text in {"BUY", "SELL"} else "UNKNOWN"


def _favorable_points(side: str, entry: float, current: float) -> float:
    return current - entry if side == "BUY" else entry - current


def _risk_points(side: str, entry: float, stop: float | None) -> float | None:
    if stop is None:
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    return risk if risk > 0 else None


def _target_progress(side: str, current: float, target: float | None) -> str:
    if target is None:
        return "NO_TARGET"
    if side == "BUY":
        return "REACHED" if current >= target else "PENDING"
    if side == "SELL":
        return "REACHED" if current <= target else "PENDING"
    return "UNKNOWN"


def evaluate_position(
    position: dict[str, Any],
    *,
    reaction_target: float | None = None,
    terminal_low: float | None = None,
    terminal_high: float | None = None,
    structure_direction: str | None = None,
) -> dict[str, Any]:
    side = _side(position.get("side"))
    entry = _f(position.get("open_price"))
    current = _f(position.get("current_price"))
    stop = _f(position.get("sl"))
    broker_tp = _f(position.get("tp"))
    volume = _f(position.get("volume"))
    profit = _f(position.get("profit"))
    swap = _f(position.get("swap"))

    base = {
        "contract": CONTRACT,
        "position_id": str(position.get("position_id") or ""),
        "symbol": str(position.get("symbol") or "").upper(),
        "side": side,
        "volume": volume,
        "entry": entry,
        "current": current,
        "stop": stop,
        "broker_tp": broker_tp,
        "profit": profit,
        "swap": swap,
        "opened_at": position.get("opened_at"),
        "execution_influence": False,
        "execution_authority": False,
    }
    if side == "UNKNOWN" or entry is None or current is None:
        return base | {
            "state": "INVALID_POSITION_SNAPSHOT",
            "protection_state": "UNKNOWN",
        }

    favorable = _favorable_points(side, entry, current)
    risk = _risk_points(side, entry, stop)
    current_r = None if risk is None else favorable / risk

    has_sl = stop is not None
    has_tp = broker_tp is not None
    if has_sl and has_tp:
        protection = "SL_TP_PRESENT"
    elif has_sl:
        protection = "SL_PRESENT_TP_MISSING"
    elif has_tp:
        protection = "SL_MISSING_TP_PRESENT"
    else:
        protection = "SL_TP_MISSING"

    structure_dir = str(structure_direction or "").upper().strip()
    structure_alignment = (
        "UNKNOWN"
        if structure_dir not in {"LONG", "SHORT"}
        else "ALIGNED"
        if (side == "BUY" and structure_dir == "LONG")
        or (side == "SELL" and structure_dir == "SHORT")
        else "OPPOSED"
    )

    first_target_state = _target_progress(side, current, reaction_target)

    terminal_reference = None
    if side == "BUY":
        terminal_reference = terminal_low if terminal_low is not None else terminal_high
    elif side == "SELL":
        terminal_reference = terminal_high if terminal_high is not None else terminal_low
    terminal_state = _target_progress(side, current, terminal_reference)

    if not has_sl:
        management_state = "PROTECTION_REQUIRED"
    elif first_target_state == "REACHED":
        management_state = "FIRST_TARGET_REACHED_REVIEW_PROTECTION"
    elif current_r is not None and current_r >= 1.0:
        management_state = "R_GE_1_REVIEW_PROTECTION"
    elif favorable > 0:
        management_state = "IN_PROFIT_HOLD_ORIGINAL_PLAN"
    elif favorable == 0:
        management_state = "AT_ENTRY"
    else:
        management_state = "UNDERWATER_HOLD_OR_INVALIDATE_BY_PLAN"

    be_reference = entry
    if first_target_state == "REACHED":
        be_state = "REVIEW_BE_OR_PARTIAL_AFTER_TARGET"
    elif current_r is not None and current_r >= 1.0:
        be_state = "REVIEW_BE_AFTER_1R"
    else:
        be_state = "NOT_YET_BY_GENERIC_MILESTONE"

    return base | {
        "state": "ACTIVE",
        "protection_state": protection,
        "favorable_points": favorable,
        "initial_risk_points": risk,
        "current_r": current_r,
        "be_reference_price": be_reference,
        "be_state": be_state,
        "first_reaction_target": reaction_target,
        "first_target_state": first_target_state,
        "terminal_reference": terminal_reference,
        "terminal_target_state": terminal_state,
        "structure_alignment": structure_alignment,
        "management_state": management_state,
        "note": (
            "BE reference is the entry price only; net break-even can differ due to "
            "spread, commission, swap, and execution costs. V195 is descriptive and "
            "does not modify broker positions."
        ),
    }


def summarize_positions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [dict(row) for row in rows if str(row.get("symbol") or "").upper() == "XAUUSD"]
    if not active:
        return {
            "contract": CONTRACT,
            "state": "NO_XAU_DEMO_POSITION",
            "count": 0,
            "total_volume": 0.0,
            "total_profit": 0.0,
            "weighted_entry": None,
            "net_side": "FLAT",
            "execution_influence": False,
            "execution_authority": False,
        }

    total_volume = sum(_f(row.get("volume")) or 0.0 for row in active)
    weighted_entry = (
        None
        if total_volume <= 0
        else sum(
            (_f(row.get("open_price")) or 0.0) * (_f(row.get("volume")) or 0.0)
            for row in active
        )
        / total_volume
    )
    total_profit = sum(_f(row.get("profit")) or 0.0 for row in active)
    sides = {_side(row.get("side")) for row in active}
    net_side = next(iter(sides)) if len(sides) == 1 else "MIXED"

    return {
        "contract": CONTRACT,
        "state": "ACTIVE_XAU_DEMO_POSITION",
        "count": len(active),
        "total_volume": total_volume,
        "total_profit": total_profit,
        "weighted_entry": weighted_entry,
        "net_side": net_side,
        "execution_influence": False,
        "execution_authority": False,
    }
