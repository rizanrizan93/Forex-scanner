"""R28.1 -> fresh cTrader zones -> M15 reclaim -> M5 BOS, research-only.

Separate from Frozen V1/cBots. Uses R28.1 shadow for *direction only*,
the pre-existing base/displacement detector on fully closed broker H1/H4,
and a freshly audited M1/M15/M5 confirmation chain. No broker order API.
Not a replay-calibrated execution strategy; all levels are observations.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

import pandas as pd

from .manual_reversal_map import detect

VERSION = "R281_SMC_MANUAL_ENTRY_R1_SHADOW"
NO_EXECUTION = False
TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}
PRIORITY = {
    "M5_BOS_CONFIRMED": 0, "WAIT_BOS_M5": 1, "WAIT_RECLAIM_M15": 2,
    "WATCH_ZONE": 3, "WAIT_TOUCH_EXPIRED": 4, "WAIT_ZONE_GAP": 5,
    "WAIT_BROKER_PRICE": 6, "WAIT_RISK": 7,
}
ACTIVE = "RECONSTRUCTED_SHADOW"


def utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("ENTRY_TIMESTAMP_MUST_BE_TZ_AWARE")
    return t.tz_convert("UTC")


def empty(reason, *, at=None, side="WAIT", context=None):
    return {
        "version": VERSION, "status": "WAIT", "reason": reason,
        "side": side, "checked_at": utc(at or datetime.now(UTC)).isoformat(),
        "context": context or {}, "zone": None, "entry_reference": None,
        "sl_reference": None, "tp_1_5r_reference": None,
        "tp_2r_reference": None, "risk_per_oz": None, "spread": None,
        "confirmation_at": None, "candidates": [],
        "execution_authority": NO_EXECUTION, "execution_influence": False,
        "replay_verified": False,
    }


def direction(shadow, now):
    """D1 + H4 establish the intraday bias. H1 must agree for a trigger.

    Weekly direction is disclosed as a countertrend warning; it is not an
    equally weighted vote because W1/H1 archive folds are not comparable.
    """
    ctx = {}
    for tf in ("H1", "H4", "D1", "W1"):
        row = shadow.get(tf) or {}
        valid = (
            row.get("state") == ACTIVE and row.get("direction") in ("BUY", "SELL")
            and row.get("target") is not None and utc(row["target"]) > now
            and row.get("execution_authority") is False
        )
        ctx[tf] = row["direction"] if valid else "WAIT"
    if ctx["D1"] == "WAIT" or ctx["H4"] == "WAIT":
        return "WAIT", "R28_D1_H4_MISSING_OR_EXPIRED", ctx
    if ctx["D1"] != ctx["H4"]:
        return "WAIT", "R28_D1_H4_CONFLICT", ctx
    side = ctx["D1"]
    if ctx["H1"] not in (side, "WAIT"):
        return "WAIT", "R28_H1_OPPOSING", ctx
    ctx["weekly_countertrend"] = ctx["W1"] in ("BUY", "SELL") and ctx["W1"] != side
    ctx["h1_confirmed"] = ctx["H1"] == side
    return side, "R28_ALIGNED_D1_H4", ctx


def closed_bars(frame, tf, now):
    """Resample only entirely present, fully closed M1 intervals."""
    minutes = TF_MINUTES[tf]
    x = frame.sort_index().copy()
    if x.index.tz is None or x.index.duplicated().any():
        raise ValueError("M1_TIME_NOT_UNIQUE_UTC")
    if not {"open", "high", "low", "close"}.issubset(x.columns):
        raise ValueError("M1_OHLC_MISSING")
    rule = f"{minutes}min"
    q = x.resample(rule, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), count=("close", "size"),
    )
    q = q[(q["count"] == minutes) & (q.index + pd.Timedelta(minutes=minutes) <= now)]
    return q.drop(columns="count").dropna()


def _records(bars):
    if bars.empty:
        return []
    return [
        {"timestamp": at.isoformat(),
         "open": float(row.open), "high": float(row.high),
         "low": float(row.low), "close": float(row.close)}
        for at, row in bars.iterrows()
    ]


def _gap_free(frame, begin, end):
    """Must observe every M1 between a zone's formation and its first touch."""
    if end < begin:
        return False
    if (end - begin).total_seconds() > 72 * 3600:
        return False
    expected = pd.date_range(begin, end, freq="min")
    actual = frame.loc[(frame.index >= begin) & (frame.index <= end)].index
    return len(expected) == len(actual) and expected.equals(actual)


