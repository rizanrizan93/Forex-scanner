from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .exceptions import DataContractError
from .models import Bar
from .strategy import TradePlan
from .technical import atr

LOOKBACK_BARS = 12
RETEST_BARS = 12
IMPULSE_RANGE_ATR = 1.20
IMPULSE_BODY_ATR = 0.80
RETEST_MIN_ATR = 0.10
RETEST_MAX_ATR = 1.25
ACCEPTANCE_INVALIDATION_ATR = 0.25
STOP_BUFFER_ATR = 0.35
TARGET_R = 1.50

# Pair-specific DEMO execution registry.
# XAUUSD keeps IMPULSE_RETEST_V2 as its active strategy. EURUSD is promoted to
# DEMO execution as an isolated baseline so its own forward evidence can decide
# whether this family remains suitable or should later be replaced by a
# EURUSD-specific strategy. No LIVE authority is granted here.
EXECUTION_SYMBOLS = frozenset({"XAUUSD", "EURUSD"})
SHADOW_SYMBOLS = frozenset()
PAIR_STRATEGY_IDS = {
    "XAUUSD": "IMPULSE_RETEST_V2",
    "EURUSD": "EURUSD_IMPULSE_RETEST_BASELINE_V1",
}


@dataclass(frozen=True, slots=True)
class ImpulseRetestV2Signal:
    symbol: str
    direction: str
    active: bool
    execution_eligible: bool
    impulse_index: int | None = None
    breakout_level: float | None = None
    impulse_atr: float | None = None
    impulse_close: float | None = None
    retest_depth_atr: float | None = None
    reason: str = "NO_VALID_IMPULSE_RETEST"


def _wanted(direction: str) -> str:
    value = str(direction).upper()
    if value not in {"LONG", "SHORT"}:
        raise DataContractError("IMPULSE_RETEST_V2 direction must be LONG or SHORT")
    return value


