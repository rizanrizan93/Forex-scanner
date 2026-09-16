from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_technical_strategy import analyze_demo_pair_mtf
from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .guards import evaluate_hard_guards
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import SetupType, TradePlan

STRATEGY_ID = "XAU_M15_EMA_REVERSAL_RECOVERY_V1"
STRATEGY_CONTRACT = "SCREENSHOT_DERIVED_SYMMETRIC_FORMALIZATION_V2"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
FORWARD_DEMO_SCORE = 70.0
ENTRY_WINDOW_SECONDS = 10 * 60
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
ATR_PERIOD = 14
EXTREME_LOOKBACK = 20
IMPULSE_LOOKBACK = 8
RECENT_EXTREME_BARS = 3
MIN_IMPULSE_ATR = 2.0
MIN_EXTENSION_ATR = 0.75
MIN_RECOVERY_ATR = 0.60
MIN_RECLAIM_BODY_ATR = 0.20
MIN_DIRECTIONAL_CLOSE_LOCATION = 0.60
MAX_CHASE_BEYOND_FAST_ATR = 0.30
STOP_BUFFER_ATR = 0.20
MIN_SIGNAL_RISK_ATR = 0.50
MAX_SIGNAL_RISK_ATR = 2.50
TP1_R = 1.50
TP2_R = 3.00
EXTENDED_RESEARCH_TARGET_R = 5.00

# Compatibility aliases retained for existing tests/evidence consumers.
RECENT_LOW_BARS = RECENT_EXTREME_BARS
MIN_DOWNSIDE_IMPULSE_ATR = MIN_IMPULSE_ATR
MIN_EXTENSION_BELOW_FAST_ATR = MIN_EXTENSION_ATR
MIN_RECOVERY_FROM_LOW_ATR = MIN_RECOVERY_ATR
MIN_BULL_BODY_ATR = MIN_RECLAIM_BODY_ATR
MIN_CLOSE_LOCATION = MIN_DIRECTIONAL_CLOSE_LOCATION
MAX_CLOSE_ABOVE_FAST_ATR = MAX_CHASE_BEYOND_FAST_ATR


@dataclass(frozen=True, slots=True)
class XauM15EmaReversalSignal:
    direction: str | None
    active: bool
    execution_eligible: bool
    signal_bar_at: datetime | None = None
    next_entry_at: datetime | None = None
    atr: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    recent_low: float | None = None
    recent_high: float | None = None
    structural_stop: float | None = None
    downside_impulse_atr: float | None = None
    upside_impulse_atr: float | None = None
    extension_below_fast_atr: float | None = None
    extension_above_fast_atr: float | None = None
    recovery_from_low_atr: float | None = None
    rejection_from_high_atr: float | None = None
    bull_body_atr: float | None = None
    bear_body_atr: float | None = None
    close_location: float | None = None
    reason: str = "NO_SIGNAL"
    symbol: str = SYMBOL
    strategy_id: str = STRATEGY_ID
    contract: str = STRATEGY_CONTRACT

    def evidence(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("signal_bar_at", "next_entry_at"):
            value = payload.get(key)
            payload[key] = None if value is None else ensure_utc(value).isoformat()
        return payload


def _ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for raw in values[1:]:
        out.append(alpha * float(raw) + (1.0 - alpha) * out[-1])
    return out


def _true_ranges(bars: Sequence[Bar]) -> list[float]:
    values: list[float] = []
    previous_close: float | None = None
    for row in bars:
        high = float(row.high)
        low = float(row.low)
        current = high - low
        if previous_close is not None:
            current = max(current, abs(high - previous_close), abs(low - previous_close))
        values.append(current)
        previous_close = float(row.close)
    return values


def _atr_at_end(bars: Sequence[Bar], period: int = ATR_PERIOD) -> float | None:
    tr = _true_ranges(bars)
    if len(tr) < period:
        return None
    value = sum(tr[-period:]) / float(period)
    return value if isfinite(value) and value > 0.0 else None


def _closed_rows(bars: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )


def _next_bar_open(bars: Sequence[Bar], signal_bar: Bar) -> datetime:
    signal_at = ensure_utc(signal_bar.timestamp)
    for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp)):
        if ensure_utc(row.timestamp) > signal_at:
            return ensure_utc(row.timestamp)
    return signal_at + timedelta(minutes=15)