def _price_ok(value):
    return type(value) in (int, float) and isfinite(value) and value > 0


def _evaluate_zone(zone, side, frame, bars, market, now):
    low, high = float(zone["low"]), float(zone["high"])
    formed = utc(zone["available_at"])
    last = float(frame.close.iloc[-1])
    atr = float(zone["atr"])
    out = {
        "side": side, "timeframe": zone["timeframe"],
        "low": low, "high": high, "formed_at": formed.isoformat(),
        "invalidation_reference": (low - .2 * atr if side == "BUY" else high + .2 * atr),
        "atr": atr, "zone_id": zone["zone_id"],
        "last_price": last, "status": "WATCH_ZONE",
        "reason": "MENUNGGU_HARGA_SENTUH_ZONA",
        "touch_at": None, "reclaim_at": None, "bos_at": None,
        "entry_reference": None, "sl_reference": None,
        "tp_1_5r_reference": None, "tp_2r_reference": None,
        "risk_per_oz": None, "spread": None,
    }
    if not (_price_ok(low) and _price_ok(high) and _price_ok(atr) and low < high):
        return None
    if formed > now or formed < frame.index[0]:
        out.update(status="WAIT_ZONE_GAP",reason="ZONE_ORIGIN_OUTSIDE_M1_HISTORY")
        return out
    first = frame.loc[frame.index >= formed]
    contact = first[(first.low <= high) & (first.high >= low)]
    if contact.empty:
        return out
    touched = contact.index[0]
    out["touch_at"] = touched.isoformat()
    if not _gap_free(frame, formed, touched):
        out.update(status="WAIT_ZONE_GAP",reason="UNVERIFIED_FIRST_TOUCH_M1_GAP")
        return out
    if (now - touched).total_seconds() > 90 * 60:
        out.update(status="WAIT_TOUCH_EXPIRED",reason="FIRST_TOUCH_TOO_OLD_FOR_ENTRY")
        return out
    prox = high if side == "BUY" else low
    d = 1 if side == "BUY" else -1
    # A closed M15 must reclaim/reject beyond the zone's proximal edge.
    q15 = bars["M15"]
    candidates15 = q15.loc[(q15.index + pd.Timedelta(minutes=15) > touched)
                           & (q15.index + pd.Timedelta(minutes=15) <= now)]
    candidates15 = candidates15[
        (d * (candidates15.close - prox) > 0)
        & (d * (candidates15.close - candidates15.open) > 0)
    ]
    out.update(status="WAIT_RECLAIM_M15",reason="WAIT_M15_REJECTION_RECLAIM")
    if candidates15.empty:
        return out
    reclaim = candidates15.index[0] + pd.Timedelta(minutes=15)
    out["reclaim_at"] = reclaim.isoformat()
    # Compare against 3 fully closed and adjacent earlier M5 bars.
    q5 = bars["M5"]
    out.update(status="WAIT_BOS_M5",reason="WAIT_M5_BOS_AFTER_M15")
    bos = None
    for i in range(3, len(q5)):
        bar_at = q5.index[i] + pd.Timedelta(minutes=5)
        if bar_at <= reclaim or bar_at > now:
            continue
        prior = q5.iloc[i-3:i]
        if any(q5.index[i-3+j] != q5.index[i-3] + pd.Timedelta(minutes=5*j)
               for j in range(4)):
            continue
        bar = q5.iloc[i]
        breaks = bar.close > prior.high.max() if d == 1 else bar.close < prior.low.min()
        if breaks and d * (bar.close - bar.open) > 0 and d * (bar.close - prox) > 0:
            bos = (bar_at, float(bar.close))
    if bos is None:
        return out
    at, bos_close = bos
    out["bos_at"] = at.isoformat()
    if (now - at).total_seconds() > 10 * 60:
        out.update(status="WAIT_TOUCH_EXPIRED", reason="M5_BOS_ALREADY_PASSED")
        return out
    out.update(status="M5_BOS_CONFIRMED",reason="R28_M15_M5_RESEARCH_ALIGNMENT")
    bid, ask, quote_at = market.get("bid"), market.get("ask"), market.get("quote_as_of")
    if not (_price_ok(bid) and _price_ok(ask) and bid <= ask and quote_at is not None
            and 0 <= (now - utc(quote_at)).total_seconds() <= 30):
        out.update(status="WAIT_BROKER_PRICE",reason="QUOTE_SPREAD_NOT_FRESH")
        return out
    entry = float(ask if side == "BUY" else bid)
    spread = float(ask-bid)
    sl = float(out["invalidation_reference"])
    risk = d*(entry-sl)
    out["spread"] = spread
    # No chasing after the BOS candle; do not turn high historical accuracy
    # into an unconditional price prediction.
    if abs(entry-bos_close) > .5*atr or d*(entry-prox) > atr:
        out.update(status="WAIT_RISK",reason="PRICE_ALREADY_MOVED_FROM_BOS")
        return out
    if risk <= 0 or risk < max(3*spread, .1*atr):
        out.update(status="WAIT_RISK",reason="STOP_DISTANCE_OR_COST_INVALID")
        return out
    tp15, tp2 = entry + d*1.5*risk, entry + d*2.0*risk
    out.update(entry_reference=entry, sl_reference=sl, risk_per_oz=risk,
               tp_1_5r_reference=tp15,tp_2r_reference=tp2)
    return out


