from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from typing import Mapping, Sequence

from .demo_technical_strategy import analyze_demo_pair_mtf
from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .guards import evaluate_hard_guards
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import DeepScanReport, SetupType, TradePlan, UniverseSelection

FIVE_CORE_SYMBOLS = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
EXECUTION_SYMBOLS = frozenset({"XAUUSD"})
SHADOW_SYMBOLS = frozenset({"USDJPY"})
NO_TRADE_SYMBOLS = frozenset({"EURUSD", "GBPUSD", "AUDUSD"})

PAIR_STRATEGY_IDS = {
    "XAUUSD": "D1_TSMOM_60_200",
    "USDJPY": "H4_COMPRESSION_BREAKOUT",
    "EURUSD": "NO_TRADE_UNTIL_VALIDATED",
    "GBPUSD": "NO_TRADE_UNTIL_VALIDATED",
    "AUDUSD": "NO_TRADE_UNTIL_VALIDATED",
}

D1_STOP_ATR = 2.0
D1_TARGET_ATR = 4.0
D1_MAX_HOLD_BARS = 30
D1_ENTRY_WINDOW_SECONDS = 30 * 60
FORWARD_DEMO_SCORE = 60.0

H4_STOP_ATR = 1.5
H4_TARGET_ATR = 3.0
H4_MAX_HOLD_BARS = 24


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


def _linear_quantile(values: Sequence[float], q: float) -> float:
    clean = sorted(float(v) for v in values if isfinite(float(v)))
    if not clean:
        raise ValueError("quantile requires values")
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(clean) - 1)
    frac = pos - lo
    return clean[lo] * (1.0 - frac) + clean[hi] * frac


def _next_weekday_open(signal_at: datetime) -> datetime:
    candidate = ensure_utc(signal_at) + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _next_bar_open(
    bars: Sequence[Bar],
    signal_bar: Bar,
) -> datetime:
    ordered = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    signal_ts = ensure_utc(signal_bar.timestamp)
    for row in ordered:
        if ensure_utc(row.timestamp) > signal_ts:
            return ensure_utc(row.timestamp)
    return _next_weekday_open(signal_ts)


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
    next_entry = _next_bar_open(rows, signal_bar)
    atr14 = _wilder_ewm(_true_ranges(closed), 14)[-1]
    if direction is None:
        return FiveCoreSignal(
            "XAUUSD", PAIR_STRATEGY_IDS["XAUUSD"], None, False, True,
            signal_bar_at=signal_at, next_entry_at=next_entry, atr=atr14,
            reason="D1_TREND_MOMENTUM_NOT_ALIGNED",
        )
    now = ensure_utc(as_of)
    in_entry_window = next_entry <= now <= next_entry + timedelta(seconds=D1_ENTRY_WINDOW_SECONDS)
    return FiveCoreSignal(
        "XAUUSD",
        PAIR_STRATEGY_IDS["XAUUSD"],
        direction,
        bool(in_entry_window),
        True,
        signal_bar_at=signal_at,
        next_entry_at=next_entry,
        atr=atr14,
        reason="ENTRY_WINDOW_ACTIVE" if in_entry_window else "WAIT_NEXT_D1_OPEN",
    )


def evaluate_usdjpy_h4_compression_breakout(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> FiveCoreSignal:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if any(row.symbol.upper() != "USDJPY" or row.timeframe != "H4" for row in rows):
        return FiveCoreSignal("USDJPY", PAIR_STRATEGY_IDS["USDJPY"], None, False, False, reason="INVALID_H4_BUNDLE")
    closed = _closed_rows(rows, as_of=as_of, timeframe_seconds=14400)
    if len(closed) < 201:
        return FiveCoreSignal("USDJPY", PAIR_STRATEGY_IDS["USDJPY"], None, False, False, reason="INSUFFICIENT_H4_HISTORY")

    closes = [float(row.close) for row in closed]
    atrs = _wilder_ewm(_true_ranges(closed), 14)
    atr_pct = [a / c if c > 0 else float("nan") for a, c in zip(atrs, closes)]
    ema50 = _ema(closes, 50)[-1]
    ema200 = _ema(closes, 200)[-1]

    i = len(closed) - 1
    prior_window = atr_pct[i - 100:i]
    q35 = _linear_quantile(prior_window, 0.35)
    compressed = atr_pct[i - 1] < q35
    prior20 = closed[i - 20:i]
    prior_high = max(float(row.high) for row in prior20)
    prior_low = min(float(row.low) for row in prior20)
    close = closes[-1]

    direction: str | None = None
    if compressed and ema50 > ema200 and close > prior_high:
        direction = "LONG"
    elif compressed and ema50 < ema200 and close < prior_low:
        direction = "SHORT"

    signal_bar = closed[-1]
    return FiveCoreSignal(
        "USDJPY",
        PAIR_STRATEGY_IDS["USDJPY"],
        direction,
        direction is not None,
        False,
        signal_bar_at=ensure_utc(signal_bar.timestamp),
        next_entry_at=_next_bar_open(rows, signal_bar),
        atr=atrs[-1],
        reason="SHADOW_SIGNAL" if direction else "NO_H4_COMPRESSION_BREAKOUT",
    )


def build_xau_d1_tsmom_plan(
    signal: FiveCoreSignal,
    *,
    current_price: float,
) -> TradePlan:
    if signal.symbol != "XAUUSD" or signal.strategy_id != PAIR_STRATEGY_IDS["XAUUSD"]:
        raise ValueError("XAU D1 strategy signal required")
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active directional XAU D1 signal required")
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
            entry_mode=PAIR_STRATEGY_IDS["XAUUSD"],
            pullback_atr=0.0,
            zone_distance_atr=0.0,
            confirmation="D1_CLOSE_TREND_MOMENTUM_ALIGNED",
            fvg_age_minutes=0,
            fvg_status="NOT_APPLICABLE",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="D1_FIXED_ATR_STOP_TARGET_MAX30",
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


def build_xau_execution_analysis(
    *,
    signal: FiveCoreSignal,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg,
    as_of: datetime,
    external_guard_flags: Mapping[str, bool],
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
    plan = build_xau_d1_tsmom_plan(signal, current_price=current_price)

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
        symbol="XAUUSD",
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
        symbol="XAUUSD",
        direction=signal.direction,
        setup_type=SetupType.TREND_CONTINUATION,
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


def five_core_policy_snapshot() -> dict[str, str]:
    return {symbol: PAIR_STRATEGY_IDS[symbol] for symbol in FIVE_CORE_SYMBOLS}
