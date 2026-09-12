from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Sequence

from .demo_five_core_router import (
    PAIR_STRATEGY_IDS,
    FiveCoreSignal,
    _closed_rows,
    _ema,
    _true_ranges,
    _wilder_ewm,
    evaluate_xau_d1_tsmom_60_200,
)
from .models import Bar, ensure_utc

XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC = 0
FORWARD_EVIDENCE_CONTRACT = "XAU_D1_TSMOM_FORWARD_EVIDENCE_V1"


def _iso(value: datetime | None) -> str | None:
    return None if value is None else ensure_utc(value).isoformat()


def bar_boundary_snapshot(
    bars: Sequence[Bar],
    *,
    expected_open_seconds_utc: int | None = None,
) -> dict[str, Any]:
    ordered = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    timestamps = [ensure_utc(row.timestamp) for row in ordered]
    open_seconds = sorted(
        {
            ts.hour * 3600 + ts.minute * 60 + ts.second
            for ts in timestamps
        }
    )
    matches_expected = None
    if expected_open_seconds_utc is not None:
        matches_expected = bool(open_seconds) and open_seconds == [int(expected_open_seconds_utc)]
    return {
        "bars": len(ordered),
        "first_bar_at": _iso(timestamps[0]) if timestamps else None,
        "last_bar_at": _iso(timestamps[-1]) if timestamps else None,
        "unique_open_seconds_utc": open_seconds,
        "expected_open_seconds_utc": expected_open_seconds_utc,
        "matches_expected_boundary": matches_expected,
    }


def xau_d1_evaluation_snapshot(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    signal: FiveCoreSignal | None = None,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    decision_at = ensure_utc(as_of)
    resolved = signal or evaluate_xau_d1_tsmom_60_200(rows, as_of=decision_at)
    closed = _closed_rows(rows, as_of=decision_at, timeframe_seconds=86400)

    payload: dict[str, Any] = {
        "contract": FORWARD_EVIDENCE_CONTRACT,
        "execution_influence": False,
        "symbol": "XAUUSD",
        "strategy_id": PAIR_STRATEGY_IDS["XAUUSD"],
        "observed_at": decision_at.isoformat(),
        "closed_bars": len(closed),
        "direction": resolved.direction,
        "active": bool(resolved.active),
        "execution_eligible": bool(resolved.execution_eligible),
        "reason": resolved.reason,
        "signal_bar_at": _iso(resolved.signal_bar_at),
        "next_entry_at": _iso(resolved.next_entry_at),
        "atr14": None if resolved.atr is None else float(resolved.atr),
        "signal_close": None,
        "ema200": None,
        "return_60": None,
        "distance_to_ema200_pct": None,
        "d1_boundary": bar_boundary_snapshot(
            closed,
            expected_open_seconds_utc=XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC,
        ),
    }

    if len(closed) < 200:
        return payload
    closes = [float(row.close) for row in closed]
    if len(closes) < 61:
        return payload
    ema200 = float(_ema(closes, 200)[-1])
    ret60 = float(closes[-1] / closes[-61] - 1.0)
    atr14 = float(_wilder_ewm(_true_ranges(closed), 14)[-1])
    close = float(closes[-1])
    distance = close / ema200 - 1.0 if isfinite(ema200) and ema200 != 0 else None
    payload.update(
        {
            "signal_close": close,
            "ema200": ema200,
            "return_60": ret60,
            "distance_to_ema200_pct": distance,
            "atr14": atr14,
        }
    )
    return payload


def evaluation_key(snapshot: dict[str, Any]) -> str | None:
    signal_bar = snapshot.get("signal_bar_at")
    if not signal_bar or int(snapshot.get("closed_bars") or 0) < 200:
        return None
    direction = snapshot.get("direction") or "NONE"
    active = "ACTIVE" if bool(snapshot.get("active")) else "INACTIVE"
    reason = str(snapshot.get("reason") or "UNKNOWN")
    return f"{signal_bar}|{direction}|{active}|{reason}"
