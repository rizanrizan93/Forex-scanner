"""Shadow-only entry/TP cycle experiments; never imported by execution code.

M1 timestamps are bar opens. Decisions using a close become available one
minute later. Fixed-spread mid OHLC is a proxy, not broker fill evidence.
"""
from __future__ import annotations

from bisect import bisect_left
from math import isfinite
from typing import Any

import pandas as pd

from .research_xau_joint_entry_tp_v280 import _candidates
from .research_xau_v229_historical_v242 import (
    PriceArrays, PIP_SIZE, MIN_TERMINAL_RR, COMMISSION_PIPS_ROUND_TRIP,
)

EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
RESEARCH_VERSION = "XAU_ENTRY_CYCLE_1"
MINUTE = pd.Timedelta(minutes=1)
# Preregistered hypotheses, not fitted recommendations or broker points.
MAX_ADVERSE_USD = 5.0
REACTION_USD = 1.0
FAST_REACTION_MINUTES = 15
MAX_CHASE_USD = 1.0
CYCLE_WINDOW_MINUTES = 30
MAX_CYCLE_GAP_USD = 5.0


def candidate_grid(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every level is frozen at publication; no future wick optimization."""
    sign = 1 if plan["direction"] == "LONG" else -1
    stop = float(plan["stop"])
    result = {}
    baseline = _candidates(plan).get("E1_T1")
    if baseline:
        result["E1_T1"] = dict(entry=baseline[0], target=baseline[1], mode="LIMIT")
    low, high = float(plan["entry_low"]), float(plan["entry_high"])
    if not all(isfinite(x) for x in (low, high, stop)) or low >= high:
        return result
    targets = {int(c["slot"]): c.get("planned_target") for c in plan["children"]
               if int(c["slot"]) in (1, 2)}
    for depth in (0.25, 0.50, 0.75):
        entry = high - depth * (high - low) if sign == 1 else low + depth * (high - low)
        for slot, raw_target in sorted(targets.items()):
            if raw_target is None:
                continue
            for buffer in (0.0, 0.5):
                target = float(raw_target) - sign * buffer
                risk, reward = sign * (entry - stop), sign * (target - entry)
                if not isfinite(reward) or risk <= 0 or reward / risk < MIN_TERMINAL_RR:
                    continue
                for mode in ("LIMIT", "RECLAIM"):
                    key = f"D{int(depth*100)}_T{slot}_B{buffer:g}_{mode}"
                    result[key] = dict(entry=entry, target=target, mode=mode)
    return result


def replay(*, px: PriceArrays, plan: dict[str, Any], candidate: dict[str, Any],
           spread_usd: float = .37, slippage_usd: float = .002,
           hold_minutes: int = 43200) -> dict[str, Any]:
    """Stop wins ties; no target/reaction credit on the fill candle.

    Reclaim requires touch and close back across the entry, then executes at
    the next contiguous bar open. A gap, expiry or chase cancels the setup.
    """
    if plan["direction"] not in ("LONG", "SHORT") or candidate["mode"] not in ("LIMIT", "RECLAIM"):
        raise ValueError("unknown direction or mode")
    if spread_usd < 0 or slippage_usd < 0 or hold_minutes <= 0:
        raise ValueError("invalid costs or horizon")
    sign = 1 if plan["direction"] == "LONG" else -1
    entry, target, stop = (float(candidate["entry"]), float(candidate["target"]), float(plan["stop"]))
    if not all(isfinite(x) for x in (entry, target, stop, spread_usd, slippage_usd)):
        raise ValueError("nonfinite prices")
    if sign*(entry-stop) <= 0 or sign*(target-entry) <= 0:
        raise ValueError("invalid geometry")
    at, expiry = pd.Timestamp(plan["plan_at"]), pd.Timestamp(plan["signal_expires_at"])
    if at.tzinfo is None or expiry.tzinfo is None or expiry <= at:
        raise ValueError("invalid publication window")
    start, end = bisect_left(px.timestamps, at), bisect_left(px.timestamps, expiry)
    half = spread_usd / 2
    missed = lambda reason: dict(state="MISSED", reason=reason, net_r=0.0,
                                 precision_5_and_tp=False, fast_precision_tp=False)
    armed = False
    fill_i = None
    for i in range(start, end):
        # Never use a partially observed bar after a sub-minute publication.
        if px.timestamps[i] < at:
            continue
        exit_extreme = float(px.lows[i])-half if sign == 1 else float(px.highs[i])+half
        if sign*(exit_extreme-stop) <= 0:
            # If touched in the same candle, it is a losing fill for a limit.
            if candidate["mode"] == "RECLAIM":
                return missed("INVALIDATED_BEFORE_CONFIRMATION")
        touched = px.lows[i]+half <= entry if sign == 1 else px.highs[i]-half >= entry
        armed |= bool(touched)
        if candidate["mode"] == "LIMIT" and touched:
            fill_i, fill = i, entry
            break
        close_quote = float(px.closes[i]) + sign*half
        if candidate["mode"] == "RECLAIM" and armed and sign*(close_quote-entry) >= 0:
            j = i+1
            if j >= len(px.timestamps) or px.timestamps[j] != px.timestamps[i]+MINUTE:
                return missed("NO_CONTIGUOUS_CONFIRMATION_EXECUTION")
            if px.timestamps[j] >= expiry:
                return missed("CONFIRMATION_EXPIRED")
            fill = float(px.opens[j]) + sign*(half+slippage_usd)
            if abs(fill-entry) > MAX_CHASE_USD:
                return missed("NO_CHASE")
            fill_i = j
            break
    if fill_i is None:
        if not px.timestamps or px.timestamps[-1]+MINUTE < expiry:
            return dict(state="CENSORED", reason="INCOMPLETE_PENDING_HISTORY")
        return missed("NO_FILL")
    risk, reward = sign*(fill-stop), sign*(target-fill)
    if risk <= 0 or reward/risk < MIN_TERMINAL_RR:
        return missed("RR_AFTER_COST_BELOW_FLOOR")
    fill_at = px.timestamps[fill_i]
    horizon = fill_at + pd.Timedelta(minutes=hold_minutes)
    last = bisect_left(px.timestamps, horizon)
    adverse, reaction_at = 0.0, None
    for i in range(fill_i, last):
        low, high = float(px.lows[i])-half, float(px.highs[i])+half
        adverse = max(adverse, fill-low if sign == 1 else high-fill)
        stop_hit = low <= stop if sign == 1 else high >= stop
        favourable = float(px.highs[i])-half-fill if sign == 1 else fill-(float(px.lows[i])+half)
        target_hit = i > fill_i and (favourable >= reward)
        # A stopped candle cannot establish a favourable event's order.
        if i > fill_i and not stop_hit and reaction_at is None and favourable >= REACTION_USD:
            reaction_at = px.timestamps[i]+MINUTE
        if stop_hit or target_hit:
            state = "STOP" if stop_hit else "TP"
            # Worse opening gaps and stop slippage; limit TP has no price worsening.
            exit_price = (min(stop, float(px.opens[i])-half)-slippage_usd if sign == 1
                          else max(stop, float(px.opens[i])+half)+slippage_usd) if stop_hit else target
            break
    else:
        # A market exit uses the first available open at/after the deadline.
        # Do not backdate it to the last candle before a weekend/data gap.
        if last >= len(px.timestamps):
            return dict(state="CENSORED", reason="NO_EXECUTABLE_TIME_EXIT_QUOTE")
        i = last
        quote = float(px.opens[i])-sign*half
        adverse = max(adverse, sign*(fill-quote))
        state = "STOP" if sign*(quote-stop) <= 0 else "TIME_EXIT"
        exit_price = quote-sign*slippage_usd
        exit_at = px.timestamps[i]
    if state in ("STOP", "TP") and i < last:
        exit_at = px.timestamps[i]+MINUTE  # intrabar outcome known at completion
    reaction_minutes = (reaction_at-fill_at).total_seconds()/60 if reaction_at is not None else None
    precise = state == "TP" and adverse <= MAX_ADVERSE_USD
    return dict(state=state, fill_at=fill_at.isoformat(), exit_at=exit_at.isoformat(),
                fill_price=fill, exit_price=exit_price, target=target,
                net_r=(sign*(exit_price-fill)-COMMISSION_PIPS_ROUND_TRIP*PIP_SIZE)/risk,
                max_adverse_usd=adverse, precision_5_and_tp=precise,
                reaction_minutes=reaction_minutes,
                fast_precision_tp=bool(precise and reaction_minutes is not None and reaction_minutes <= FAST_REACTION_MINUTES),
                holding_minutes=(exit_at-fill_at).total_seconds()/60)


def next_cycle(*, first: dict[str, Any], first_plan: dict[str, Any],
               plans: list[dict[str, Any]], px: PriceArrays, key: str,
               spread_usd: float = .37, slippage_usd: float = .002,
               hold_minutes: int = 43200) -> dict[str, Any]:
    """First new eligible opposite publication wins, regardless of its outcome.

    Previously active plans are excluded: we do not know whether they have
    already filled or invalidated. This intentionally understates coverage.
    """
    if first["state"] != "TP":
        return dict(state="NO_FIRST_TP", cycle_success=False)
    at = pd.Timestamp(first["exit_at"])
    deadline = at + pd.Timedelta(minutes=CYCLE_WINDOW_MINUTES)
    for plan in sorted(plans, key=lambda p: (pd.Timestamp(p["plan_at"]), str(p["plan_id"]))):
        publication = pd.Timestamp(plan["plan_at"])
        if not at <= publication < deadline or plan["direction"] == first_plan["direction"]:
            continue
        candidate = candidate_grid(plan).get(key)
        if candidate is None or abs(candidate["entry"]-first["exit_price"]) > MAX_CYCLE_GAP_USD:
            continue
        bounded = {**plan, "signal_expires_at": min(deadline, pd.Timestamp(plan["signal_expires_at"])).isoformat()}
        second = replay(px=px, plan=bounded, candidate=candidate,
                        spread_usd=spread_usd, slippage_usd=slippage_usd, hold_minutes=hold_minutes)
        if second["state"] == "CENSORED":
            return dict(state="CENSORED", reason="INCOMPLETE_SECOND_LEG_HISTORY")
        return dict(state="SELECTED", next_plan_id=plan["plan_id"], next_result=second,
                    tp_to_next_fill_minutes=(pd.Timestamp(second["fill_at"])-at).total_seconds()/60 if second.get("fill_at") else None,
                    gap_usd=abs(candidate["entry"]-first["exit_price"]),
                    cycle_success=bool(first.get("fast_precision_tp") and second.get("fast_precision_tp")))
    return dict(state="NO_NEW_ELIGIBLE_OPPOSITE_PLAN", cycle_success=False)
