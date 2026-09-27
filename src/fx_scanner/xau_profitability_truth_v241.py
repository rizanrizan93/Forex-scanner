from __future__ import annotations

from math import sqrt
from typing import Any, Sequence


V184_STRATEGY = "XAU_SUPPLY_DEMAND_PROSPECTIVE_V184"
V184_REACTION_EPISODE = "SUPPLY_DEMAND_V184_REACTION"
V184_RESOLVED = {"HOLD", "BREAK", "BREAK_TOUCH_BAR", "STALL"}
V184_PRIMARY_MIN_N = 50
V184_PRIMARY_MIN_PRECISION = 0.80
V184_PRIMARY_MIN_WILSON = 0.70


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def wilson_lower_bound(successes: int, total: int, *, z: float = 1.959963984540054) -> float | None:
    n = int(total)
    k = int(successes)
    if n <= 0 or k < 0 or k > n:
        return None
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return (centre - margin) / denom


def _latest_xau_performance(
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    xau = [
        dict(row)
        for row in rows
        if str(dict(row).get("symbol") or "").upper().strip() == "XAUUSD"
    ]
    if not xau:
        return {
            "available": False,
            "status": "NO_PERSISTED_XAU_OOS_PERFORMANCE",
            "trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "expectancy_r": None,
            "max_drawdown_r": None,
            "sample_scope": None,
            "setup_type": None,
            "as_of": None,
        }
    xau.sort(key=lambda row: str(row.get("as_of") or ""), reverse=True)
    row = xau[0]
    return {
        "available": True,
        "status": "PERSISTED_XAU_PERFORMANCE_AVAILABLE",
        "trades": int(row.get("trades") or 0),
        "win_rate": _f(row.get("win_rate")),
        "profit_factor": _f(row.get("profit_factor")),
        "expectancy_r": _f(row.get("expectancy_r")),
        "max_drawdown_r": _f(row.get("max_drawdown_r")),
        "sample_scope": row.get("sample_scope"),
        "setup_type": row.get("setup_type"),
        "as_of": row.get("as_of"),
    }


def _supply_demand_reaction(
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    resolved = [
        dict(row)
        for row in rows
        if str(dict(row).get("strategy_id") or "") == V184_STRATEGY
        and str(dict(row).get("episode_type") or "") == V184_REACTION_EPISODE
        and str(dict(row).get("status") or "").upper() in V184_RESOLVED
    ]
    holds = sum(str(row.get("status") or "").upper() == "HOLD" for row in resolved)
    primary = [
        row
        for row in resolved
        if bool(dict(row.get("metadata") or {}).get("primary_candidate_match"))
    ]
    primary_holds = sum(
        str(row.get("status") or "").upper() == "HOLD" for row in primary
    )
    n = len(resolved)
    primary_n = len(primary)
    precision = None if n == 0 else holds / n
    primary_precision = None if primary_n == 0 else primary_holds / primary_n
    primary_wilson = wilson_lower_bound(primary_holds, primary_n)
    replication_gate_met = bool(
        primary_n >= V184_PRIMARY_MIN_N
        and primary_precision is not None
        and primary_precision >= V184_PRIMARY_MIN_PRECISION
        and primary_wilson is not None
        and primary_wilson >= V184_PRIMARY_MIN_WILSON
    )
    return {
        "resolved": n,
        "holds": holds,
        "precision_hold": precision,
        "primary_n": primary_n,
        "primary_holds": primary_holds,
        "primary_precision": primary_precision,
        "primary_wilson_lower_95": primary_wilson,
        "replication_gate_met": replication_gate_met,
        "minimum_n": V184_PRIMARY_MIN_N,
        "minimum_precision": V184_PRIMARY_MIN_PRECISION,
        "minimum_wilson_lower_95": V184_PRIMARY_MIN_WILSON,
        "interpretation": "REACTION_EVIDENCE_NOT_TRADING_WIN_RATE",
    }


def _authorized_execution_sample(
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    authorized = [
        dict(row)
        for row in rows
        if str(dict(row).get("execution_authority") or "").upper().strip()
        not in {"", "NONE", "SHADOW"}
    ]
    terminal = [
        row
        for row in authorized
        if row.get("outcome_at")
        or str(row.get("status") or "").upper()
        in {"CLOSED", "STOPPED", "TP1_HIT", "TP2_HIT", "LOSS", "WIN"}
    ]
    tp1 = sum(bool(row.get("tp1_hit")) for row in terminal)
    tp2 = sum(bool(row.get("tp2_hit")) for row in terminal)
    stops = sum(bool(row.get("stop_hit")) for row in terminal)
    return {
        "authorized_rows": len(authorized),
        "terminal_rows": len(terminal),
        "tp1_hits": tp1,
        "tp2_hits": tp2,
        "stop_hits": stops,
        "status": (
            "FORWARD_SAMPLE_AVAILABLE"
            if terminal
            else "NO_COMPLETED_BROKER_AUTHORIZED_SAMPLE"
        ),
    }


def build_xau_profitability_truth(
    *,
    outcomes: Sequence[dict[str, Any]],
    performance: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Separate reaction quality from actual trading-performance evidence."""
    perf = _latest_xau_performance(performance)
    reaction = _supply_demand_reaction(outcomes)
    execution = _authorized_execution_sample(outcomes)
    if perf["available"]:
        validation_state = "PERSISTED_PERFORMANCE_AVAILABLE"
    elif execution["terminal_rows"] > 0:
        validation_state = "FORWARD_EXECUTION_SAMPLE_ONLY"
    else:
        validation_state = "PROFITABILITY_NOT_YET_VALIDATED"
    return {
        "contract": "XAU_PROFITABILITY_TRUTH_V241_1",
        "validation_state": validation_state,
        "performance": perf,
        "supply_demand_reaction": reaction,
        "authorized_execution": execution,
        "reaction_is_not_win_rate": True,
        "execution_authority": False,
        "live_execution_enabled": False,
    }
