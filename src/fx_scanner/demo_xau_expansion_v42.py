from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
from typing import Mapping, Sequence

from .demo_technical_strategy import analyze_demo_pair_mtf
from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .guards import evaluate_hard_guards
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import SetupType, TradePlan

STRATEGY_ID = "D1_EXPANSION_S2R2T2H0_V42"
FORWARD_DEMO_SCORE = 60.0
ENTRY_WINDOW_SECONDS = 30 * 60
TR_MULT = 1.45
ATR_MULT = 1.25
ADX_MIN = 22.0
BODY_ATR_MIN = 0.60
LOOKBACK = 30
BUFFER_ATR = 0.05
STOP_ATR = 1.25
RR = 2.60
TARGET_ATR = STOP_ATR * RR
MAX_HOLD_D1_BARS = 7


@dataclass(frozen=True, slots=True)
class XauExpansionSignal:
    direction: str | None
    active: bool
    execution_eligible: bool
    signal_bar_at: datetime | None = None
    next_entry_at: datetime | None = None
    atr: float | None = None
    adx: float | None = None
    reason: str = "NO_SIGNAL"
    symbol: str = "XAUUSD"
    strategy_id: str = STRATEGY_ID


def _ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for raw in values[1:]:
        out.append(alpha * float(raw) + (1.0 - alpha) * out[-1])
    return out


