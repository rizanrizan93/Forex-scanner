"""RIZAN R6.3: deterministic macro versus *closed-bar XAU* divergence audit.

IMPORTANT: This is an explanatory PRICE-CONFIRMATION VETO for a
read-only manual WATCH panel, not a backtested new alpha model,
not a live Fed surprise feed, and never a cBot order.
Market direction from R6.1 and 2019-2026 FOMC event-study findings
must NOT override H1 and M15 completed-bar XAU structure.

M15 and H1 both use EMA20 price+EMA-slope gates, plus H4 veto if
enough closed data. This is heuristic, not a validated SMC/ICT BOS
or probability. Do not pretend a daily yield change and today's
DXY tick occurred simultaneously.
"""
from __future__ import annotations
from datetime import UTC, datetime
from math import isfinite

CONTRACT = "RIZAN_R63_XAU_MACRO_PRICE_DIVERGENCE_READONLY_V1"
MACRO_CONTRACT = "RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1"
PRICE_CONTRACT = "RIZAN_XAU_FED_R6_MANUAL_AREA_V1"
DIRECTIONS = frozenset(("BUY","SELL","WAIT"))


def evaluate_divergence(market, price):
    """Return explicit context vs price disagreement with NO trade authority."""
    base = {
        "contract": CONTRACT,
        "state": "WAIT_UNVERIFIED_MARKET_OR_PRICE",
        "display_direction": "WAIT",
        "macro_context": "WAIT",
        "daily_yield_lean": "WAIT",
        "price_structure": "WAIT",
        "price_m15": "UNKNOWN",
        "price_h1": "UNKNOWN",
        "price_h4": "UNKNOWN",
        "reason": "MISSING_OR_MISMATCHED_SOURCE_CONTRACTS",
        "watch_side": "WAIT",
        "divergence": False,
        "validated_historical_performance": False,
        "confidence_pct": None,
        "point_in_time_paired_macro_price_data": False,
        "entry_permission": False,
        "authority_to_send_orders": False,
        "execution_influence": False,
    }
    if (not isinstance(market,dict) or market.get("contract") != MACRO_CONTRACT
        or not isinstance(price,dict) or price.get("contract") != PRICE_CONTRACT):
        return base
    macro = market.get("direction")
    lean = market.get("daily_direction")
    m15 = price.get("bias_m15")
    h1 = price.get("bias_h1")
    h4 = price.get("bias_h4")
    base.update({
        "macro_context": macro if macro in DIRECTIONS else "WAIT",
        "daily_yield_lean": lean if lean in DIRECTIONS else "WAIT",
        "price_m15":m15 if m15 in ("BUY","SELL","MIXED") else "UNKNOWN",
        "price_h1":h1 if h1 in ("BUY","SELL","MIXED") else "UNKNOWN",
        "price_h4":h4 if h4 in ("BUY","SELL","MIXED") else "UNKNOWN",
    })
    if price.get("entry_allowed") is not False or price.get("authority_to_send_orders") is not False:
        base["reason"] = "PRICE_REPORT_PRIVILEGES_UNTRUSTED"
        return base
    if price.get("status") not in ("WAIT","WATCH") or price.get("price") is None:
        base["reason"] = "NO_FRESH_XAU_CLOSED_M1_QUOTE"
        return base
    if price.get("quote_at") is None or price.get("last_closed_m1") is None:
        base["reason"] = "NO_FRESH_XAU_QUOTE_OR_BAR"
        return base
    try:
        now = datetime.fromisoformat(price["as_of"].replace("Z","+00:00"))
        quote = datetime.fromisoformat(price["quote_at"].replace("Z","+00:00"))
        bar = datetime.fromisoformat(price["last_closed_m1"].replace("Z","+00:00"))
        if any(t.tzinfo is None for t in (now,quote,bar)):
            base["reason"] = "NAIVE_PRICE_CLOCK"
            return base
        if not (0 <= (now-quote).total_seconds() <=30
                and 0<= (now-bar).total_seconds() <=90):
            base["reason"] = "STALE_PRICE_TIME"
            return base
    except (ValueError,TypeError,KeyError):
        base["reason"] = "PRICE_TIMESTAMPS_UNAVAILABLE"
        return base
    if m15 not in ("BUY","SELL") or h1 not in ("BUY","SELL") or m15!=h1:
        base["state"] = "WAIT_XAU_STRUCTURE_MIXED"
        base["reason"] = "M15_H1_NOT_SAME_DIRECTION"
        return base
    side = m15
    if h4 in ("BUY","SELL") and h4!=side:
        base["state"] = "WAIT_H4_OPPOSES_M15_H1"
        base["reason"] = "H4_OPPOSING_STRONG_PRICE_DIRECTION"
        return base
    base["price_structure"]=side
    if macro not in ("BUY","SELL"):
        if lean in ("BUY","SELL") and lean!=side:
            base["state"]="DAILY_MACRO_LEAN_VS_XAU_DIVERGENCE"
            base["divergence"]=True
            base["reason"]="TREASURY_DAILY_LEAN_OPPOSES_LIVE_XAU_M15_H1"
        else:
            base["state"]="TECHNICAL_DIRECTION_ONLY_MACRO_WAIT"
            base["reason"]="PRICE_TREND_OBSERVED_BUT_NO_VERIFIED_MACRO_CONFLUENCE"
        base["watch_side"]=side
        return base
    if macro!=side:
        base["state"]="MACRO_PRICE_DIVERGENCE"
        base["divergence"]=True
        base["reason"]="MARKET_MACRO_SIDE_OPPOSES_CLOSED_XAU_M15_H1"
        base["watch_side"]=side
        return base
    base["state"]="MACRO_AND_PRICE_ALIGNED_WATCH"
    base["watch_side"]=side
    base["display_direction"]=side
    base["reason"]="MACRO_CONTEXT_AND_CLOSED_XAU_M15_H1_SAME_SIDE"
    # Even full alignment does NOT pass historical Fed R4 or authorize orders.
    return base
