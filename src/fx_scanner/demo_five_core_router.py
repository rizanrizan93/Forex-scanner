from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite, sqrt
from typing import Mapping, Sequence

from .demo_technical_strategy import analyze_demo_pair_mtf
from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .guards import evaluate_hard_guards
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import SetupType, TradePlan

FIVE_CORE_SYMBOLS = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
EXECUTION_SYMBOLS = frozenset({"XAUUSD", "USDJPY", "GBPUSD"})
SHADOW_SYMBOLS = frozenset()
NO_TRADE_SYMBOLS = frozenset({"EURUSD", "AUDUSD"})

PAIR_STRATEGY_IDS = {
    "XAUUSD": "D1_TSMOM_60_200",
    "USDJPY": "D1_DONCHIAN55_200",
    "GBPUSD": "H4_MEAN_REVERT_Z2_TO_SMA20",
    "EURUSD": "NO_TRADE_UNTIL_VALIDATED",
    "AUDUSD": "NO_TRADE_UNTIL_VALIDATED",
}

D1_STOP_ATR = 2.0
D1_TARGET_ATR = 4.0
D1_MAX_HOLD_BARS = 30
D1_ENTRY_WINDOW_SECONDS = 30 * 60
FORWARD_DEMO_SCORE = 60.0

H4_STOP_ATR = 1.5
H4_MAX_HOLD_BARS = 12
H4_ENTRY_WINDOW_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class FiveCoreSignal:
    symbol: str
    strategy_id: str
    direction: str | None
    active: bool
    execution_eligible: bool
    signal_bar_at: datetime | None = None
    next_entry_at: datetime | None = None
    atr: float | None = None
    target_price: float | None = None
    reason: str = "NO_SIGNAL"


def _closed_rows(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    timeframe_seconds: int,
) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row for row in bars
        if ensure_utc(row.timestamp) + timedelta(seconds=timeframe_seconds) <= now
    )