def _rolling_mean(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, raw in enumerate(values):
        running += float(raw)
        if i >= period:
            running -= float(values[i - period])
        if i >= period - 1:
            out[i] = running / period
    return out


def _true_ranges(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    previous_close: float | None = None
    for row in bars:
        high, low, close = float(row.high), float(row.low), float(row.close)
        value = high - low
        if previous_close is not None:
            value = max(value, abs(high - previous_close), abs(low - previous_close))
        out.append(value)
        previous_close = close
    return out


def _research_indicators(bars: Sequence[Bar]) -> dict[str, list[float | None] | list[float]]:
    closes = [float(row.close) for row in bars]
    highs = [float(row.high) for row in bars]
    lows = [float(row.low) for row in bars]
    tr = _true_ranges(bars)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, len(bars)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr = _rolling_mean(tr, 14)
    tr14 = _rolling_mean(tr, 14)
    pdm14 = _rolling_mean(plus_dm, 14)
    mdm14 = _rolling_mean(minus_dm, 14)
    dx = [0.0] * len(bars)
    for i in range(len(bars)):
        if tr14[i] and pdm14[i] is not None and mdm14[i] is not None:
            pdi = 100.0 * float(pdm14[i]) / float(tr14[i])
            mdi = 100.0 * float(mdm14[i]) / float(tr14[i])
            denom = pdi + mdi
            dx[i] = 100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0
    adx = _rolling_mean(dx, 14)
    return {
        "e20": _ema(closes, 20),
        "e50": _ema(closes, 50),
        "e200": _ema(closes, 200),
        "tr": tr,
        "atr": atr,
        "adx": adx,
    }


def _closed_rows(bars: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row for row in sorted(bars, key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp) + timedelta(days=1) <= now
    )


def _next_weekday_open(signal_at: datetime) -> datetime:
    candidate = ensure_utc(signal_at) + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _next_bar_open(bars: Sequence[Bar], signal_bar: Bar) -> datetime:
    signal_ts = ensure_utc(signal_bar.timestamp)
    for row in sorted(bars, key=lambda x: ensure_utc(x.timestamp)):
        if ensure_utc(row.timestamp) > signal_ts:
            return ensure_utc(row.timestamp)
    return _next_weekday_open(signal_ts)


def evaluate_xau_d1_expansion_v42(
    bars: Sequence[Bar], *, as_of: datetime
) -> XauExpansionSignal:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if any(row.symbol.upper() != "XAUUSD" or row.timeframe != "D1" for row in rows):
        return XauExpansionSignal(None, False, True, reason="INVALID_D1_BUNDLE")
    closed = _closed_rows(rows, as_of=as_of)
    if len(closed) < 220:
        return XauExpansionSignal(None, False, True, reason="INSUFFICIENT_D1_HISTORY")

    ind = _research_indicators(closed)
    i = len(closed) - 1
    atr_raw = ind["atr"][i]
    adx_raw = ind["adx"][i]
    if atr_raw is None or adx_raw is None or float(atr_raw) <= 0:
        return XauExpansionSignal(None, False, True, reason="D1_INDICATORS_UNAVAILABLE")
    atr = float(atr_raw)
    adx = float(adx_raw)
    prior_atr = [float(x) for x in ind["atr"][max(0, i - 50):i] if x is not None and float(x) > 0]
    median_atr = median(prior_atr) if prior_atr else atr
    row = closed[i]
    body = abs(float(row.close) - float(row.open))
    expansion = float(ind["tr"][i]) >= TR_MULT * atr or atr >= ATR_MULT * median_atr
    prior = closed[i - LOOKBACK:i]
    prior_high = max(float(x.high) for x in prior)
    prior_low = min(float(x.low) for x in prior)
    e20 = float(ind["e20"][i])
    e50 = float(ind["e50"][i])
    e200 = float(ind["e200"][i])
    close = float(row.close)

    direction: str | None = None
    if expansion and adx >= ADX_MIN and body >= BODY_ATR_MIN * atr:
        if close > prior_high + BUFFER_ATR * atr and close > e20 > e50 > e200:
            direction = "LONG"
        elif close < prior_low - BUFFER_ATR * atr and close < e20 < e50 < e200:
            direction = "SHORT"

    signal_at = ensure_utc(row.timestamp)
    next_entry = _next_bar_open(rows, row)
    if direction is None:
        return XauExpansionSignal(
            None,
            False,
            True,
            signal_bar_at=signal_at,
            next_entry_at=next_entry,
            atr=atr,
            adx=adx,
            reason="D1_EXPANSION_CONTRACT_NOT_MET",
        )
    now = ensure_utc(as_of)
    active = next_entry <= now <= next_entry + timedelta(seconds=ENTRY_WINDOW_SECONDS)
    return XauExpansionSignal(
        direction,
        active,
        True,
        signal_bar_at=signal_at,
        next_entry_at=next_entry,
        atr=atr,
        adx=adx,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_D1_OPEN",
    )


def build_xau_expansion_v42_plan(
    signal: XauExpansionSignal, *, current_price: float
) -> TradePlan:
    if signal.strategy_id != STRATEGY_ID or not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active XAU expansion V4.2 signal required")
    atr = float(signal.atr or 0.0)
    price = float(current_price)
    if not isfinite(atr) or atr <= 0 or not isfinite(price) or price <= 0:
        raise ValueError("valid price and ATR required")
    zone_half = max(price * 1e-7, atr * 0.001)
    if signal.direction == "LONG":
        stop = price - STOP_ATR * atr
        target = price + TARGET_ATR * atr
    else:
        stop = price + STOP_ATR * atr
        target = price - TARGET_ATR * atr
    plan = TradePlan(
        direction=signal.direction,
        entry_low=price - zone_half,
        entry_high=price + zone_half,
        stop_loss=stop,
        tp1=None,
        tp2=target,
        rr1=None,
        rr2=RR,
        chase_distance_atr=0.0,
    )
    remember_plan_evidence(
        plan,
        DemoPlanGeometryEvidence(
            entry_mode=STRATEGY_ID,
            pullback_atr=0.0,
            zone_distance_atr=0.0,
            confirmation="D1_S2R2T2H0_EXPANSION_BREAKOUT",
            fvg_age_minutes=0,
            fvg_status="NOT_APPLICABLE",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="D1_EXPANSION_V42_DEFERRED_STEP_MAX7",
        ),
    )
    return plan


def forward_rank(signal: XauExpansionSignal) -> PairRank:
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("directional signal required")
    edge = FORWARD_DEMO_SCORE if signal.direction == "LONG" else -FORWARD_DEMO_SCORE
    return PairRank(
        symbol="XAUUSD",
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


def build_xau_expansion_v42_analysis(
    *,
    signal: XauExpansionSignal,
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
    plan = build_xau_expansion_v42_plan(signal, current_price=float(m5[-1].close))
    guard_flags = dict(external_guard_flags)
    guard_flags.update({"STALE_SIGNAL": False, "CHASE_BLOCK": False, "RR_BLOCK": False, "STRUCTURE_INVALID": False})
    guard_result = evaluate_hard_guards(required_names=cfg.scoring["hard_guards"], **guard_flags)
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
        conviction_components={"xau_expansion_v42": FORWARD_DEMO_SCORE},
        computed_guards={"STALE_SIGNAL": False, "CHASE_BLOCK": False, "RR_BLOCK": False, "STRUCTURE_INVALID": False},
        decision=decision,
    )
