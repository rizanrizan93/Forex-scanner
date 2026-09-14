from __future__ import annotations

"""Forward-only shadow evaluators for the selected EURAUD and GBPAUD strategies.

The strategy identities and parameters are frozen from the completed public-history and
cTrader broker cross-feed studies.  This module evaluates only completed D1 bars and has
no broker order path, no execution influence, and no promotion authority.
"""

from datetime import datetime
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_five_core_router import _closed_rows, _ema, _next_bar_open, _true_ranges, _wilder_ewm
from .models import Bar, ensure_utc

FORWARD_EVIDENCE_CONTRACT = "EURAUD_GBPAUD_FORWARD_EVIDENCE_V1"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False
EXECUTION_ELIGIBLE = False

EURAUD_STRATEGY_ID = "D1_DONCHIAN55_VOLFILTER_CHANDELIER35"
GBPAUD_STRATEGY_ID = "D1_COMPONENT_RET63_OPPOSITE_CHANDELIER3"

PAIR_SPECS: dict[str, dict[str, Any]] = {
    "EURAUD": {
        "strategy_id": EURAUD_STRATEGY_ID,
        "timeframe": "D1",
        "initial_stop_atr": 2.0,
        "trail_atr": 3.5,
        "max_hold_bars": 120,
    },
    "GBPAUD": {
        "strategy_id": GBPAUD_STRATEGY_ID,
        "timeframe": "D1",
        "initial_stop_atr": 2.0,
        "trail_atr": 3.0,
        "max_hold_bars": 120,
        "component_period": 63,
    },
}


def _base_snapshot(symbol: str, *, as_of: datetime) -> dict[str, Any]:
    spec = PAIR_SPECS[symbol]
    return {
        "contract": FORWARD_EVIDENCE_CONTRACT,
        "environment": "DEMO",
        "execution_eligible": EXECUTION_ELIGIBLE,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "symbol": symbol,
        "strategy_id": spec["strategy_id"],
        "timeframe": "D1",
        "observed_at": ensure_utc(as_of).isoformat(),
        "closed_bars": 0,
        "signal_bar_at": None,
        "next_entry_at": None,
        "direction": None,
        "active": False,
        "reason": "NOT_EVALUATED",
        "signal_close": None,
        "atr14": None,
        "shadow_initial_stop": None,
        "trail_atr": spec["trail_atr"],
        "max_hold_bars": spec["max_hold_bars"],
        "geometry_basis": "SIGNAL_CLOSE_PROXY_PENDING_NEXT_D1_OPEN",
    }


def _ordered_bundle(symbol: str, bars: Sequence[Bar]) -> tuple[Bar, ...] | None:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != symbol or row.timeframe.upper() != "D1" for row in rows):
        return None
    return rows


def _closed_bundle(symbol: str, bars: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...] | None:
    rows = _ordered_bundle(symbol, bars)
    if rows is None:
        return None
    return _closed_rows(rows, as_of=as_of, timeframe_seconds=86_400)


def _initial_stop(close: float, atr14: float, direction: str | None, stop_atr: float) -> float | None:
    if direction not in {"LONG", "SHORT"} or not isfinite(atr14) or atr14 <= 0:
        return None
    sign = 1.0 if direction == "LONG" else -1.0
    return close - sign * stop_atr * atr14


