from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from adaptive_router_public_backtest import indicators, median_prior

COST_R = 0.05
MAX_HOLD = 10
PARAMS = {
    "EXPANSION_BREAKOUT": (2.2, 1.10),
    "TREND_PULLBACK": (2.0, 1.20),
    "LIQUIDITY_SWEEP": (1.8, None),
    "MEAN_REVERSION": (1.4, 1.00),
}


def regime_at(rows: list[dict[str, Any]], ind: dict[str, list[Any]], i: int) -> str:
    atr = ind["atr"][i]
    adx = ind["adx"][i]
    if not atr or adx is None:
        return "UNKNOWN"
    e20, e50, e200 = ind["e20"][i], ind["e50"][i], ind["e200"][i]
    med_atr = median_prior(ind["atr"], i, 50) or atr
    sep = abs(e20 - e50) / atr
    expansion = ind["tr"][i] >= 1.35 * atr or atr >= 1.18 * med_atr
    directional = (e20 > e50 > e200) or (e20 < e50 < e200)
    if expansion and adx >= 20:
        return "EXPANSION"
    if directional and adx >= 22 and sep >= 0.45:
        return "TREND"
    if adx <= 18 and sep < 0.55:
        return "RANGE"
    return "TRANSITION"


def candidate_signals(rows: list[dict[str, Any]], ind: dict[str, list[Any]], i: int) -> list[tuple[str, str, str]]:
    if i < 220 or i + 1 >= len(rows):
        return []
    r = rows[i]
    atr, adx, rsi = ind["atr"][i], ind["adx"][i], ind["rsi"][i]
    sma20, std20 = ind["sma20"][i], ind["std20"][i]
    if not atr or adx is None or rsi is None or sma20 is None or std20 is None:
        return []
    e20, e50, e200 = ind["e20"][i], ind["e50"][i], ind["e200"][i]
    prev20_hi = max(x["high"] for x in rows[i-20:i])
    prev20_lo = min(x["low"] for x in rows[i-20:i])
    rng = max(r["high"] - r["low"], 1e-12)
    body = abs(r["close"] - r["open"])
    close_loc = (r["close"] - r["low"]) / rng
    regime = regime_at(rows, ind, i)
    out: list[tuple[str, str, str]] = []

    if regime == "EXPANSION" and body >= 0.50 * atr:
        if r["close"] > prev20_hi + 0.03 * atr and e20 > e50:
            out.append(("EXPANSION_BREAKOUT", "LONG", regime))
        if r["close"] < prev20_lo - 0.03 * atr and e20 < e50:
            out.append(("EXPANSION_BREAKOUT", "SHORT", regime))

    if regime == "TREND":
        if e20 > e50 > e200 and r["low"] <= e20 + 0.20 * atr and r["close"] > e20 and r["close"] > r["open"] and body >= 0.25 * atr:
            out.append(("TREND_PULLBACK", "LONG", regime))
        if e20 < e50 < e200 and r["high"] >= e20 - 0.20 * atr and r["close"] < e20 and r["close"] < r["open"] and body >= 0.25 * atr:
            out.append(("TREND_PULLBACK", "SHORT", regime))

    if regime in {"RANGE", "TRANSITION"} and adx < 28:
        if r["low"] < prev20_lo - 0.05 * atr and r["close"] > prev20_lo and r["close"] > r["open"] and close_loc >= 0.62:
            out.append(("LIQUIDITY_SWEEP", "LONG", regime))
        if r["high"] > prev20_hi + 0.05 * atr and r["close"] < prev20_hi and r["close"] < r["open"] and close_loc <= 0.38:
            out.append(("LIQUIDITY_SWEEP", "SHORT", regime))

    if regime == "RANGE":
        lower, upper = sma20 - 1.7 * std20, sma20 + 1.7 * std20
        if r["low"] < lower and r["close"] > lower and r["close"] > r["open"] and rsi <= 42:
            out.append(("MEAN_REVERSION", "LONG", regime))
        if r["high"] > upper and r["close"] < upper and r["close"] < r["open"] and rsi >= 58:
            out.append(("MEAN_REVERSION", "SHORT", regime))
    return out


def simulate_candidate(symbol: str, rows: list[dict[str, Any]], ind: dict[str, list[Any]], i: int, setup: str, side: str, regime: str) -> dict[str, Any] | None:
    entry_i = i + 1
    entry = rows[entry_i]["open"]
    atr = ind["atr"][i]
    if not atr or atr <= 0:
        return None
    rr, stop_mult = PARAMS[setup]
    if setup == "LIQUIDITY_SWEEP":
        stop = rows[i]["low"] - 0.15 * atr if side == "LONG" else rows[i]["high"] + 0.15 * atr
        risk = entry - stop if side == "LONG" else stop - entry
    else:
        risk = float(stop_mult) * atr
        stop = entry - risk if side == "LONG" else entry + risk
    if risk <= 0 or risk / entry > 0.15:
        return None
    target = entry + rr * risk if side == "LONG" else entry - rr * risk
    exit_i = min(entry_i + MAX_HOLD, len(rows) - 1)
    gross_r = None
    reason = "TIME"
    for j in range(entry_i, exit_i + 1):
        b = rows[j]
        if side == "LONG":
            sl, tp = b["low"] <= stop, b["high"] >= target
        else:
            sl, tp = b["high"] >= stop, b["low"] <= target
        if sl and tp:
            gross_r, exit_i, reason = -1.0, j, "SL_AMBIGUOUS_FIRST"; break
        if sl:
            gross_r, exit_i, reason = -1.0, j, "SL"; break
        if tp:
            gross_r, exit_i, reason = rr, j, "TP"; break
    if gross_r is None:
        px = rows[exit_i]["close"]
        gross_r = (px - entry) / risk if side == "LONG" else (entry - px) / risk
        gross_r = max(-1.5, min(rr, gross_r))
    return {
        "symbol": symbol, "timeframe": "D1", "setup": setup, "regime": regime, "side": side,
        "signal_at": rows[i]["dt"].isoformat(), "entry_at": rows[entry_i]["dt"].isoformat(),
        "exit_at": rows[exit_i]["dt"].isoformat(), "gross_r": round(gross_r, 6),
        "net_r": round(gross_r - COST_R, 6), "cost_r": COST_R, "exit_reason": reason,
    }


def generate_shadow(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ind = indicators(rows)
    out: list[dict[str, Any]] = []
    blocked_until: dict[str, int] = defaultdict(lambda: -1)
    for i in range(220, len(rows) - 2):
        for setup, side, regime in candidate_signals(rows, ind, i):
            if i <= blocked_until[setup]:
                continue
            t = simulate_candidate(symbol, rows, ind, i, setup, side, regime)
            if not t:
                continue
            out.append(t)
            exit_dt = datetime.fromisoformat(t["exit_at"])
            j = i + 1
            while j < len(rows) and rows[j]["dt"] <= exit_dt:
                j += 1
            blocked_until[setup] = j - 1
    return out