def _long_candidate(
    closed: Sequence[Bar],
    *,
    row: Bar,
    previous: Bar,
    atr: float,
    ema20: float,
    ema50: float,
    ema200: float,
) -> tuple[bool, dict[str, float | None], list[str]]:
    recent_window = closed[-RECENT_EXTREME_BARS:]
    recent_low = min(float(item.low) for item in recent_window)
    extreme_low = min(float(item.low) for item in closed[-EXTREME_LOOKBACK:])
    reference_high = max(float(item.high) for item in closed[-(IMPULSE_LOOKBACK + 1):-1])
    downside_impulse_atr = (reference_high - recent_low) / atr
    extension_below_fast_atr = (ema20 - recent_low) / atr
    recovery_from_low_atr = (float(row.close) - recent_low) / atr
    bull_body_atr = (float(row.close) - float(row.open)) / atr
    candle_range = max(float(row.high) - float(row.low), 1e-12)
    close_location = (float(row.close) - float(row.low)) / candle_range
    structural_stop = recent_low - STOP_BUFFER_ATR * atr
    signal_risk_atr = (float(row.close) - structural_stop) / atr

    checks = (
        ("BEARISH_EMA_STACK", ema20 < ema50 < ema200),
        ("FRESH_EXTREME_LOW", recent_low <= extreme_low + max(1e-9, atr * 0.01)),
        ("SELL_OFF_IMPULSE", downside_impulse_atr >= MIN_IMPULSE_ATR),
        ("EXTENSION", extension_below_fast_atr >= MIN_EXTENSION_ATR),
        (
            "BULLISH_RECLAIM",
            float(row.close) > float(row.open)
            and float(row.close) > float(previous.close)
            and bull_body_atr >= MIN_RECLAIM_BODY_ATR
            and close_location >= MIN_DIRECTIONAL_CLOSE_LOCATION
            and recovery_from_low_atr >= MIN_RECOVERY_ATR,
        ),
        ("NOT_CHASED", float(row.close) <= ema20 + MAX_CHASE_BEYOND_FAST_ATR * atr),
        ("RISK_GEOMETRY", MIN_SIGNAL_RISK_ATR <= signal_risk_atr <= MAX_SIGNAL_RISK_ATR),
    )
    failed = [name for name, passed in checks if not passed]
    metrics: dict[str, float | None] = {
        "recent_low": recent_low,
        "recent_high": None,
        "structural_stop": structural_stop,
        "downside_impulse_atr": downside_impulse_atr,
        "upside_impulse_atr": None,
        "extension_below_fast_atr": extension_below_fast_atr,
        "extension_above_fast_atr": None,
        "recovery_from_low_atr": recovery_from_low_atr,
        "rejection_from_high_atr": None,
        "bull_body_atr": bull_body_atr,
        "bear_body_atr": None,
        "close_location": close_location,
    }
    return not failed, metrics, failed


def _short_candidate(
    closed: Sequence[Bar],
    *,
    row: Bar,
    previous: Bar,
    atr: float,
    ema20: float,
    ema50: float,
    ema200: float,
) -> tuple[bool, dict[str, float | None], list[str]]:
    recent_window = closed[-RECENT_EXTREME_BARS:]
    recent_high = max(float(item.high) for item in recent_window)
    extreme_high = max(float(item.high) for item in closed[-EXTREME_LOOKBACK:])
    reference_low = min(float(item.low) for item in closed[-(IMPULSE_LOOKBACK + 1):-1])
    upside_impulse_atr = (recent_high - reference_low) / atr
    extension_above_fast_atr = (recent_high - ema20) / atr
    rejection_from_high_atr = (recent_high - float(row.close)) / atr
    bear_body_atr = (float(row.open) - float(row.close)) / atr
    candle_range = max(float(row.high) - float(row.low), 1e-12)
    close_location = (float(row.high) - float(row.close)) / candle_range
    structural_stop = recent_high + STOP_BUFFER_ATR * atr
    signal_risk_atr = (structural_stop - float(row.close)) / atr

    checks = (
        ("BULLISH_EMA_STACK", ema20 > ema50 > ema200),
        ("FRESH_EXTREME_HIGH", recent_high >= extreme_high - max(1e-9, atr * 0.01)),
        ("RALLY_IMPULSE", upside_impulse_atr >= MIN_IMPULSE_ATR),
        ("EXTENSION", extension_above_fast_atr >= MIN_EXTENSION_ATR),
        (
            "BEARISH_REJECTION",
            float(row.close) < float(row.open)
            and float(row.close) < float(previous.close)
            and bear_body_atr >= MIN_RECLAIM_BODY_ATR
            and close_location >= MIN_DIRECTIONAL_CLOSE_LOCATION
            and rejection_from_high_atr >= MIN_RECOVERY_ATR,
        ),
        ("NOT_CHASED", float(row.close) >= ema20 - MAX_CHASE_BEYOND_FAST_ATR * atr),
        ("RISK_GEOMETRY", MIN_SIGNAL_RISK_ATR <= signal_risk_atr <= MAX_SIGNAL_RISK_ATR),
    )
    failed = [name for name, passed in checks if not passed]
    metrics: dict[str, float | None] = {
        "recent_low": None,
        "recent_high": recent_high,
        "structural_stop": structural_stop,
        "downside_impulse_atr": None,
        "upside_impulse_atr": upside_impulse_atr,
        "extension_below_fast_atr": None,
        "extension_above_fast_atr": extension_above_fast_atr,
        "recovery_from_low_atr": None,
        "rejection_from_high_atr": rejection_from_high_atr,
        "bull_body_atr": None,
        "bear_body_atr": bear_body_atr,
        "close_location": close_location,
    }
    return not failed, metrics, failed