def evaluate_euraud(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    """Evaluate the frozen EURAUD D1 Donchian-55 volatility-filter strategy."""
    snapshot = _base_snapshot("EURAUD", as_of=as_of)
    rows = _ordered_bundle("EURAUD", bars)
    if rows is None:
        snapshot["reason"] = "INVALID_EURAUD_D1_BUNDLE"
        return snapshot
    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=86_400)
    snapshot["closed_bars"] = len(closed)
    if len(closed) < 200:
        snapshot["reason"] = "INSUFFICIENT_EURAUD_D1_HISTORY"
        return snapshot

    closes = [float(row.close) for row in closed]
    ema50 = float(_ema(closes, 50)[-1])
    ema200 = float(_ema(closes, 200)[-1])
    atrs = _wilder_ewm(_true_ranges(closed), 14)
    atr14 = float(atrs[-1])
    atr_pct_window = [
        float(a) / float(row.close)
        for a, row in zip(atrs[-126:], closed[-126:])
        if float(row.close) > 0 and isfinite(float(a))
    ]
    if len(atr_pct_window) < 126 or not isfinite(atr14) or atr14 <= 0:
        snapshot["reason"] = "INVALID_EURAUD_VOLATILITY_HISTORY"
        return snapshot
    atr_pct = atr14 / closes[-1]
    atr_pct_med126 = float(median(atr_pct_window))
    prior55 = closed[-56:-1]
    if len(prior55) != 55:
        snapshot["reason"] = "INSUFFICIENT_EURAUD_DONCHIAN55_HISTORY"
        return snapshot
    prior_high55 = max(float(row.high) for row in prior55)
    prior_low55 = min(float(row.low) for row in prior55)
    close = closes[-1]
    vol_ok = atr_pct >= atr_pct_med126

    direction: str | None = None
    reason = "NO_D1_DONCHIAN55_VOLFILTER_BREAKOUT"
    if ema50 > ema200 and vol_ok and close > prior_high55:
        direction = "LONG"
        reason = "D1_DONCHIAN55_VOLFILTER_LONG"
    elif ema50 < ema200 and vol_ok and close < prior_low55:
        direction = "SHORT"
        reason = "D1_DONCHIAN55_VOLFILTER_SHORT"
    elif not vol_ok:
        reason = "D1_VOLATILITY_FILTER_NOT_MET"
    elif ema50 >= ema200:
        reason = "D1_UPTREND_NO_DONCHIAN55_BREAKOUT"
    else:
        reason = "D1_DOWNTREND_NO_DONCHIAN55_BREAKOUT"

    signal_bar = closed[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry = _next_bar_open(rows, signal_bar, timeframe_seconds=86_400)
    snapshot.update(
        {
            "signal_bar_at": signal_at.isoformat(),
            "next_entry_at": ensure_utc(next_entry).isoformat(),
            "direction": direction,
            "active": direction is not None,
            "reason": reason,
            "signal_close": close,
            "ema50": ema50,
            "ema200": ema200,
            "atr14": atr14,
            "atr_pct": atr_pct,
            "atr_pct_med126": atr_pct_med126,
            "prior_high55": prior_high55,
            "prior_low55": prior_low55,
            "shadow_initial_stop": _initial_stop(
                close, atr14, direction, float(PAIR_SPECS["EURAUD"]["initial_stop_atr"])
            ),
        }
    )
    return snapshot


def _date_map(rows: Sequence[Bar]) -> dict[str, Bar]:
    return {ensure_utc(row.timestamp).date().isoformat(): row for row in rows}


def evaluate_gbpaud(
    bundles: Mapping[str, Sequence[Bar]],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    """Evaluate the frozen GBPAUD D1 63-session component-relative-momentum strategy."""
    snapshot = _base_snapshot("GBPAUD", as_of=as_of)
    required_symbols = ("GBPAUD", "GBPUSD", "AUDUSD")
    closed_by_symbol: dict[str, tuple[Bar, ...]] = {}
    for symbol in required_symbols:
        bars = bundles.get(symbol)
        if bars is None:
            snapshot["reason"] = f"MISSING_{symbol}_D1_BUNDLE"
            return snapshot
        closed = _closed_bundle(symbol, bars, as_of=as_of)
        if closed is None:
            snapshot["reason"] = f"INVALID_{symbol}_D1_BUNDLE"
            return snapshot
        closed_by_symbol[symbol] = closed

    gbp_map = _date_map(closed_by_symbol["GBPUSD"])
    aud_map = _date_map(closed_by_symbol["AUDUSD"])
    cross: list[Bar] = []
    gbp: list[Bar] = []
    aud: list[Bar] = []
    for row in closed_by_symbol["GBPAUD"]:
        key = ensure_utc(row.timestamp).date().isoformat()
        gbp_row = gbp_map.get(key)
        aud_row = aud_map.get(key)
        if gbp_row is None or aud_row is None:
            continue
        cross.append(row)
        gbp.append(gbp_row)
        aud.append(aud_row)

    snapshot["closed_bars"] = len(cross)
    if len(cross) < 200:
        snapshot["reason"] = "INSUFFICIENT_GBPAUD_COMPONENT_HISTORY"
        return snapshot

    cross_closes = [float(row.close) for row in cross]
    gbp_closes = [float(row.close) for row in gbp]
    aud_closes = [float(row.close) for row in aud]
    ema200 = float(_ema(cross_closes, 200)[-1])
    atr14 = float(_wilder_ewm(_true_ranges(cross), 14)[-1])
    period = int(PAIR_SPECS["GBPAUD"]["component_period"])
    if len(cross) <= period:
        snapshot["reason"] = "INSUFFICIENT_GBPAUD_RET63_HISTORY"
        return snapshot
    gbp_ret63 = gbp_closes[-1] / gbp_closes[-1 - period] - 1.0
    aud_ret63 = aud_closes[-1] / aud_closes[-1 - period] - 1.0
    close = cross_closes[-1]

    direction: str | None = None
    reason = "D1_COMPONENT_RET63_NOT_OPPOSITE"
    if close > ema200 and gbp_ret63 > 0 and aud_ret63 < 0:
        direction = "LONG"
        reason = "D1_COMPONENT_RET63_OPPOSITE_LONG"
    elif close < ema200 and gbp_ret63 < 0 and aud_ret63 > 0:
        direction = "SHORT"
        reason = "D1_COMPONENT_RET63_OPPOSITE_SHORT"
    elif close > ema200:
        reason = "GBPAUD_UPTREND_COMPONENTS_NOT_OPPOSITE"
    elif close < ema200:
        reason = "GBPAUD_DOWNTREND_COMPONENTS_NOT_OPPOSITE"

    signal_bar = cross[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    # Use the GBPAUD bundle for the broker's next D1 bar/open convention.
    next_entry = _next_bar_open(closed_by_symbol["GBPAUD"], signal_bar, timeframe_seconds=86_400)
    snapshot.update(
        {
            "signal_bar_at": signal_at.isoformat(),
            "next_entry_at": ensure_utc(next_entry).isoformat(),
            "direction": direction,
            "active": direction is not None,
            "reason": reason,
            "signal_close": close,
            "ema200": ema200,
            "atr14": atr14,
            "gbpusd_ret63": gbp_ret63,
            "audusd_ret63": aud_ret63,
            "aligned_component_bars": len(cross),
            "shadow_initial_stop": _initial_stop(
                close, atr14, direction, float(PAIR_SPECS["GBPAUD"]["initial_stop_atr"])
            ),
        }
    )
    return snapshot


def evaluation_key(snapshot: Mapping[str, Any]) -> str | None:
    signal_bar_at = snapshot.get("signal_bar_at")
    if not signal_bar_at:
        return None
    return "|".join(
        (
            str(snapshot.get("symbol") or ""),
            str(snapshot.get("strategy_id") or ""),
            str(signal_bar_at),
            str(snapshot.get("direction") or "NONE"),
            str(snapshot.get("reason") or "UNKNOWN"),
        )
    )
