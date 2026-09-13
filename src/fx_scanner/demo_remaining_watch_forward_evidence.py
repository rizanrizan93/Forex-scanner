from __future__ import annotations

"""Non-authoritative forward evaluators for broker-supported remaining WATCH pairs.

These evaluators deliberately have no order path. They reproduce the frozen public-history
signal conditions on closed cTrader bars and emit shadow evidence only.
"""

from datetime import datetime
from math import isfinite
from typing import Any, Sequence

from .demo_five_core_router import (
    _adx14,
    _closed_rows,
    _ema,
    _next_bar_open,
    _true_ranges,
    _wilder_ewm,
)
from .models import Bar, ensure_utc

FORWARD_EVIDENCE_CONTRACT = "REMAINING_WATCH_FORWARD_EVIDENCE_V1"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False

PAIR_SPECS: dict[str, dict[str, Any]] = {
    "GBPJPY": {
        "strategy_id": "D1_TSMOM_60_200",
        "timeframe": "D1",
        "timeframe_seconds": 86_400,
        "momentum_period": 60,
        "stop_atr": 2.0,
        "target_atr": 4.0,
        "max_hold_bars": 30,
    },
    "CADJPY": {
        "strategy_id": "D1_TSMOM_120_200",
        "timeframe": "D1",
        "timeframe_seconds": 86_400,
        "momentum_period": 120,
        "stop_atr": 2.0,
        "target_atr": 4.0,
        "max_hold_bars": 30,
    },
    "USDCAD": {
        "strategy_id": "H4_DONCHIAN40_ADX20",
        "timeframe": "H4",
        "timeframe_seconds": 14_400,
        "stop_atr": 1.5,
        "target_atr": 3.0,
        "max_hold_bars": 24,
    },
}


def _base_snapshot(symbol: str, spec: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
    return {
        "contract": FORWARD_EVIDENCE_CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "execution_eligible": False,
        "symbol": symbol,
        "strategy_id": spec["strategy_id"],
        "timeframe": spec["timeframe"],
        "observed_at": ensure_utc(as_of).isoformat(),
        "closed_bars": 0,
        "signal_bar_at": None,
        "next_entry_at": None,
        "direction": None,
        "active": False,
        "reason": "NOT_EVALUATED",
        "signal_close": None,
        "atr14": None,
        "shadow_sl": None,
        "shadow_tp": None,
        "geometry_basis": "SIGNAL_CLOSE_PROXY_PENDING_NEXT_OPEN",
        "stop_atr": spec["stop_atr"],
        "target_atr": spec["target_atr"],
        "max_hold_bars": spec["max_hold_bars"],
    }


def _validate_bundle(symbol: str, timeframe: str, bars: Sequence[Bar]) -> tuple[Bar, ...] | None:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != symbol or row.timeframe.upper() != timeframe for row in rows):
        return None
    return rows


def _apply_shadow_geometry(snapshot: dict[str, Any], *, close: float, atr14: float, direction: str | None) -> None:
    if direction is None or not isfinite(atr14) or atr14 <= 0:
        return
    sign = 1.0 if direction == "LONG" else -1.0
    snapshot["shadow_sl"] = close - sign * float(snapshot["stop_atr"]) * atr14
    snapshot["shadow_tp"] = close + sign * float(snapshot["target_atr"]) * atr14


def _evaluate_d1_tsmom(
    symbol: str,
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    period: int,
) -> dict[str, Any]:
    spec = PAIR_SPECS[symbol]
    snapshot = _base_snapshot(symbol, spec, as_of=as_of)
    rows = _validate_bundle(symbol, "D1", bars)
    if rows is None:
        snapshot["reason"] = "INVALID_D1_BUNDLE"
        return snapshot

    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=86_400)
    snapshot["closed_bars"] = len(closed)
    required = max(200, period + 1)
    if len(closed) < required:
        snapshot["reason"] = "INSUFFICIENT_D1_HISTORY"
        return snapshot

    closes = [float(row.close) for row in closed]
    ema200 = float(_ema(closes, 200)[-1])
    ret_n = closes[-1] / closes[-1 - period] - 1.0
    atr14 = float(_wilder_ewm(_true_ranges(closed), 14)[-1])
    close = closes[-1]
    direction: str | None = None
    if close > ema200 and ret_n > 0:
        direction = "LONG"
    elif close < ema200 and ret_n < 0:
        direction = "SHORT"

    signal_bar = closed[-1]
    snapshot.update(
        {
            "signal_bar_at": ensure_utc(signal_bar.timestamp).isoformat(),
            "next_entry_at": _next_bar_open(rows, signal_bar, timeframe_seconds=86_400).isoformat(),
            "direction": direction,
            "active": direction is not None,
            "reason": "D1_TREND_MOMENTUM_ALIGNED" if direction else "D1_TREND_MOMENTUM_NOT_ALIGNED",
            "signal_close": close,
            "ema200": ema200,
            f"ret{period}": ret_n,
            "atr14": atr14,
        }
    )
    _apply_shadow_geometry(snapshot, close=close, atr14=atr14, direction=direction)
    return snapshot


