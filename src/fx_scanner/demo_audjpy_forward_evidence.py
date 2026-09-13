from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .demo_five_core_router import _closed_rows, _ema, _true_ranges, _wilder_ewm
from .models import Bar, ensure_utc

FORWARD_EVIDENCE_CONTRACT = "AUDJPY_H4_DONCHIAN40_ADX20_FORWARD_EVIDENCE_V1"
SYMBOL = "AUDJPY"
STRATEGY_ID = "H4_DONCHIAN40_ADX20"
TIMEFRAME_SECONDS = 14_400


def _adx_series(bars: Sequence[Bar], period: int = 14) -> list[float]:
    rows = tuple(bars)
    if not rows:
        return []
    tr = _true_ranges(rows)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for previous, current in zip(rows[:-1], rows[1:]):
        up = float(current.high) - float(previous.high)
        down = float(previous.low) - float(current.low)
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr = _wilder_ewm(tr, period)
    plus = _wilder_ewm(plus_dm, period)
    minus = _wilder_ewm(minus_dm, period)
    dx: list[float] = []
    for average_range, positive, negative in zip(atr, plus, minus):
        if average_range <= 0:
            dx.append(0.0)
            continue
        positive_di = 100.0 * positive / average_range
        negative_di = 100.0 * negative / average_range
        denominator = positive_di + negative_di
        dx.append(
            0.0
            if denominator <= 0
            else 100.0 * abs(positive_di - negative_di) / denominator
        )
    return _wilder_ewm(dx, period)


def audjpy_h4_evaluation_snapshot(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    decision_at = ensure_utc(as_of)
    closed = _closed_rows(
        tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp))),
        as_of=decision_at,
        timeframe_seconds=TIMEFRAME_SECONDS,
    )
    payload: dict[str, Any] = {
        "contract": FORWARD_EVIDENCE_CONTRACT,
        "execution_influence": False,
        "symbol": SYMBOL,
        "strategy_id": STRATEGY_ID,
        "timeframe": "H4",
        "observed_at": decision_at.isoformat(),
        "closed_bars": len(closed),
        "signal_bar_at": None,
        "next_entry_at": None,
        "direction": None,
        "active": False,
        "execution_eligible": False,
        "reason": "INSUFFICIENT_H4_HISTORY",
        "signal_close": None,
        "ema50": None,
        "ema200": None,
        "adx14": None,
        "atr14": None,
        "prior_high40": None,
        "prior_low40": None,
        "shadow_sl": None,
        "shadow_tp": None,
    }
    if len(closed) < 201:
        return payload

    closes = [float(row.close) for row in closed]
    ema50 = float(_ema(closes, 50)[-1])
    ema200 = float(_ema(closes, 200)[-1])
    atr14 = float(_wilder_ewm(_true_ranges(closed), 14)[-1])
    adx14 = float(_adx_series(closed, 14)[-1])
    prior = closed[-41:-1]
    prior_high40 = max(float(row.high) for row in prior)
    prior_low40 = min(float(row.low) for row in prior)
    close = closes[-1]
    signal_bar = ensure_utc(closed[-1].timestamp)

    direction: str | None = None
    reason = "NO_BREAKOUT"
    if (
        isfinite(ema50)
        and isfinite(ema200)
        and isfinite(adx14)
        and ema50 > ema200
        and adx14 >= 20.0
        and close > prior_high40
    ):
        direction = "LONG"
        reason = "DONCHIAN40_BREAKOUT_TREND_LONG"
    elif (
        isfinite(ema50)
        and isfinite(ema200)
        and isfinite(adx14)
        and ema50 < ema200
        and adx14 >= 20.0
        and close < prior_low40
    ):
        direction = "SHORT"
        reason = "DONCHIAN40_BREAKOUT_TREND_SHORT"
    elif not isfinite(adx14) or adx14 < 20.0:
        reason = "ADX_BELOW_20"
    elif ema50 >= ema200:
        reason = "UPTREND_NO_DONCHIAN_BREAKOUT"
    else:
        reason = "DOWNTREND_NO_DONCHIAN_BREAKOUT"

    shadow_sl = None
    shadow_tp = None
    if direction is not None and isfinite(atr14) and atr14 > 0:
        sign = 1.0 if direction == "LONG" else -1.0
        shadow_sl = close - sign * 1.5 * atr14
        shadow_tp = close + sign * 3.0 * atr14

    payload.update(
        {
            "signal_bar_at": signal_bar.isoformat(),
            "next_entry_at": (
                signal_bar + timedelta(seconds=TIMEFRAME_SECONDS)
            ).isoformat(),
            "direction": direction,
            "active": direction is not None,
            "reason": reason,
            "signal_close": close,
            "ema50": ema50,
            "ema200": ema200,
            "adx14": adx14,
            "atr14": atr14,
            "prior_high40": prior_high40,
            "prior_low40": prior_low40,
            "shadow_sl": shadow_sl,
            "shadow_tp": shadow_tp,
        }
    )
    return payload


def evaluation_key(snapshot: dict[str, Any]) -> str | None:
    signal_bar = snapshot.get("signal_bar_at")
    if not signal_bar or int(snapshot.get("closed_bars") or 0) < 201:
        return None
    direction = str(snapshot.get("direction") or "NONE")
    reason = str(snapshot.get("reason") or "UNKNOWN")
    return f"{signal_bar}|{direction}|{reason}"
