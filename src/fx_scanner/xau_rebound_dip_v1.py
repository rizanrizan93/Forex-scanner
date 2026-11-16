"""Read-only XAU rebound/dip tactical watchlists, not a cBot execution signal.

Uses closed LIVE cTrader candles and already validated scanner macro/news inputs.
Never substitutes a historical macro narrative for a fresh feed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

from .xau_decision_checklist_v1 import atr14, closed_bars, ema, stamp
from .xau_technical_engine_v1 import pivots

CONTRACT = "RIZAN_XAU_REBOUND_DIP_V1_SHADOW"


def _obj(value):
    return dict(value) if isinstance(value, dict) else {}


def _pass(items, key):
    return any(item.get("key") == key and item.get("state") == "PASS"
               for item in items if isinstance(item, dict))


def _unique(values, price, atr, above):
    levels = sorted((float(x) for x in values
                     if isinstance(x, (float, int)) and isfinite(x) and x > 0
                     and ((x > price + .15 * atr) if above else (x < price - .15 * atr))),
                    reverse=not above)
    result = []
    for value in levels:
        if all(abs(value - known) >= .65 * atr for known in result):
            result.append(value)
    return result[:3]


def macro_vote(evaluation, usd, yield_pressure, now):
    """Score corroborated live context only; news is optional and expires in 1h."""
    quality = _obj(_obj(evaluation).get("attribution_quality"))
    votes, evidence = 0, []
    if quality.get("quality_state") == "ALIGNED_CONTEXT_ONLY":
        bias = quality.get("quality_screened_bias")
        if bias == "BEARISH_XAU":
            votes += 2
            evidence.append("Makro tervalidasi: BEARISH_XAU (+2 SELL)")
        elif bias == "BULLISH_XAU":
            votes -= 2
            evidence.append("Makro tervalidasi: BULLISH_XAU (+2 BUY)")
    usd_direction = _obj(usd).get("usd_direction")
    if usd_direction == "UP_WATCH":
        votes += 1
        evidence.append("USD Lead menguat (+1 SELL)")
    elif usd_direction == "DOWN_WATCH":
        votes -= 1
        evidence.append("USD Lead melemah (+1 BUY)")
    yp = _obj(yield_pressure)
    if yp.get("state") == "CONCORDANT_PROXY":
        if yp.get("yield_direction") == "UP":
            votes += 1
            evidence.append("Tekanan yield intraday naik (+1 SELL)")
        elif yp.get("yield_direction") == "DOWN":
            votes -= 1
            evidence.append("Tekanan yield intraday turun (+1 BUY)")
    event = _obj(quality.get("event_quality"))
    event_time = stamp(event.get("event_time"))
    if event_time is not None and 0 <= (now - event_time).total_seconds() <= 3600:
        if event.get("state") == "VERIFIED_HOT":
            votes += 1
            evidence.append("Actual berita AS HOT terverifikasi <60 menit (+1 SELL)")
        elif event.get("state") == "VERIFIED_COOL":
            votes -= 1
            evidence.append("Actual berita AS COOL terverifikasi <60 menit (+1 BUY)")
    if not evidence:
        direction = "WAIT_DATA"
    elif votes >= 2:
        direction = "SELL"
    elif votes <= -2:
        direction = "BUY"
    else:
        direction = "MIXED"
    return {"direction": direction, "net_votes": votes,
            "evidence": evidence,
            "note": "Real yield Treasury/FRED adalah konteks harian; yield intraday berupa proxy, bukan kutipan resmi."}


def evaluate_rebound_dip(feed, technical, checklist, usd, yield_pressure,
                         evaluation, *, now):
    """Evaluate watch zones; never set an order or claim calibrated win-rate."""
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE")
    now = now.astimezone(UTC)
    macro = macro_vote(evaluation, usd, yield_pressure, now)
    output = {"contract": CONTRACT, "execution_authority": False,
              "execution_influence": False, "order_enabled": False,
              "as_of_utc": now.isoformat(), "macro": macro,
              "preferred": "WAIT_DATA", "reason": "", "reference_close": None}
    bars, errors = {}, []
    for tf in ("H1", "M15", "M5"):
        bars[tf], err = closed_bars(feed, tf, now)
        if err:
            errors.append(tf + ": " + err)
    if _obj(technical).get("errors"):
        errors += list(technical["errors"])
    if errors:
        output["reason"] = "WAIT DATA: " + "; ".join(dict.fromkeys(errors))
        for side in ("SELL", "BUY"):
            output[side] = {"state": "WAIT_DATA", "zones": [], "conditions": [],
                            "score": None}
        return output

    h1, m15, m5 = bars["H1"], bars["M15"], bars["M5"]
    price = m5[-1]["c"]
    atr = atr14(m5)
    if atr is None or not isfinite(atr) or atr <= 0:
        output["reason"] = "WAIT DATA: ATR M5 tidak valid"
        for side in ("SELL", "BUY"):
            output[side] = {"state": "WAIT_DATA", "zones": [], "conditions": [], "score": None}
        return output
    output["reference_close"] = round(price, 2)
    output["candle_closed_at"] = m5[-1]["at"].isoformat()
    hprices = [b["c"] for b in h1]
    mprices = [b["c"] for b in m15]
    h1_bear = price < ema(hprices, 50) < ema(hprices, 200)
    h1_bull = price > ema(hprices, 50) > ema(hprices, 200)
    h_highs, h_lows = pivots(h1[-72:])
    m_highs, m_lows = pivots(m15[-48:])
    f_highs, f_lows = pivots(m5[-30:])

    # Price derives all zones from causal, CLOSED bars (not static screenshot levels).
    sell_levels = _unique(f_highs + m_highs + h_highs +
                          [ema(mprices, 20), ema(mprices, 50),
                           ema(hprices, 20), ema(hprices, 50)],
                          price, atr, True)
    buy_levels = _unique(f_lows + m_lows + h_lows +
                         [min(b["l"] for b in m15[-16:]),
                          min(b["l"] for b in h1[-8:])],
                         price, atr, False)
    # Conservative fallback: local observed extremes; no invented future price.
    if not sell_levels:
        sell_levels = _unique([max(b["h"] for b in m5[-12:])], price, atr, True)
    if not buy_levels:
        buy_levels = _unique([min(b["l"] for b in m5[-12:])], price, atr, False)

    for side, levels, trend_ok in (
        ("SELL", sell_levels, h1_bear),
        ("BUY", buy_levels, h1_bull),
    ):
        wants_sell = side == "SELL"
        series = _obj(technical.get(side))
        items = series.get("items") if isinstance(series.get("items"), list) else []
        sweep = _pass(items, "sweep")
        mss = _pass(items, "mss")
        fvg = _pass(items, "fvg")
        macro_ok = macro["direction"] == side
        macro_conflict = macro["direction"] in ("BUY", "SELL") and not macro_ok
        zones = []
        for level in levels:
            half = max(.2, min(2., .30 * atr))
            low, high = level - half, level + half
            stop = high + max(2., .85 * atr) if wants_sell else low - max(2., .85 * atr)
            entry = level
            opposing = (f_lows + m_lows + h_lows) if wants_sell else (f_highs + m_highs + h_highs)
            targets = sorted((v for v in opposing if
                              (v < entry - .15 * atr if wants_sell else v > entry + .15 * atr)),
                             reverse=wants_sell)
            targets = _unique(targets, entry, atr, not wants_sell)[:2]
            risk = stop - entry if wants_sell else entry - stop
            rr = (abs(entry - targets[0]) / risk if targets and risk > 0 else None)
            zones.append({"low": round(low, 2), "high": round(high, 2),
                          "reference_entry": round(entry, 2),
                          "structural_sl_estimate": round(stop, 2),
                          "targets": [round(v, 2) for v in targets],
                          "rr_before_costs": round(rr, 2) if rr is not None else None})
        in_zone = any(z["low"] <= price <= z["high"] for z in zones)
        # FVG event belongs to a chronological sweep/MSS sequence from the
        # existing strict technical engine, not a one-candle indicator guess.
        seq = sweep and mss and fvg
        rr_ok = any(z["rr_before_costs"] is not None and z["rr_before_costs"] >= 2
                    for z in zones)
        conditions = [
            {"name": "Makro + news/real yield context", "state": "PASS" if macro_ok else
             "FAIL" if macro_conflict else "UNKNOWN"},
            {"name": "H1 searah tren", "state": "PASS" if trend_ok else "FAIL"},
            {"name": "Harga menguji zona supply/demand", "state": "PASS" if in_zone else "FAIL"},
            {"name": "M5 sweep + MSS + FVG retest", "state": "PASS" if seq else "FAIL"},
            {"name": "RR bruto minimal 2R dari level kandidat", "state": "PASS" if rr_ok else "UNKNOWN" if not zones else "FAIL"},
        ]
        score = 20 * sum(x["state"] == "PASS" for x in conditions)
        if not zones:
            state = "WAIT_ZONE"
        elif macro_conflict:
            state = "WAIT_MACRO_CONFLICT"
        elif not trend_ok and not wants_sell:
            state = "COUNTERTREND_BUY_WATCH"
        elif in_zone and seq and rr_ok and macro_ok and trend_ok:
            state = "TRIGGER_SHADOW_VERIFY_RISK"
        else:
            state = "WATCH_REBOUND" if wants_sell else "WATCH_DIP"
        output[side] = {"state": state, "zones": zones,
                        "conditions": conditions, "score": score,
                        "countertrend": not trend_ok, "has_m5_sequence": seq}
    if macro["direction"] == "SELL" and h1_bear:
        output["preferred"] = "SELL_ON_REBOUND"
        output["reason"] = "Makro/berita tervalidasi dan tren H1 bearish searah; entry tetap menunggu M5."
    elif macro["direction"] == "BUY" and h1_bull:
        output["preferred"] = "BUY_THE_DIP"
        output["reason"] = "Makro/berita tervalidasi dan tren H1 bullish searah; entry tetap menunggu M5."
    elif macro["direction"] == "WAIT_DATA":
        output["preferred"] = "WAIT_MACRO_DATA"
        output["reason"] = "Makro/news tidak cukup segar untuk memilih arah; zona teknikal hanya watch."
    else:
        output["preferred"] = "WAIT_CONFLICT"
        output["reason"] = "Makro/news dan struktur H1 belum selaras; tidak memaksakan sinyal."
    return output
