"""Primary XAU research direction: frozen best *side* candidates, fail closed.

This router consumes only already provenance-validated read-only consumer rows.
Never upgrades archival accuracy, incomplete opponent heads or expired models
to an execution signal.  R28.1 remains an explicitly labeled baseline.
"""
from __future__ import annotations

import pandas as pd

VERSIONS = {
    "H1": {"BUY": "R25", "SELL": "R11"},
    "H4": {"BUY": "R29.2", "SELL": "R11"},
    "D1": {"BUY": "R28.1", "SELL": "R18"},
    "W1": {"BUY": "R27", "SELL": "R24"},
}
LIVE_STATES = ("RESEARCH_SHADOW", "MODEL_ABSTAIN")
DIRECTIONS = ("BUY", "SELL")


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("BEST_SIDE_TIME_MUST_BE_AWARE")
    return stamp.tz_convert("UTC")


def fresh(row, now, allowed=LIVE_STATES):
    if not isinstance(row, dict) or row.get("state") not in allowed:
        return False
    if row.get("execution_authority") is not False:
        return False
    try:
        target = utc(row["target"])
        issued = utc(row["issued"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return issued <= now < target


def item(tf, direction="WAIT", status="WAIT_DATA", reason="NO_VALIDATED_MODEL",
         *, target=None, issued=None, sources=None):
    return {
        "tf": tf, "direction": direction, "status": status, "reason": reason,
        "target": target, "issued": issued, "sources": sources or VERSIONS[tf],
        "execution_authority": False, "execution_influence": False,
        "research_only": True,
    }


def select(best, r294, r281, *, now):
    """Pick H1 R25/R11; H4 R29.2/R11; conditional D1 R28.1 BUY.

    R18 D1 SELL and both W1 heads are not reconstructed at present.
    An unverified/missing counterpart must never be silently substituted
    with an unrelated R28.1 SELL/W1 vote.  All outputs are non-execution.
    """
    now = utc(now)
    best, r294, r281 = best or {}, r294 or {}, r281 or {}
    output = {}

    h1 = best.get("H1") or {}
    if fresh(h1, now):
        buy, sell = h1.get("buy_active"), h1.get("sell_active")
        if type(buy) is bool and type(sell) is bool:
            decision = "WAIT" if buy == sell else "BUY" if buy else "SELL"
            if decision == h1.get("direction"):
                output["H1"] = item(
                    "H1", decision, "ACTIVE_SHADOW" if decision != "WAIT" else "WAIT_MODEL",
                    "SIDE_CONFLICT" if buy and sell else "NO_SIDE_TRIGGER"
                    if not buy and not sell else "R25_R11_FROZEN_TRIGGER",
                    target=h1["target"], issued=h1["issued"])
    if "H1" not in output:
        output["H1"] = item("H1", reason=h1.get("reason") or "RBEST_H1_NOT_FRESH")

    h4 = best.get("H4") or {}
    # Need *both* complete, unexpired source heads to establish conflict.
    if fresh(h4, now) and fresh(r294, now):
        sell = h4.get("sell_active")
        buy = r294.get("direction") == "BUY" and r294.get("state") == "RESEARCH_SHADOW"
        if type(sell) is bool and r294.get("direction") in ("BUY", "WAIT"):
            decision = "WAIT" if buy == sell else "BUY" if buy else "SELL"
            output["H4"] = item(
                "H4", decision, "ACTIVE_SHADOW" if decision != "WAIT" else "WAIT_MODEL",
                "SIDE_CONFLICT" if buy and sell else "NO_SIDE_TRIGGER"
                if not buy and not sell else "R292_BUY_R11_SELL_TRIGGER",
                target=min(h4["target"], r294["target"], key=lambda x: utc(x)),
                issued=max(h4["issued"], r294["issued"], key=lambda x: utc(x)))
    if "H4" not in output:
        missing = "R292_H4_BUY_NOT_FRESH" if not fresh(r294, now) else (
            h4.get("reason") or "RBEST_H4_SELL_NOT_FRESH")
        output["H4"] = item("H4", reason=missing)

    # Only the archived D1 BUY winner has a presently validated live source,
    # and it is multihead R28.1; R18 SELL is still unavailable.
    d1 = r281.get("D1") or {}
    if (fresh(d1, now, ("RECONSTRUCTED_SHADOW",))
            and d1.get("direction") == "BUY"):
        output["D1"] = item(
            "D1", "BUY", "PARTIAL_HEAD", "R281_D1_BUY_LIVE_R18_SELL_UNAVAILABLE",
            target=d1["target"], issued=d1["issued"])
    else:
        output["D1"] = item(
            "D1", status="NOT_INFERENCED",
            reason="R18_D1_SELL_UNAVAILABLE_OR_R281_BUY_NOT_TRIGGERED")

    output["W1"] = item(
        "W1", status="NOT_INFERENCED",
        reason="R27_BUY_R24_SELL_NO_VALIDATED_LIVE_INFERENCE")
    return output