def evaluate_impulse_retest_v2(
    bars: Sequence[Bar],
    *,
    direction: str,
) -> ImpulseRetestV2Signal:
    """Detect the latest completed M5 impulse whose first valid retest is the current bar.

    The contract intentionally matches the public-data research definition:
    prior-12-bar breakout, >=1.2 ATR range, >=0.8 ATR body, close near the
    directional extreme, retained acceptance, and a 0.10-1.25 ATR retest.
    """
    direction = _wanted(direction)
    rows = tuple(bars)
    if not rows:
        raise DataContractError("IMPULSE_RETEST_V2 requires M5 bars")
    symbol = rows[-1].symbol
    if any(row.symbol != symbol or row.timeframe != "M5" for row in rows):
        raise DataContractError("IMPULSE_RETEST_V2 requires one-symbol M5 bars")
    if len(rows) < LOOKBACK_BARS + RETEST_BARS + 15:
        return ImpulseRetestV2Signal(symbol, direction, False, symbol in EXECUTION_SYMBOLS, reason="INSUFFICIENT_HISTORY")

    current_idx = len(rows) - 1
    current = rows[current_idx]
    first_impulse = max(LOOKBACK_BARS + 14, current_idx - RETEST_BARS)

    for impulse_idx in range(current_idx - 1, first_impulse - 1, -1):
        history = rows[: impulse_idx + 1]
        impulse = rows[impulse_idx]
        impulse_atr = float(atr(list(history), 14))
        if impulse_atr <= 0:
            continue
        prior = rows[impulse_idx - LOOKBACK_BARS : impulse_idx]
        prior_high = max(row.high for row in prior)
        prior_low = min(row.low for row in prior)
        candle_range = float(impulse.high - impulse.low)
        body = abs(float(impulse.close - impulse.open))
        if candle_range <= 0:
            continue

        if direction == "LONG":
            breakout_level = float(prior_high)
            broke = impulse.close > breakout_level
            directional = impulse.close > impulse.open
            close_location = (impulse.close - impulse.low) / candle_range
            close_ok = close_location >= 0.75
        else:
            breakout_level = float(prior_low)
            broke = impulse.close < breakout_level
            directional = impulse.close < impulse.open
            close_location = (impulse.high - impulse.close) / candle_range
            close_ok = close_location >= 0.75

        impulse_ok = bool(
            broke
            and directional
            and close_ok
            and candle_range >= IMPULSE_RANGE_ATR * impulse_atr
            and body >= IMPULSE_BODY_ATR * impulse_atr
        )
        if not impulse_ok:
            continue

        stale_or_invalid = False
        for idx in range(impulse_idx + 1, current_idx):
            row = rows[idx]
            depth = (
                (impulse.close - row.low) / impulse_atr
                if direction == "LONG"
                else (row.high - impulse.close) / impulse_atr
            )
            accepted = row.close > breakout_level if direction == "LONG" else row.close < breakout_level
            if accepted and RETEST_MIN_ATR <= depth <= RETEST_MAX_ATR:
                stale_or_invalid = True
                break
            invalid = (
                row.close < breakout_level - ACCEPTANCE_INVALIDATION_ATR * impulse_atr
                if direction == "LONG"
                else row.close > breakout_level + ACCEPTANCE_INVALIDATION_ATR * impulse_atr
            )
            if invalid:
                stale_or_invalid = True
                break
        if stale_or_invalid:
            continue

        depth = (
            (impulse.close - current.low) / impulse_atr
            if direction == "LONG"
            else (current.high - impulse.close) / impulse_atr
        )
        accepted = current.close > breakout_level if direction == "LONG" else current.close < breakout_level
        touched = RETEST_MIN_ATR <= depth <= RETEST_MAX_ATR
        invalid_now = (
            current.close < breakout_level - ACCEPTANCE_INVALIDATION_ATR * impulse_atr
            if direction == "LONG"
            else current.close > breakout_level + ACCEPTANCE_INVALIDATION_ATR * impulse_atr
        )
        if invalid_now:
            continue
        if accepted and touched:
            return ImpulseRetestV2Signal(
                symbol=symbol,
                direction=direction,
                active=True,
                execution_eligible=symbol in EXECUTION_SYMBOLS,
                impulse_index=impulse_idx,
                breakout_level=breakout_level,
                impulse_atr=impulse_atr,
                impulse_close=float(impulse.close),
                retest_depth_atr=float(depth),
                reason="VALID_FIRST_CONTROLLED_RETEST" if symbol in EXECUTION_SYMBOLS else "SHADOW_ONLY_SYMBOL",
            )

    return ImpulseRetestV2Signal(
        symbol=symbol,
        direction=direction,
        active=False,
        execution_eligible=symbol in EXECUTION_SYMBOLS,
    )


def build_impulse_retest_v2_plan(signal: ImpulseRetestV2Signal, *, current_price: float) -> TradePlan | None:
    if not signal.active or signal.breakout_level is None or signal.impulse_atr is None:
        return None
    atr_value = float(signal.impulse_atr)
    level = float(signal.breakout_level)
    entry = float(current_price)
    half_width = max(atr_value * 0.025, abs(entry) * 1e-7)
    entry_low = entry - half_width
    entry_high = entry + half_width

    if signal.direction == "LONG":
        stop = level - STOP_BUFFER_ATR * atr_value
        if stop >= entry_low:
            return None
        risk = entry - stop
        tp2 = entry + TARGET_R * risk
    else:
        stop = level + STOP_BUFFER_ATR * atr_value
        if stop <= entry_high:
            return None
        risk = stop - entry
        tp2 = entry - TARGET_R * risk
    if risk <= 0:
        return None

    plan = TradePlan(
        direction=signal.direction,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop,
        tp1=None,
        tp2=tp2,
        rr1=None,
        rr2=TARGET_R,
        chase_distance_atr=0.0,
    )
    remember_plan_evidence(
        plan,
        DemoPlanGeometryEvidence(
            entry_mode="IMPULSE_RETEST_V2",
            pullback_atr=float(signal.retest_depth_atr or 0.0),
            zone_distance_atr=0.0,
            confirmation=signal.reason,
            fvg_age_minutes=0.0,
            fvg_status="NOT_APPLICABLE",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="IMPULSE_RETEST_R_MULTIPLE",
        ),
    )
    return plan
