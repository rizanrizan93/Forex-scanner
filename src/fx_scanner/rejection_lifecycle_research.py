"""Causal, immutable-price rejection lifecycle (research/read-only only).

A wick is EARLY, never evidence of a durable reversal. A confirmed close across
the frozen failure boundary rescinds the setup; an M5 close upgrades to a
confirmed breakout. Quote-only breaches are risk alerts, not candle closes.
"""
from __future__ import annotations
import math
import pandas as pd

TERMINAL = frozenset({"BREAKOUT_CONFIRMED", "REJECTION_INVALIDATED", "EXPIRED", "DATA_GAP"})
MAX_EVENTS = 18
NEW_EVENT_COOLDOWN_MINUTES = 15
EARLY_EXPIRY_MINUTES = 30
CONFIRMED_EXPIRY_MINUTES = 120


def _utc(v) -> pd.Timestamp:
    ts = pd.Timestamp(v)
    if ts.tzinfo is None:
        raise ValueError("Event times must have timezone")
    return ts.tz_convert("UTC")


def _crossed(side: str, value: float, level: float) -> bool:
    return value > level if side == "SELL" else value < level


def _directional_break(side: str, value: float, level: float) -> bool:
    return value < level if side == "SELL" else value > level


def advance_events(prior_events, m1: pd.DataFrame, m5: pd.DataFrame,
                   zones: list[dict], *, now, atr: float, bid=None, ask=None,
                   quote_valid: bool = False) -> list[dict]:
    """Return JSON-safe immutable price geometry and evolving event states.

    m1: UTC indexed CLOSED M1 prices with indices marking OPEN time.
    m5: UTC indexed COMPLETED M5 bars with indices marking CLOSE time.
    zones: current model's watch zones. Only EARLY REJECTION creates new events.
    Caller persists returned records, but function never sends any order.
    """
    at = _utc(now)
    if not math.isfinite(float(atr)) or atr <= 0:
        raise ValueError("ATR must be positive")
    if not isinstance(m1.index, pd.DatetimeIndex) or m1.index.tz is None:
        raise ValueError("M1 timestamps must be UTC aware")
    events = [dict(e) for e in (prior_events or [])]
    for event in events:
        side = event["side"]
        if side not in ("BUY", "SELL") or event.get("state") not in TERMINAL | {"EARLY_REJECTION", "REJECTION_CONFIRMED"}:
            raise ValueError("Invalid lifecycle event")
        cutoff = float(event["invalidation"])
        began = _utc(event["signal_at"])
        checked = _utc(event.get("checked_through", event["signal_at"]))
        if checked > at or began > at:
            raise ValueError("Future prior event")
        # Terminal invalidations are retained to prevent a stale "VALID" label
        # resurrecting when a dynamic EMA shifts.
        if event["state"] not in TERMINAL:
            recent = m1.loc[(m1.index + pd.Timedelta(minutes=1) > checked) &
                            (m1.index + pd.Timedelta(minutes=1) <= at)]
            cursor = checked
            for opened, bar in recent.iterrows():
                closed = opened + pd.Timedelta(minutes=1)
                if closed - cursor != pd.Timedelta(minutes=1):
                    event["state"] = "DATA_GAP"
                    event["gap_detected_at"] = at.isoformat()
                    event["reason"] = "M1 history gap; prior rejection cannot be verified"
                    break
                cursor = closed
                if _crossed(side, float(bar.close), cutoff):
                    event["state"] = "REJECTION_INVALIDATED"
                    event["reason"] = "Closed M1 breached frozen event high/low + buffer"
                    event["invalidated_at"] = closed.isoformat()
                    break
                trigger = float(event["structure_trigger"])
                if event["state"] == "EARLY_REJECTION" and _directional_break(side, float(bar.close), trigger):
                    event["state"] = "REJECTION_CONFIRMED"
                    event["confirmed_at"] = closed.isoformat()
                    event["reason"] = "M1 close broke pre-event three-bar structure"
            event["checked_through"] = cursor.isoformat()
            timeout = CONFIRMED_EXPIRY_MINUTES if event["state"] == "REJECTION_CONFIRMED" else EARLY_EXPIRY_MINUTES
            if event["state"] not in TERMINAL and (at-began).total_seconds() > timeout*60:
                event["state"] = "EXPIRED"
                event["reason"] = "Rejection observation expired without fresh setup"
        # An M5 completed close beyond the frozen hard boundary takes precedence,
        # including after a prior M1 invalidation.
        if event["state"] in {"EARLY_REJECTION", "REJECTION_CONFIRMED", "REJECTION_INVALIDATED"}:
            later = m5.loc[(m5.index > began) & (m5.index <= at)]
            breakout = later.loc[(later.close > cutoff) if side=="SELL" else (later.close < cutoff)]
            if len(breakout):
                event["state"] = "BREAKOUT_CONFIRMED"
                event["reason"] = "Completed M5 close outside frozen rejection boundary"
                event["breakout_at"] = breakout.index[0].isoformat()
        event["display_state"] = event["state"]
        if event["state"] in {"EARLY_REJECTION", "REJECTION_CONFIRMED"} and quote_valid:
            quote = ask if side == "SELL" else bid
            if quote is not None and _crossed(side, float(quote), cutoff):
                event["display_state"] = "BREAKOUT_RISK"
                event["risk_reason"] = "Live quote breached frozen rejection boundary; await closed M1/M5"
    # Create a new event from the latest closed M1, with a frozen boundary;
    # repeated EMA touches cannot continuously create 'new' valid SELL.
    closed_at = m1.index[-1] + pd.Timedelta(minutes=1)
    if pd.Timedelta(0) <= at-closed_at <= pd.Timedelta(seconds=90):
        last = m1.iloc[-1]
        preceding = m1.iloc[-4:-1]
        if len(preceding) == 3 and all(
            preceding.index[i+1]-preceding.index[i]==pd.Timedelta(minutes=1) for i in range(2)
        ):
            for z in zones:
                if z.get("stage") != "EARLY REJECTION":
                    continue
                side, name = z["side"], z["name"]
                if side not in ("BUY","SELL"):
                    continue
                # Whole-side cooldown: a breakout or missing observation must
                # never be disguised as a 'fresh' rejection at a different EMA.
                blocked = False
                for older in events:
                    if older["side"] != side:
                        continue
                    if older.get("display_state") == "BREAKOUT_RISK":
                        blocked = True
                        break
                    if older["state"] not in {"REJECTION_INVALIDATED",
                                               "BREAKOUT_CONFIRMED","DATA_GAP"}:
                        continue
                    failure = (older.get("breakout_at") or older.get("invalidated_at")
                               or older.get("gap_detected_at") or older.get("checked_through"))
                    if failure and 0 <= (at-_utc(failure)).total_seconds() <= NEW_EVENT_COOLDOWN_MINUTES*60:
                        blocked = True
                        break
                if blocked:
                    continue
                previous = [e for e in events if e["side"]==side and e["zone_name"]==name]
                if previous and (
                    at - _utc(previous[-1]["signal_at"])
                ).total_seconds() < NEW_EVENT_COOLDOWN_MINUTES*60:
                    continue
                # Never issue a new same-side event while an earlier same-zone
                # event remains active. Invalidation does not erase its audit.
                if any(e["state"] not in TERMINAL for e in previous):
                    continue
                zone_lower, zone_upper = float(z["low"]), float(z["high"])
                invalid = (min(float(last.low), zone_lower)-0.10*atr if side=="BUY"
                           else max(float(last.high), zone_upper)+0.10*atr)
                trigger = float(preceding.high.max() if side=="BUY" else preceding.low.min())
                events.append({
                    "id": side+"|"+name+"|"+closed_at.isoformat(),
                    "side": side, "zone_name": name,
                    "level": float(z["price"]), "zone_low": zone_lower,
                    "zone_high": zone_upper, "signal_at": closed_at.isoformat(),
                    "observed_at": at.isoformat(),
                    "checked_through": closed_at.isoformat(),
                    "state": "EARLY_REJECTION",
                    "display_state": "EARLY_REJECTION",
                    "invalidation": round(invalid,5),
                    "structure_trigger": round(trigger,5),
                    "reason": "M1 wick/reclaim detected; reversal NOT confirmed",
                })
    # The latest quote can already be beyond invalidation when a new event is
    # first detected. Mark risk immediately, even before a new M1 close exists.
    if quote_valid:
        for event in events:
            if event["state"] not in {"EARLY_REJECTION", "REJECTION_CONFIRMED"}:
                continue
            quote = ask if event["side"]=="SELL" else bid
            if quote is not None and _crossed(event["side"],float(quote),float(event["invalidation"])):
                event["display_state"]="BREAKOUT_RISK"
                event["risk_reason"]="Quote crossed frozen boundary; confirm with closed candle"
    return events[-MAX_EVENTS:]
