from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Sequence

from .demo_five_core_router import (
    _closed_rows,
    _ema,
    _linear_quantile,
    _next_bar_open,
    _true_ranges,
    _wilder_ewm,
)
from .models import Bar, ensure_utc

XAU_SOFT_STRATEGY_ID = "D1_TSMOM_60_EMA200_SOFT_V2"
USDJPY_SOFT_STRATEGY_ID = "H4_COMPRESSION_BREAKOUT_EMA200_SOFT_V2"
XAU_ENTRY_WINDOW_SECONDS = 30 * 60
USDJPY_ENTRY_WINDOW_SECONDS = 30 * 60
ALIGNED_SCORE = 60.0
COUNTERTREND_SCORE = 55.0


@dataclass(frozen=True, slots=True)
class SoftEmaCandidate:
    symbol: str
    strategy_id: str
    direction: str | None
    active: bool
    signal_bar_at: datetime | None
    next_entry_at: datetime | None
    atr: float | None
    ema_context: str | None
    score: float | None
    reason: str


def _context_score(aligned: bool) -> tuple[str, float]:
    return ("EMA_ALIGNED", ALIGNED_SCORE) if aligned else ("EMA_COUNTERTREND", COUNTERTREND_SCORE)


def evaluate_xau_soft_ema(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> SoftEmaCandidate:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != "XAUUSD" or row.timeframe != "D1" for row in rows):
        return SoftEmaCandidate("XAUUSD", XAU_SOFT_STRATEGY_ID, None, False, None, None, None, None, None, "INVALID_D1_BUNDLE")

    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=86400)
    if len(closed) < 200:
        return SoftEmaCandidate("XAUUSD", XAU_SOFT_STRATEGY_ID, None, False, None, None, None, None, None, "INSUFFICIENT_D1_HISTORY")

    closes = [float(row.close) for row in closed]
    if len(closes) < 61:
        return SoftEmaCandidate("XAUUSD", XAU_SOFT_STRATEGY_ID, None, False, None, None, None, None, None, "INSUFFICIENT_RET60_HISTORY")

    ret60 = closes[-1] / closes[-61] - 1.0
    direction = "LONG" if ret60 > 0 else "SHORT" if ret60 < 0 else None
    signal_bar = closed[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry = _next_bar_open(rows, signal_bar)
    atr14 = _wilder_ewm(_true_ranges(closed), 14)[-1]

    if direction is None:
        return SoftEmaCandidate("XAUUSD", XAU_SOFT_STRATEGY_ID, None, False, signal_at, next_entry, atr14, None, None, "D1_MOMENTUM_FLAT")

    ema200 = _ema(closes, 200)[-1]
    aligned = (direction == "LONG" and closes[-1] > ema200) or (direction == "SHORT" and closes[-1] < ema200)
    ema_context, score = _context_score(aligned)
    now = ensure_utc(as_of)
    active = next_entry <= now <= next_entry + timedelta(seconds=XAU_ENTRY_WINDOW_SECONDS)
    return SoftEmaCandidate(
        "XAUUSD",
        XAU_SOFT_STRATEGY_ID,
        direction,
        active,
        signal_at,
        next_entry,
        atr14,
        ema_context,
        score,
        f"{'ENTRY_WINDOW_ACTIVE' if active else 'WAIT_NEXT_D1_OPEN'}_{ema_context}",
    )


def evaluate_usdjpy_soft_ema(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> SoftEmaCandidate:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != "USDJPY" or row.timeframe != "H4" for row in rows):
        return SoftEmaCandidate("USDJPY", USDJPY_SOFT_STRATEGY_ID, None, False, None, None, None, None, None, "INVALID_H4_BUNDLE")

    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=14400)
    if len(closed) < 201:
        return SoftEmaCandidate("USDJPY", USDJPY_SOFT_STRATEGY_ID, None, False, None, None, None, None, None, "INSUFFICIENT_H4_HISTORY")

    closes = [float(row.close) for row in closed]
    atrs = _wilder_ewm(_true_ranges(closed), 14)
    atr_pct = [a / c if c > 0 else float("nan") for a, c in zip(atrs, closes)]
    i = len(closed) - 1
    q35 = _linear_quantile(atr_pct[i - 100:i], 0.35)
    compressed = isfinite(atr_pct[i - 1]) and atr_pct[i - 1] < q35
    prior20 = closed[i - 20:i]
    prior_high = max(float(row.high) for row in prior20)
    prior_low = min(float(row.low) for row in prior20)
    close = closes[-1]

    direction = None
    if compressed and close > prior_high:
        direction = "LONG"
    elif compressed and close < prior_low:
        direction = "SHORT"

    signal_bar = closed[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry = _next_bar_open(rows, signal_bar)
    if direction is None:
        return SoftEmaCandidate("USDJPY", USDJPY_SOFT_STRATEGY_ID, None, False, signal_at, next_entry, atrs[-1], None, None, "NO_H4_COMPRESSION_BREAKOUT")

    ema50 = _ema(closes, 50)[-1]
    ema200 = _ema(closes, 200)[-1]
    aligned = (direction == "LONG" and ema50 > ema200) or (direction == "SHORT" and ema50 < ema200)
    ema_context, score = _context_score(aligned)
    now = ensure_utc(as_of)
    active = next_entry <= now <= next_entry + timedelta(seconds=USDJPY_ENTRY_WINDOW_SECONDS)
    return SoftEmaCandidate(
        "USDJPY",
        USDJPY_SOFT_STRATEGY_ID,
        direction,
        active,
        signal_at,
        next_entry,
        atrs[-1],
        ema_context,
        score,
        f"{'ENTRY_WINDOW_ACTIVE' if active else 'WAIT_NEXT_H4_OPEN'}_{ema_context}",
    )


def candidate_payload(candidate: SoftEmaCandidate) -> dict[str, object]:
    return {
        "symbol": candidate.symbol,
        "strategy_id": candidate.strategy_id,
        "direction": candidate.direction,
        "active": candidate.active,
        "signal_bar_at": None if candidate.signal_bar_at is None else ensure_utc(candidate.signal_bar_at).isoformat(),
        "next_entry_at": None if candidate.next_entry_at is None else ensure_utc(candidate.next_entry_at).isoformat(),
        "atr": candidate.atr,
        "ema_context": candidate.ema_context,
        "score": candidate.score,
        "reason": candidate.reason,
        "execution_influence": False,
    }