def _evaluate_h4_donchian_adx(symbol: str, bars: Sequence[Bar], *, as_of: datetime) -> dict[str, Any]:
    spec = PAIR_SPECS[symbol]
    snapshot = _base_snapshot(symbol, spec, as_of=as_of)
    rows = _validate_bundle(symbol, "H4", bars)
    if rows is None:
        snapshot["reason"] = "INVALID_H4_BUNDLE"
        return snapshot

    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=14_400)
    snapshot["closed_bars"] = len(closed)
    if len(closed) < 201:
        snapshot["reason"] = "INSUFFICIENT_H4_HISTORY"
        return snapshot

    closes = [float(row.close) for row in closed]
    ema50 = float(_ema(closes, 50)[-1])
    ema200 = float(_ema(closes, 200)[-1])
    adx14 = float(_adx14(closed))
    atr14 = float(_wilder_ewm(_true_ranges(closed), 14)[-1])
    prior40 = closed[-41:-1]
    prior_high40 = max(float(row.high) for row in prior40)
    prior_low40 = min(float(row.low) for row in prior40)
    close = closes[-1]

    direction: str | None = None
    reason = "NO_DONCHIAN40_BREAKOUT"
    if ema50 > ema200 and adx14 >= 20.0 and close > prior_high40:
        direction = "LONG"
        reason = "DONCHIAN40_BREAKOUT_TREND_LONG"
    elif ema50 < ema200 and adx14 >= 20.0 and close < prior_low40:
        direction = "SHORT"
        reason = "DONCHIAN40_BREAKOUT_TREND_SHORT"
    elif adx14 < 20.0:
        reason = "ADX_BELOW_20"
    elif ema50 >= ema200:
        reason = "UPTREND_NO_DONCHIAN_BREAKOUT"
    else:
        reason = "DOWNTREND_NO_DONCHIAN_BREAKOUT"

    signal_bar = closed[-1]
    snapshot.update(
        {
            "signal_bar_at": ensure_utc(signal_bar.timestamp).isoformat(),
            "next_entry_at": _next_bar_open(rows, signal_bar, timeframe_seconds=14_400).isoformat(),
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
        }
    )
    _apply_shadow_geometry(snapshot, close=close, atr14=atr14, direction=direction)
    return snapshot


def evaluate_remaining_watch_pair(symbol: str, bars: Sequence[Bar], *, as_of: datetime) -> dict[str, Any]:
    normalized = str(symbol).upper().strip()
    spec = PAIR_SPECS.get(normalized)
    if spec is None:
        raise ValueError(f"unsupported remaining WATCH symbol: {symbol}")
    if spec["timeframe"] == "D1":
        return _evaluate_d1_tsmom(
            normalized,
            bars,
            as_of=as_of,
            period=int(spec["momentum_period"]),
        )
    return _evaluate_h4_donchian_adx(normalized, bars, as_of=as_of)


def evaluation_key(snapshot: dict[str, Any]) -> str | None:
    signal_bar = snapshot.get("signal_bar_at")
    if not signal_bar:
        return None
    symbol = str(snapshot.get("symbol") or "")
    strategy = str(snapshot.get("strategy_id") or "")
    direction = str(snapshot.get("direction") or "NONE")
    reason = str(snapshot.get("reason") or "UNKNOWN")
    return f"{symbol}|{strategy}|{signal_bar}|{direction}|{reason}"
