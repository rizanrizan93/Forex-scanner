"""Stable closed-H1 context beside *unaltered* Frozen V1 / SMC research triggers.

This is a descriptive watch-only trend context: EMA5/EMA8 H1 alignment,
two successive CLOSED H1 confirmations, rising/falling slow EMA and a
volatility band. It is NOT a Frozen V1 entry gate or a backtested signal.
"""
from __future__ import annotations

from datetime import timedelta
from math import isfinite

from .frozen_v1_directional_score import _rows as frozen_rows
from .xau_decision_checklist_v1 import closed_bars


def _ema(values, span):
    if len(values) < span:
        return None
    value = sum(values[:span]) / span
    alpha = 2. / (span + 1)
    for x in values[span:]:
        value += alpha * (x - value)
    return value


def _compute(rows, *, source):
    default = {
        "direction": "WAIT DATA", "source": source, "last_h1_close": None,
        "method": "EMA5/EMA8 + 2 H1 closed + band 0.10 TR8",
        "native_signal": False, "order_enabled": False,
        "details": "Memerlukan >=11 H1 tertutup dengan dua H1 terakhir berurutan.",
    }
    if not rows or len(rows) < 11:
        return default
    last, previous = rows[-1], rows[-2]
    # Rows may come from either normalized transport; no forming candles.
    current_at = last["at"]
    previous_at = previous["at"]
    if current_at - previous_at != timedelta(hours=1):
        return {**default, "details": "Gap sesi H1; tunggu dua H1 berturut-turut."}
    closes = [x["c"] for x in rows]
    highs = [x["h"] for x in rows]
    lows = [x["l"] for x in rows]
    if any(not isfinite(float(x)) for x in closes + highs + lows):
        return default
    fast = _ema(closes, 5)
    slow = _ema(closes, 8)
    fast_prev = _ema(closes[:-1], 5)
    slow_prev = _ema(closes[:-1], 8)
    tr = [
        max(rows[i]["h"] - rows[i]["l"],
            abs(rows[i]["h"] - rows[i-1]["c"]),
            abs(rows[i]["l"] - rows[i-1]["c"]))
        for i in range(len(rows) - 8, len(rows))
    ]
    volatility = sum(tr) / len(tr)
    if volatility <= 0:
        return {**default, "details": "Rentang harga H1 tidak valid."}
    band = .10 * volatility
    up = (
        fast > slow + band and fast_prev > slow_prev + band
        and closes[-1] > slow + band and closes[-2] > slow_prev + band
        and slow > slow_prev
    )
    down = (
        fast < slow - band and fast_prev < slow_prev - band
        and closes[-1] < slow - band and closes[-2] < slow_prev - band
        and slow < slow_prev
    )
    direction = "BUY" if up else "SELL" if down else "NETRAL"
    return {
        **default, "direction": direction,
        "last_h1_close": current_at.isoformat(),
        "details": (
            "BUY/SELL hanya jika EMA5/EMA8, dua close H1, slope EMA8 dan "
            "buffer volatilitas selaras; selain itu NETRAL."
        ),
        "ema5": round(fast, 5), "ema8": round(slow, 5),
        "tr8": round(volatility, 5), "buffer": round(band, 5),
    }


def from_v1_market(market, now):
    rows = frozen_rows(market, "XAUUSD", "H1", now, 11)
    if rows:
        # V1 rows are timestamped at the bar's OPEN, unlike research closed bars.
        rows = [{**r, "at": r["at"] + timedelta(hours=1)} for r in rows]
    return _compute(rows, source="V1 LIVE 7903 H1")


def from_research_candles(candles, now):
    rows, reason = closed_bars(candles, "H1", now)
    if reason:
        return {**_compute(None, source="Research LIVE 7903 H1"), "details": reason}
    return _compute(rows, source="Research LIVE 7903 H1")


def explain_vs_fast(anchor, fast_side):
    regime = anchor.get("direction", "WAIT DATA")
    if regime == "WAIT DATA":
        return "WAIT DATA · regime H1 belum tervalidasi; trigger cepat tidak menetapkan tren."
    if regime == "NETRAL":
        return "RANGE/TRANSISI H1 · trigger cepat tidak cukup untuk mengubah tren."
    if fast_side not in ("BUY", "SELL"):
        return "Regime H1 " + regime + " · belum ada trigger cepat valid."
    if fast_side == regime:
        return "SEARAH H1 · trigger " + fast_side + " sesuai konteks; bukan izin order."
    return (
        "KONTRA H1 · trigger " + fast_side
        + " berlawanan regime " + regime
        + "; berpotensi pullback atau reversal yang BELUM terkonfirmasi H1."
    )