def _ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for raw in values[1:]:
        value = float(raw)
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _true_ranges(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    previous_close: float | None = None
    for row in bars:
        high = float(row.high)
        low = float(row.low)
        candidates = [abs(high - low)]
        if previous_close is not None:
            candidates.extend((abs(high - previous_close), abs(low - previous_close)))
        out.append(max(candidates))
        previous_close = float(row.close)
    return out


def _wilder_ewm(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []
    alpha = 1.0 / period
    out = [float(values[0])]
    for raw in values[1:]:
        value = float(raw)
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _rsi14(closes: Sequence[float]) -> float:
    if len(closes) < 15:
        return float("nan")
    gains = [0.0]
    losses = [0.0]
    for prev, cur in zip(closes[:-1], closes[1:]):
        delta = float(cur) - float(prev)
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = _wilder_ewm(gains, 14)[-1]
    avg_loss = _wilder_ewm(losses, 14)[-1]
    if avg_loss <= 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _adx14(bars: Sequence[Bar]) -> float:
    if len(bars) < 30:
        return float("nan")
    trs = _true_ranges(bars)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for prev, cur in zip(bars[:-1], bars[1:]):
        up = float(cur.high) - float(prev.high)
        down = float(prev.low) - float(cur.low)
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atrs = _wilder_ewm(trs, 14)
    plus = _wilder_ewm(plus_dm, 14)
    minus = _wilder_ewm(minus_dm, 14)
    dx: list[float] = []
    for a, p, m in zip(atrs, plus, minus):
        if a <= 0:
            dx.append(0.0)
            continue
        pdi = 100.0 * p / a
        mdi = 100.0 * m / a
        denom = pdi + mdi
        dx.append(0.0 if denom <= 0 else 100.0 * abs(pdi - mdi) / denom)
    return _wilder_ewm(dx, 14)[-1]


def _zscore20(closes: Sequence[float]) -> tuple[float, float]:
    if len(closes) < 20:
        return float("nan"), float("nan")
    sample = [float(v) for v in closes[-20:]]
    mean = sum(sample) / 20.0
    variance = sum((v - mean) ** 2 for v in sample) / 20.0
    std = sqrt(variance)
    return (0.0 if std <= 0 else (sample[-1] - mean) / std), mean


def _expected_next_open(signal_at: datetime, timeframe_seconds: int) -> datetime:
    candidate = ensure_utc(signal_at) + timedelta(seconds=timeframe_seconds)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _next_bar_open(
    bars: Sequence[Bar],
    signal_bar: Bar,
    *,
    timeframe_seconds: int,
) -> datetime:
    ordered = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    signal_ts = ensure_utc(signal_bar.timestamp)
    for row in ordered:
        if ensure_utc(row.timestamp) > signal_ts:
            return ensure_utc(row.timestamp)
    return _expected_next_open(signal_ts, timeframe_seconds)


def _entry_window(next_entry: datetime, as_of: datetime, seconds: int) -> bool:
    now = ensure_utc(as_of)
    return next_entry <= now <= next_entry + timedelta(seconds=seconds)


def evaluate_xau_d1_tsmom_60_200(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> FiveCoreSignal:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != "XAUUSD" or row.timeframe != "D1" for row in rows):
        return FiveCoreSignal("XAUUSD", PAIR_STRATEGY_IDS["XAUUSD"], None, False, True, reason="INVALID_D1_BUNDLE")
    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=86400)
    if len(closed) < 200:
        return FiveCoreSignal("XAUUSD", PAIR_STRATEGY_IDS["XAUUSD"], None, False, True, reason="INSUFFICIENT_D1_HISTORY")

    closes = [float(row.close) for row in closed]
    ema200 = _ema(closes, 200)[-1]
    if len(closes) < 61:
        return FiveCoreSignal("XAUUSD", PAIR_STRATEGY_IDS["XAUUSD"], None, False, True, reason="INSUFFICIENT_RET60_HISTORY")
    ret60 = closes[-1] / closes[-61] - 1.0
    direction: str | None = None
    if closes[-1] > ema200 and ret60 > 0:
        direction = "LONG"
    elif closes[-1] < ema200 and ret60 < 0:
        direction = "SHORT"

    signal_bar = closed[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry = _next_bar_open(rows, signal_bar, timeframe_seconds=86400)
    atr14 = _wilder_ewm(_true_ranges(closed), 14)[-1]
    if direction is None:
        return FiveCoreSignal(
            "XAUUSD", PAIR_STRATEGY_IDS["XAUUSD"], None, False, True,
            signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
            reason="D1_TREND_MOMENTUM_NOT_ALIGNED",
        )
    active = _entry_window(next_entry, as_of, D1_ENTRY_WINDOW_SECONDS)
    return FiveCoreSignal(
        "XAUUSD", PAIR_STRATEGY_IDS["XAUUSD"], direction, active, True,
        signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_D1_OPEN",
    )


def evaluate_usdjpy_d1_donchian55_200(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> FiveCoreSignal:
    """Frozen public-history lead: D1 Donchian-55 with EMA200 alignment."""
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != "USDJPY" or row.timeframe != "D1" for row in rows):
        return FiveCoreSignal("USDJPY", PAIR_STRATEGY_IDS["USDJPY"], None, False, True, reason="INVALID_D1_BUNDLE")
    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=86400)
    if len(closed) < 200:
        return FiveCoreSignal("USDJPY", PAIR_STRATEGY_IDS["USDJPY"], None, False, True, reason="INSUFFICIENT_D1_HISTORY")

    closes = [float(row.close) for row in closed]
    ema200 = _ema(closes, 200)[-1]
    prior55 = closed[-56:-1]
    prior_high = max(float(row.high) for row in prior55)
    prior_low = min(float(row.low) for row in prior55)
    close = closes[-1]
    direction: str | None = None
    if close > ema200 and close > prior_high:
        direction = "LONG"
    elif close < ema200 and close < prior_low:
        direction = "SHORT"

    signal_bar = closed[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry = _next_bar_open(rows, signal_bar, timeframe_seconds=86400)
    atr14 = _wilder_ewm(_true_ranges(closed), 14)[-1]
    if direction is None:
        return FiveCoreSignal(
            "USDJPY", PAIR_STRATEGY_IDS["USDJPY"], None, False, True,
            signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
            reason="NO_D1_DONCHIAN55_EMA200_BREAKOUT",
        )
    active = _entry_window(next_entry, as_of, D1_ENTRY_WINDOW_SECONDS)
    return FiveCoreSignal(
        "USDJPY", PAIR_STRATEGY_IDS["USDJPY"], direction, active, True,
        signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_D1_OPEN",
    )


def evaluate_gbpusd_h4_mean_revert_z2_to_sma20(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> FiveCoreSignal:
    """Frozen public-history lead: H4 Z2/RSI/ADX mean reversion to signal SMA20."""
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != "GBPUSD" or row.timeframe != "H4" for row in rows):
        return FiveCoreSignal("GBPUSD", PAIR_STRATEGY_IDS["GBPUSD"], None, False, True, reason="INVALID_H4_BUNDLE")
    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=14400)
    if len(closed) < 200:
        return FiveCoreSignal("GBPUSD", PAIR_STRATEGY_IDS["GBPUSD"], None, False, True, reason="INSUFFICIENT_H4_HISTORY")

    closes = [float(row.close) for row in closed]
    z20, sma20 = _zscore20(closes)
    rsi = _rsi14(closes)
    adx = _adx14(closed)
    direction: str | None = None
    if z20 <= -2.0 and rsi <= 30.0 and adx < 20.0:
        direction = "LONG"
    elif z20 >= 2.0 and rsi >= 70.0 and adx < 20.0:
        direction = "SHORT"

    signal_bar = closed[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry = _next_bar_open(rows, signal_bar, timeframe_seconds=14400)
    atr14 = _wilder_ewm(_true_ranges(closed), 14)[-1]
    if direction is None:
        return FiveCoreSignal(
            "GBPUSD", PAIR_STRATEGY_IDS["GBPUSD"], None, False, True,
            signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
            target_price=sma20,
            reason="NO_H4_Z2_RSI_ADX_MEAN_REVERSION",
        )
    active = _entry_window(next_entry, as_of, H4_ENTRY_WINDOW_SECONDS)
    return FiveCoreSignal(
        "GBPUSD", PAIR_STRATEGY_IDS["GBPUSD"], direction, active, True,
        signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
        target_price=sma20,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_H4_OPEN",
    )


# Backward-compatible alias retained for old shadow observers/tests. It now maps
# to the promoted frozen USDJPY public-history strategy rather than the rejected
# H4 compression family.
def evaluate_usdjpy_h4_compression_breakout(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> FiveCoreSignal:
    if bars and bars[0].timeframe == "H4":
        return FiveCoreSignal(
            "USDJPY", PAIR_STRATEGY_IDS["USDJPY"], None, False, True,
            reason="H4_COMPRESSION_SUPERSEDED_BY_D1_DONCHIAN55_200",
        )
    return evaluate_usdjpy_d1_donchian55_200(bars, as_of=as_of)


def _fixed_atr_plan(signal: FiveCoreSignal, *, current_price: float, entry_mode: str) -> TradePlan:
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active directional D1 signal required")
    atr_value = float(signal.atr or 0.0)
    price = float(current_price)
    if not isfinite(atr_value) or atr_value <= 0 or not isfinite(price) or price <= 0:
        raise ValueError("valid price and ATR required")
    zone_half = max(price * 1e-7, atr_value * 0.001)
    entry_low = price - zone_half
    entry_high = price + zone_half
    if signal.direction == "LONG":
        stop = price - D1_STOP_ATR * atr_value
        target = price + D1_TARGET_ATR * atr_value
    else:
        stop = price + D1_STOP_ATR * atr_value
        target = price - D1_TARGET_ATR * atr_value
    plan = TradePlan(
        direction=signal.direction,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop,
        tp1=None,
        tp2=target,
        rr1=None,
        rr2=D1_TARGET_ATR / D1_STOP_ATR,
        chase_distance_atr=0.0,
    )
    remember_plan_evidence(
        plan,
        DemoPlanGeometryEvidence(
            entry_mode=entry_mode,
            pullback_atr=0.0,
            zone_distance_atr=0.0,
            confirmation="D1_CLOSE_FROZEN_PAIR_RULE_CONFIRMED",
            fvg_age_minutes=0,
            fvg_status="NOT_APPLICABLE",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="D1_FIXED_ATR_STOP_TARGET_MAX30",
        ),
    )
    return plan


def build_xau_d1_tsmom_plan(signal: FiveCoreSignal, *, current_price: float) -> TradePlan:
    if signal.symbol != "XAUUSD" or signal.strategy_id != PAIR_STRATEGY_IDS["XAUUSD"]:
        raise ValueError("XAU D1 strategy signal required")
    return _fixed_atr_plan(signal, current_price=current_price, entry_mode=PAIR_STRATEGY_IDS["XAUUSD"])


def build_usdjpy_d1_donchian55_plan(signal: FiveCoreSignal, *, current_price: float) -> TradePlan:
    if signal.symbol != "USDJPY" or signal.strategy_id != PAIR_STRATEGY_IDS["USDJPY"]:
        raise ValueError("USDJPY D1 Donchian strategy signal required")
    return _fixed_atr_plan(signal, current_price=current_price, entry_mode=PAIR_STRATEGY_IDS["USDJPY"])


def build_gbpusd_h4_mean_revert_plan(signal: FiveCoreSignal, *, current_price: float) -> TradePlan:
    if signal.symbol != "GBPUSD" or signal.strategy_id != PAIR_STRATEGY_IDS["GBPUSD"]:
        raise ValueError("GBPUSD H4 mean-reversion strategy signal required")
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active directional GBPUSD H4 signal required")
    atr_value = float(signal.atr or 0.0)
    price = float(current_price)
    target = float(signal.target_price or 0.0)
    if not all(isfinite(v) for v in (atr_value, price, target)) or atr_value <= 0 or price <= 0 or target <= 0:
        raise ValueError("valid price, target and ATR required")
    if (signal.direction == "LONG" and target <= price) or (signal.direction == "SHORT" and target >= price):
        raise ValueError("mean-reversion target must remain beyond entry in signal direction")

    risk = H4_STOP_ATR * atr_value
    stop = price - risk if signal.direction == "LONG" else price + risk
    reward = abs(target - price)
    rr = reward / risk
    zone_half = max(price * 1e-7, atr_value * 0.001)
    plan = TradePlan(
        direction=signal.direction,
        entry_low=price - zone_half,
        entry_high=price + zone_half,
        stop_loss=stop,
        tp1=None,
        tp2=target,
        rr1=None,
        rr2=rr,
        chase_distance_atr=0.0,
    )
    remember_plan_evidence(
        plan,
        DemoPlanGeometryEvidence(
            entry_mode=PAIR_STRATEGY_IDS["GBPUSD"],
            pullback_atr=0.0,
            zone_distance_atr=0.0,
            confirmation="H4_Z2_RSI14_ADX14_MEAN_REVERSION_CONFIRMED",
            fvg_age_minutes=0,
            fvg_status="NOT_APPLICABLE",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="H4_1P5ATR_STOP_SIGNAL_SMA20_TARGET_MAX12",
        ),
    )
    return plan


def forward_rank(signal: FiveCoreSignal) -> PairRank:
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("directional signal required")
    edge = FORWARD_DEMO_SCORE if signal.direction == "LONG" else -FORWARD_DEMO_SCORE
    return PairRank(
        symbol=signal.symbol,
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


def _build_execution_analysis(
    *,
    signal: FiveCoreSignal,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg,
    as_of: datetime,
    external_guard_flags: Mapping[str, bool],
    plan_builder,
    setup_type: SetupType,
):
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
    current_price = float(m5[-1].close)
    plan = plan_builder(signal, current_price=current_price)

    guard_flags = dict(external_guard_flags)
    guard_flags.update(
        {
            "STALE_SIGNAL": False,
            "CHASE_BLOCK": False,
            "RR_BLOCK": False,
            "STRUCTURE_INVALID": False,
        }
    )
    guard_result = evaluate_hard_guards(required_names=cfg.scoring["hard_guards"], **guard_flags)
    state = SignalState.EXECUTION_READY if guard_result.allowed else SignalState.SETUP_FORMING
    decision = replace(
        base.decision,
        symbol=signal.symbol,
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
    return replace(
        base,
        symbol=signal.symbol,
        direction=signal.direction,
        setup_type=setup_type,
        trigger_confirmed=True,
        trade_plan=plan,
        conviction_components={"five_core_forward_demo": FORWARD_DEMO_SCORE},
        computed_guards={
            "STALE_SIGNAL": False,
            "CHASE_BLOCK": False,
            "RR_BLOCK": False,
            "STRUCTURE_INVALID": False,
        },
        decision=decision,
    )


def build_xau_execution_analysis(**kwargs):
    return _build_execution_analysis(
        **kwargs,
        plan_builder=build_xau_d1_tsmom_plan,
        setup_type=SetupType.TREND_CONTINUATION,
    )


def build_usdjpy_execution_analysis(**kwargs):
    return _build_execution_analysis(
        **kwargs,
        plan_builder=build_usdjpy_d1_donchian55_plan,
        setup_type=SetupType.TREND_CONTINUATION,
    )


def build_gbpusd_execution_analysis(**kwargs):
    return _build_execution_analysis(
        **kwargs,
        plan_builder=build_gbpusd_h4_mean_revert_plan,
        setup_type=SetupType.LIQUIDITY_SWEEP_REVERSAL,
    )


def five_core_policy_snapshot() -> dict[str, str]:
    return {symbol: PAIR_STRATEGY_IDS[symbol] for symbol in FIVE_CORE_SYMBOLS}