def evaluate_entry(shadow, market, *, now=None):
    """Deterministic research-stage manual watch. Never grants order authority."""
    now = utc(now or datetime.now(UTC))
    side, reason, ctx = direction(shadow, now)
    result = empty(reason, at=now, side=side, context=ctx)
    if side == "WAIT":
        return result
    if market is None or not isinstance(market, dict) or not isinstance(market.get("frame"), pd.DataFrame):
        result["reason"] = "BROKER_M1_UNAVAILABLE"
        return result
    observed = market.get("as_of")
    if observed is None or not 0 <= (now-utc(observed)).total_seconds() <= 90:
        result["reason"] = "BROKER_M1_STALE"
        return result
    frame = market["frame"].sort_index().copy()
    if len(frame) < 1440 or frame.empty or frame.index.tz is None:
        result["reason"] = "M1_HISTORY_INSUFFICIENT"
        return result
    if frame.index.duplicated().any():
        result["reason"] = "M1_DUPLICATED_TIME"
        return result
    if not 0 <= (now-(frame.index[-1]+pd.Timedelta(minutes=1))).total_seconds() <= 120:
        result["reason"] = "LAST_M1_NOT_FRESH"
        return result
    try:
        bars = {tf: closed_bars(frame, tf, now) for tf in TF_MINUTES}
        if len(bars["M5"]) < 10 or len(bars["M15"]) < 10:
            result["reason"] = "CLOSED_M5_M15_UNAVAILABLE"
            return result
        zones = []
        for tf in ("H1", "H4"):
            sample = bars[tf]
            if len(sample) < 24:
                continue
            zones += detect(_records(sample),tf,now)
        valid = []
        for z in zones:
            if z.get("direction") != side or z.get("structural_bos") is not True:
                continue
            if z.get("lifecycle") not in ("FRESH","RETESTED") or z.get("touch_count",999) > 1:
                continue
            born = utc(z["available_at"])
            age_limit = 24 if z["timeframe"] == "H1" else 72
            if not 0 <= (now-born).total_seconds() <= age_limit*3600:
                continue
            item = _evaluate_zone(z,side,frame,bars,market,now)
            if item is not None:
                valid.append(item)
        if not valid:
            result["reason"] = "NO_VALID_CLOSED_H1_H4_BOS_ZONE"
            return result
        last=float(frame.close.iloc[-1])
        valid.sort(key=lambda z: (
            PRIORITY.get(z["status"],99),
            max(z["low"]-last,last-z["high"],0),-utc(z["formed_at"]).timestamp()
        ))
        result["candidates"] = valid[:6]
        chosen=valid[0]
        result["zone"]=chosen
        result["status"]=chosen["status"]
        result["reason"]=chosen["reason"]
        # H1 must confirm D1+H4 before an entry reference may be shown.
        if chosen["status"] == "M5_BOS_CONFIRMED" and ctx.get("h1_confirmed") is not True:
            result["status"] = "WAIT"
            result["reason"] = "R28_H1_NOT_CONFIRMED"
            return result
        if chosen["status"] == "M5_BOS_CONFIRMED":
            result.update(
                entry_reference=chosen["entry_reference"],
                sl_reference=chosen["sl_reference"],
                tp_1_5r_reference=chosen["tp_1_5r_reference"],
                tp_2r_reference=chosen["tp_2r_reference"],
                risk_per_oz=chosen["risk_per_oz"],
                spread=chosen["spread"],
                confirmation_at=chosen["bos_at"],
            )
        return result
    except (ValueError, TypeError, IndexError, KeyError, OverflowError, ArithmeticError):
        result["status"]="WAIT"
        result["reason"]="ENTRY_CANDLE_CONTRACT_FAILED"
        return result
