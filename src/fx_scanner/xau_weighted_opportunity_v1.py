"""Read-only opportunity scoring independent of Frozen V1 order decisions.

This is a research ranking, NOT a probability, order authorization, or evidence
of a missed native cBot signal. Unknown data contributes zero, never a PASS.
"""
from __future__ import annotations

from typing import Mapping

WEIGHTS = {"smc": 40.0, "momentum": 25.0, "usd": 15.0, "yield": 10.0, "zone": 10.0}
SMC_KEYS = ("h1", "location", "sweep", "mss", "fvg", "rr")
MOMENTUM_KEYS = ("h1", "m15", "m5")
STATES = ("PASS", "FAIL", "UNKNOWN")
RANKS = {
    "CONFIRMED_SHADOW": 4, "ARMED_SHADOW": 3, "WATCH_SHADOW": 2,
    "WATCH_CONFLICT": 1, "WAIT_RISK": 0, "WAIT_DATA": 0, "NO_SETUP": 0,
}


def _obj(value):
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(report, side, expected_keys, *, valid):
    if not valid:
        return {key: "UNKNOWN" for key in expected_keys}
    items = _obj(_obj(report).get(side)).get("items")
    if not isinstance(items, list) or len(items) < len(expected_keys):
        return {key: "UNKNOWN" for key in expected_keys}
    by_key = {}
    for item in items:
        item = _obj(item)
        key = item.get("key")
        if key in by_key:
            return {name: "UNKNOWN" for name in expected_keys}
        if isinstance(key, str) and item.get("state") in STATES:
            by_key[key] = item["state"]
    return {key: by_key.get(key, "UNKNOWN") for key in expected_keys}


def _component(name, states):
    states = list(states)
    weight = WEIGHTS[name]
    return {
        "name": name,
        "weight": weight,
        "earned": weight * sum(s == "PASS" for s in states) / len(states),
        "covered": weight * sum(s != "UNKNOWN" for s in states) / len(states),
        "passed": sum(s == "PASS" for s in states),
        "failed": sum(s == "FAIL" for s in states),
        "unknown": sum(s == "UNKNOWN" for s in states),
        "states": states,
    }


def evaluate_opportunity(*, unified, technical, checklist):
    """Convert independently audited gates into actionable WATCH/ARMED research.

    Price/closed-candle evidence must be valid before assigning a watch state.
    Risk FAIL blocks confirmed/armed; risk UNKNOWN permits preparation only.
    Macro/yield disagreement blocks armed/confirmed but never impersonates
    an actual native Frozen V1 entry trigger.
    """
    u = _obj(unified)
    valid = _obj(u.get("sources_valid"))
    if u.get("execution_authority") is not False or u.get("order_enabled") is not False:
        valid = {key: False for key in ("technical", "checklist", "usd", "yield")}
    output = {}
    for side in ("BUY", "SELL"):
        tech = _obj(_obj(technical).get(side))
        checks = _obj(_obj(checklist).get(side))
        smc = _rows(technical, side, SMC_KEYS, valid=valid.get("technical") is True)
        momentum = _rows(checklist, side, MOMENTUM_KEYS, valid=valid.get("checklist") is True)
        extras = _rows(checklist, side, ("v404", "risk"), valid=valid.get("checklist") is True)
        gates = _obj(u.get(side)).get("gates")
        gates = gates if isinstance(gates, list) and len(gates) == 4 else []
        usd_state = _obj(gates[2]).get("state") if valid.get("usd") is True and gates else "UNKNOWN"
        yield_state = _obj(gates[3]).get("state") if valid.get("yield") is True and gates else "UNKNOWN"
        usd_state = usd_state if usd_state in STATES else "UNKNOWN"
        yield_state = yield_state if yield_state in STATES else "UNKNOWN"
        parts = [
            _component("smc", smc.values()),
            _component("momentum", momentum.values()),
            _component("usd", [usd_state]),
            _component("yield", [yield_state]),
            _component("zone", [extras["v404"]]),
        ]
        score = round(sum(part["earned"] for part in parts), 1)
        coverage = round(sum(part["covered"] for part in parts), 1)
        smc_pass = sum(state == "PASS" for state in smc.values())
        momentum_pass = sum(state == "PASS" for state in momentum.values())
        price_valid = (
            valid.get("technical") is True
            and tech.get("state") not in ("WAIT_CANDLE", "WAIT_DATA")
            and not _obj(technical).get("errors")
            and all(state != "UNKNOWN" for state in smc.values())
        )
        conflict = usd_state == "FAIL" or yield_state == "FAIL"
        risk_state = extras["risk"]
        full_structure = (
            tech.get("state") == "SETUP_CONFIRMED"
            and _obj(technical).get("direction") == side
            and isinstance(tech.get("plan"), Mapping)
            and all(s == "PASS" for s in smc.values())
        )
        watch = score >= 35 and smc_pass >= 2 and momentum_pass >= 1
        armed = (
            score >= 55 and smc_pass >= 4 and momentum_pass >= 1
            and smc["sweep"] == "PASS" and smc["mss"] == "PASS"
        )
        if not price_valid:
            state = "WAIT_DATA"
        elif risk_state == "FAIL" and watch:
            state = "WAIT_RISK"
        elif full_structure and score >= 70 and risk_state == "PASS" and not conflict:
            state = "CONFIRMED_SHADOW"
        elif conflict and watch:
            state = "WATCH_CONFLICT"
        elif armed:
            state = "ARMED_SHADOW"
        elif watch:
            state = "WATCH_SHADOW"
        else:
            state = "NO_SETUP"
        missing = [
            part["name"] for part in parts
            if part["earned"] + 0.0001 < part["weight"]
        ]
        output[side] = {
            "state": state, "score": score, "coverage": coverage,
            "components": parts, "missing": missing,
            "risk": risk_state, "price_valid": price_valid,
            "macro_conflict": conflict,
            "technical_plan": tech.get("plan") if full_structure else None,
        }
    candidates = [(RANKS[output[s]["state"]], output[s]["score"], s)
                  for s in ("BUY", "SELL") if RANKS[output[s]["state"]] >= 2]
    preferred = max(candidates)[2] if candidates else "WAIT"
    return {
        "BUY": output["BUY"], "SELL": output["SELL"],
        "preferred": preferred, "weights": dict(WEIGHTS),
        "scoring_is_probability": False,
        "order_enabled": False, "execution_authority": False,
        "frozen_v1_signal": "NOT_EVALUATED",
        "missed_order_verdict": "NOT_EVALUATED",
    }