def evaluate_xau_m15_ema_reversal_recovery(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> XauM15EmaReversalSignal:
    """Evaluate the transparent XAU M15 reversal/recovery V2 contract.

    LONG mirrors the supplied BUY example: extreme selloff below a bearish
    EMA20/50/200 stack followed by a bullish reclaim. SHORT is the exact
    directional mirror: extreme rally above a bullish stack followed by a
    bearish rejection. The source chart's proprietary formulas remain unknown;
    this contract is explicit, reproducible and independently attributable.
    """

    rows = tuple(sorted(bars, key=lambda value: ensure_utc(value.timestamp)))
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != TIMEFRAME for row in rows):
        return XauM15EmaReversalSignal(None, False, True, reason="INVALID_M15_BUNDLE")

    closed = _closed_rows(rows, as_of=as_of)
    minimum = max(EMA_SLOW + 5, EXTREME_LOOKBACK + IMPULSE_LOOKBACK + 5)
    if len(closed) < minimum:
        return XauM15EmaReversalSignal(None, False, True, reason="INSUFFICIENT_M15_HISTORY")

    closes = [float(item.close) for item in closed]
    ema20 = _ema(closes, EMA_FAST)[-1]
    ema50 = _ema(closes, EMA_MID)[-1]
    ema200 = _ema(closes, EMA_SLOW)[-1]
    atr = _atr_at_end(closed, ATR_PERIOD)
    if atr is None:
        return XauM15EmaReversalSignal(None, False, True, reason="M15_ATR_UNAVAILABLE")

    row = closed[-1]
    previous = closed[-2]
    signal_at = ensure_utc(row.timestamp)
    next_entry_at = _next_bar_open(rows, row)
    common = {
        "signal_bar_at": signal_at,
        "next_entry_at": next_entry_at,
        "atr": atr,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
    }

    if ema20 < ema50 < ema200:
        passed, metrics, failed = _long_candidate(
            closed,
            row=row,
            previous=previous,
            atr=atr,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
        )
        direction = "LONG"
    elif ema20 > ema50 > ema200:
        passed, metrics, failed = _short_candidate(
            closed,
            row=row,
            previous=previous,
            atr=atr,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
        )
        direction = "SHORT"
    else:
        return XauM15EmaReversalSignal(
            None,
            False,
            True,
            reason="M15_REVERSAL_NOT_MET:EMA_STACK_NOT_DIRECTIONAL",
            **common,
        )

    if not passed:
        return XauM15EmaReversalSignal(
            None,
            False,
            True,
            reason=f"M15_{direction}_REVERSAL_NOT_MET:" + ",".join(failed),
            **common,
            **metrics,
        )

    now = ensure_utc(as_of)
    active = next_entry_at <= now <= next_entry_at + timedelta(seconds=ENTRY_WINDOW_SECONDS)
    return XauM15EmaReversalSignal(
        direction,
        active,
        True,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_M15_OPEN",
        **common,
        **metrics,
    )


