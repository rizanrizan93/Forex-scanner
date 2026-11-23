"""Read-only SMC direction gate for separately validated frozen best-side models.

Uses the primary H1/H4/D1/W1 candidate board; NEVER uses R28.1 H1/H4/W1
as an unstated fallback. Incomplete D1 head or H1 abstention permits *watch*
of a validated H4 zone only. Every watch scrubs numeric entry/SL/TP levels.
No order endpoint or Frozen V1 integration.
"""
from __future__ import annotations

from datetime import UTC, datetime
import pandas as pd

from .best_candidate_direction import VERSIONS
from .r281_smc_entry_engine import evaluate_entry

ACTIVE = ("ACTIVE_SHADOW", "PARTIAL_HEAD")


def utc(value):
    t=pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("BEST_SMC_TIME_NAIVE")
    return t.tz_convert("UTC")


def verified(row, tf, now):
    if not isinstance(row, dict) or row.get("tf") != tf:
        return False
    if row.get("status") not in ACTIVE or row.get("direction") not in ("BUY", "SELL"):
        return False
    if (row.get("sources") != VERSIONS[tf]
            or row.get("execution_authority") is not False
            or row.get("execution_influence") is not False
            or row.get("research_only") is not True):
        return False
    try:
        issued, target=utc(row["issued"]),utc(row["target"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
    return issued <= now < target


def best_direction(primary, now):
    """D1 only grants a complete alignment if both side heads are proven.

    R28.1 D1 BUY is multihead PARTIAL_HEAD: even when aligned with H1/H4 it
    cannot grant levels until R18 independent SELL is parity verified.
    """
    now=utc(now)
    primary=primary or {}
    ctx={}
    rows={}
    for tf in ("H1","H4","D1","W1"):
        r=primary.get(tf) or {}
        rows[tf]=r
        ctx[tf]=r["direction"] if verified(r,tf,now) else "WAIT"

    h4=ctx["H4"]
    if h4=="WAIT":
        return "WAIT","BEST_H4_MISSING_OR_EXPIRED",ctx

    # Do not label a counter-direction as a pullback and encourage an entry.
    for tf in ("H1","D1"):
        if ctx[tf] in ("BUY","SELL") and ctx[tf]!=h4:
            return "WAIT","BEST_"+tf+"_OPPOSING",ctx
    ctx["h4_confirmed"]=True
    ctx["h1_confirmed"]=ctx["H1"]==h4
    ctx["d1_confirmed"]=(ctx["D1"]==h4 and
                          rows["D1"].get("status")=="ACTIVE_SHADOW")
    ctx["weekly_countertrend"]=ctx["W1"] in ("BUY","SELL") and ctx["W1"]!=h4
    ctx["d1_partial"]=(ctx["D1"]==h4 and
                        rows["D1"].get("status")=="PARTIAL_HEAD")
    ctx["watch_only"]=not (ctx["h1_confirmed"] and ctx["d1_confirmed"])
    if ctx["watch_only"]:
        return h4,"BEST_DIRECTION_INCOMPLETE_WATCH_ONLY",ctx
    return h4,"BEST_DIRECTION_ALIGNED",ctx


def evaluate_best_entry(primary,market,*,now=None):
    return evaluate_entry(primary,market,now=now,
                          direction_resolver=best_direction)
