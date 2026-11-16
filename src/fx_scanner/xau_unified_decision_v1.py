"""Fail-closed XAU research confluence; never a Frozen V1 order oracle.

The independent shadow checklist, ICT technical setup and USD/yield context
have different rules. Their concurrence is informative but is NOT proof that
the native Frozen V1 cBot should have submitted an order.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

CONTRACT = "RIZAN_XAU_UNIFIED_DECISION_V1_READONLY"
EXPECTED = {
    "technical": "RIZAN_XAU_TECHNICAL_V1_READONLY",
    "checklist": "RIZAN_XAU_DECISION_CHECKLIST_V1",
    "usd": "RIZAN_USD_LEAD_V1_RESEARCH_ONLY",
    "yield": "RIZAN_US10Y_YIELD_PRESSURE_NOWCAST_V1_READONLY",
}
FIELDS = ("technical", "checklist", "usd", "yield")


def _obj(value):
    return dict(value) if isinstance(value, Mapping) else {}


def _recent(report, key, now):
    r = _obj(report)
    try:
        at = datetime.fromisoformat(str(r.get("as_of_utc")).replace("Z", "+00:00"))
        if at.tzinfo is None:\n            return False\n        delta = (now - at.astimezone(UTC)).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return False
    return (r.get("contract") == EXPECTED[key]
            and r.get("execution_authority") is False
            and r.get("execution_influence") is False
            and 0 <= delta <= 120)


def _gate(name, state, detail):
    return {"name": name, "state": state, "detail": detail}


def _rule_state(items, *, expected=6):
    if not isinstance(items, list) or len(items) != expected:
        return "UNKNOWN"
    states = [x.get("state") for x in items if isinstance(x, Mapping)]
    if len(states) != expected or any(x not in ("PASS", "FAIL", "UNKNOWN") for x in states):
        return "UNKNOWN"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    return "PASS" if all(x == "PASS" for x in states) else "FAIL"


def evaluate_unified(*, technical, checklist, usd, yield_pressure, now=None):
    """Only READY_SHADOW when ALL independently measured gates pass.

    Missing/outdated inputs are UNKNOWN, not negative price evidence and not
    positive confirmation. A shadow setup never authorizes trading or missed-order
    alerts, which require native V1 signal/guard/intent and broker order history.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_HAVE_TIMEZONE")
    now = now.astimezone(UTC)
    reports = {"technical": _obj(technical), "checklist": _obj(checklist),
               "usd": _obj(usd), "yield": _obj(yield_pressure)}
    valid = {name: _recent(reports[name], name, now) for name in FIELDS}
    results = {}
    for side in ("BUY", "SELL"):
        gates = []
        t = _obj(reports["technical"].get(side)) if valid["technical"] else {}
        t_state = _rule_state(t.get("items"))
        t_pass = t_state == "PASS" and t.get("state") == "SETUP_CONFIRMED"
        if valid["technical"] and t_pass:
            t_state = "PASS" if reports["technical"].get("direction") == side and t.get("plan") else "UNKNOWN"
        elif valid["technical"] and t_state == "PASS":
            t_state = "UNKNOWN" if t.get("state") in ("WAIT_CANDLE", "WAIT_DATA") else "FAIL"
        gates.append(_gate("SMC/ICT: H1, sweep, MSS, FVG, RR",
                           t_state if valid["technical"] else "UNKNOWN",
                           "Setup closed-candle dan expiry M5; bukan entry native Frozen V1"))
        c = _obj(reports["checklist"].get(side)) if valid["checklist"] else {}
        c_state = _rule_state(c.get("items"))
        if c_state == "PASS" and c.get("state") != "ALL_CONDITIONS_MET_SHADOW_ONLY":
            c_state = "UNKNOWN"
        gates.append(_gate("Checklist: makro, EMA, ADX, BOS, V404, risiko",
                           c_state if valid["checklist"] else "UNKNOWN",
                           "Risiko wajib memakai equity LIVE terverifikasi, bukan modal awal $100"))
        up = side == "SELL"
        direction_key = "usd_up" if up else "usd_down"
        other_key = "usd_down" if up else "usd_up"
        target = "UP_WATCH" if up else "DOWN_WATCH"
        usd_report = reports["usd"]
        x = _obj(usd_report.get(direction_key))
        other = _obj(usd_report.get(other_key))
        allowed = ("USD_DIRECTION_WATCH_ONLY", "XAU_SELL_SHADOW_WATCH") if up else (
            "USD_DIRECTION_WATCH_ONLY", "XAU_BUY_SHADOW_WATCH")
        opposite_allowed = ("USD_DIRECTION_WATCH_ONLY", "XAU_BUY_SHADOW_WATCH") if up else (
            "USD_DIRECTION_WATCH_ONLY", "XAU_SELL_SHADOW_WATCH")
        if not valid["usd"]:
            u_state = "UNKNOWN"
        elif usd_report.get("usd_direction") == target and x.get("status") in allowed and other.get("status") not in opposite_allowed:
            u_state = "PASS"
        elif other.get("status") in opposite_allowed:
            u_state = "FAIL"
        else:
            u_state = "UNKNOWN"
        gates.append(_gate("USD Lead: ZQ + rate context + DXY",
                           u_state, "Yield resmi harian adalah konteks; DXY konfirmasi, bukan lead"))
        y = reports["yield"]
        expected = "UP" if up else "DOWN"
        if not valid["yield"] or y.get("state") != "CONCORDANT_PROXY":
            y_state = "UNKNOWN"
        else:
            y_state = "PASS" if y.get("yield_direction") == expected else (
                "FAIL" if y.get("yield_direction") in ("UP", "DOWN") else "UNKNOWN")
        gates.append(_gate("Tekanan yield 15–60 menit: ZN + ZQ",
                           y_state, "Proxy futures, bukan real-time yield resmi atau prediksi terkalibrasi"))
        passed = sum(g["state"] == "PASS" for g in gates)
        unknown = sum(g["state"] == "UNKNOWN" for g in gates)
        conflict = any(g["state"] == "FAIL" for g in gates[2:])
        state = ("READY_SHADOW" if passed == len(gates)
                 else "WAIT_DATA" if unknown
                 else "WAIT_CONFLICT" if conflict
                 else "WAIT_SETUP")
        results[side] = {
            "state": state, "gates": gates, "passed": passed,
            "unknown": unknown, "total": len(gates),
            "next_missing": [g["name"] for g in gates if g["state"] != "PASS"],
            "technical_plan": t.get("plan") if valid["technical"] and t_state == "PASS" else None,
        }
    ready = [side for side in ("BUY", "SELL") if results[side]["state"] == "READY_SHADOW"]
    decision = ready[0] if len(ready) == 1 else "WAIT"
    return {
        "contract": CONTRACT, "as_of_utc": now.isoformat(),
        "decision": decision, "BUY": results["BUY"], "SELL": results["SELL"],
        "sources_valid": valid, "order_enabled": False,
        "execution_authority": False, "execution_influence": False,
        "probability_calibrated": False, "out_of_sample_validated": False,
        "frozen_v1_native_signal": "NOT_EVALUATED",
        "missed_order_verdict": "NOT_EVALUATED",
    }