def build_xau_m15_ema_reversal_plan(
    signal: XauM15EmaReversalSignal,
    *,
    current_price: float,
) -> TradePlan:
    if (
        signal.strategy_id != STRATEGY_ID
        or not signal.active
        or signal.direction not in {"LONG", "SHORT"}
    ):
        raise ValueError("active XAU M15 EMA reversal LONG/SHORT signal required")
    atr = float(signal.atr or 0.0)
    stop = float(signal.structural_stop or 0.0)
    price = float(current_price)
    if not all(isfinite(value) and value > 0 for value in (atr, stop, price)):
        raise ValueError("valid M15 ATR, structural stop and price required")

    if signal.direction == "LONG":
        if stop >= price:
            raise ValueError("LONG structural stop must remain below current price")
        risk = price - stop
        tp1 = price + TP1_R * risk
        tp2 = price + TP2_R * risk
        confirmation = "M15_EXTREME_SELLOFF_BULLISH_RECLAIM_EMA20_50_200_CONTEXT"
        directional_excursion = signal.recovery_from_low_atr
    else:
        if stop <= price:
            raise ValueError("SHORT structural stop must remain above current price")
        risk = stop - price
        tp1 = price - TP1_R * risk
        tp2 = price - TP2_R * risk
        if tp2 <= 0:
            raise ValueError("SHORT TP2 must remain positive")
        confirmation = "M15_EXTREME_RALLY_BEARISH_REJECTION_EMA20_50_200_CONTEXT"
        directional_excursion = signal.rejection_from_high_atr

    risk_atr = risk / atr
    if not MIN_SIGNAL_RISK_ATR <= risk_atr <= MAX_SIGNAL_RISK_ATR + 0.50:
        raise ValueError("live reversal risk geometry outside bounded ATR range")

    zone_half = max(price * 1e-7, atr * 0.002)
    plan = TradePlan(
        direction=signal.direction,
        entry_low=price - zone_half,
        entry_high=price + zone_half,
        stop_loss=stop,
        tp1=tp1,
        tp2=tp2,
        rr1=TP1_R,
        rr2=TP2_R,
        chase_distance_atr=0.0,
    )
    remember_plan_evidence(
        plan,
        DemoPlanGeometryEvidence(
            entry_mode=STRATEGY_ID,
            pullback_atr=directional_excursion,
            zone_distance_atr=0.0,
            confirmation=confirmation,
            fvg_age_minutes=0,
            fvg_status="NOT_REQUIRED",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="M15_REVERSAL_TP1_1P5R_TP2_3R_EXTENDED_RESEARCH_5R",
        ),
    )
    return plan


def forward_rank(signal: XauM15EmaReversalSignal) -> PairRank:
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active directional signal required")
    edge = FORWARD_DEMO_SCORE if signal.direction == "LONG" else -FORWARD_DEMO_SCORE
    return PairRank(
        symbol=SYMBOL,
        direction=signal.direction,
        relative_macro_edge=0.0,
        relative_technical_edge=edge,
        cross_asset_edge=None,
        pair_edge=edge,
        absolute_edge=abs(edge),
        coverage=1.0,
        missing_components=(),
        rank=1,
    )


def build_xau_m15_ema_reversal_analysis(
    *,
    signal: XauM15EmaReversalSignal,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg,
    as_of: datetime,
    external_guard_flags: Mapping[str, bool],
):
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("directional XAU M15 reversal signal required")
    rank = forward_rank(signal)
    base = analyze_demo_pair_mtf(
        rank=rank,
        bars_by_timeframe=bars_by_timeframe,
        cfg=cfg,
        as_of=as_of,
        external_guard_flags=external_guard_flags,
        execution_quality_score=100.0,
    )
    m5 = tuple(bars_by_timeframe.get("M5", ()))
    if not m5:
        raise ValueError("M5 current price required")
    plan = build_xau_m15_ema_reversal_plan(signal, current_price=float(m5[-1].close))

    guard_flags = dict(external_guard_flags)
    guard_flags.update(
        {
            "STALE_SIGNAL": False,
            "CHASE_BLOCK": False,
            "RR_BLOCK": False,
            "STRUCTURE_INVALID": False,
        }
    )
    guard_result = evaluate_hard_guards(
        required_names=cfg.scoring["hard_guards"],
        **guard_flags,
    )
    state = SignalState.EXECUTION_READY if guard_result.allowed else SignalState.SETUP_FORMING
    decision = replace(
        base.decision,
        symbol=SYMBOL,
        direction=signal.direction,
        pair_rank=1,
        pair_edge=rank.pair_edge,
        conviction_score=FORWARD_DEMO_SCORE,
        coverage=1.0,
        pair_coverage=1.0,
        state=state,
        guards=guard_result.active_guards,
        missing_components=(),
        pair_missing_components=(),
    )
    directional_impulse = (
        signal.downside_impulse_atr
        if signal.direction == "LONG"
        else signal.upside_impulse_atr
    )
    directional_extension = (
        signal.extension_below_fast_atr
        if signal.direction == "LONG"
        else signal.extension_above_fast_atr
    )
    directional_recovery = (
        signal.recovery_from_low_atr
        if signal.direction == "LONG"
        else signal.rejection_from_high_atr
    )
    return replace(
        base,
        symbol=SYMBOL,
        direction=signal.direction,
        setup_type=SetupType.LIQUIDITY_SWEEP_REVERSAL,
        trigger_confirmed=True,
        trade_plan=plan,
        conviction_components={
            "xau_m15_ema_reversal_recovery": FORWARD_DEMO_SCORE,
            "directional_impulse_atr": directional_impulse,
            "directional_extension_atr": directional_extension,
            "directional_recovery_atr": directional_recovery,
        },
        computed_guards={
            "STALE_SIGNAL": False,
            "CHASE_BLOCK": False,
            "RR_BLOCK": False,
            "STRUCTURE_INVALID": False,
        },
        decision=decision,
    )
