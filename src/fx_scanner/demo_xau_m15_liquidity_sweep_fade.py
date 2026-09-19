from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_technical_strategy import analyze_demo_pair_mtf
from .demo_trade_plan_geometry import (\n    DemoPlanGeometryEvidence,\n    demo_entry_zone_half_width,\n    remember_plan_evidence,\n)
from .demo_xau_m15_ema_reversal_recovery import _atr_at_end, _closed_rows, _ema, _next_bar_open
from .guards import evaluate_hard_guards
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import SetupType, TradePlan

STRATEGY_ID = "XAU_M15_LIQUIDITY_SWEEP_FADE_V1"
STRATEGY_CONTRACT = "TELEGRAM_SETUP_TRANSPARENT_FORMALIZATION_V1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
FORWARD_DEMO_SCORE = 70.0
ENTRY_WINDOW_SECONDS = 10 * 60
ATR_PERIOD = 14
EMA_CONTEXT_PERIOD = 20
SWEEP_LOOKBACK = 12
IMPULSE_LOOKBACK = 8
MIN_SWEEP_ATR = 0.05
MIN_IMPULSE_ATR = 1.50
MIN_EXTENSION_FROM_EMA_ATR = 0.60
MIN_REJECTION_ATR = 0.35
MIN_BODY_ATR = 0.10
MIN_DIRECTIONAL_CLOSE_LOCATION = 0.55
MIN_RECLAIM_ATR = 0.02
MAX_CHASE_BEYOND_EMA_ATR = 0.25
STOP_BUFFER_ATR = 1.00
MIN_SIGNAL_RISK_ATR = 0.50
MAX_SIGNAL_RISK_ATR = 3.00
TP1_R = 1.20
TP2_R = 1.80
RESEARCH_LADDER_R = (0.30, 0.60, 0.90, 1.20, 1.50, 1.80)


@dataclass(frozen=True, slots=True)
class XauM15LiquiditySweepFadeSignal:
    direction: str | None
    active: bool
    execution_eligible: bool
    signal_bar_at: datetime | None = None
    next_entry_at: datetime | None = None
    atr: float | None = None
    ema20: float | None = None
    swept_level: float | None = None
    sweep_price: float | None = None
    structural_stop: float | None = None
    sweep_depth_atr: float | None = None
    impulse_atr: float | None = None
    extension_from_ema_atr: float | None = None
    rejection_atr: float | None = None
    reclaim_atr: float | None = None
    body_atr: float | None = None
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
        payload["research_ladder_r"] = list(RESEARCH_LADDER_R)
        return payload


def _short_candidate(
    closed: Sequence[Bar],
    *,
    row: Bar,
    atr: float,
    ema20: float,
) -> tuple[bool, dict[str, float], list[str]]:
    prior = closed[-(SWEEP_LOOKBACK + 1):-1]
    impulse_window = closed[-(IMPULSE_LOOKBACK + 1):-1]
    swept_level = max(float(item.high) for item in prior)
    sweep_price = float(row.high)
    sweep_depth_atr = (sweep_price - swept_level) / atr
    impulse_atr = (sweep_price - min(float(item.low) for item in impulse_window)) / atr
    extension_from_ema_atr = (sweep_price - ema20) / atr
    rejection_atr = (sweep_price - float(row.close)) / atr
    reclaim_atr = (swept_level - float(row.close)) / atr
    body_atr = (float(row.open) - float(row.close)) / atr
    candle_range = max(float(row.high) - float(row.low), 1e-12)
    close_location = (float(row.high) - float(row.close)) / candle_range
    structural_stop = sweep_price + STOP_BUFFER_ATR * atr
    signal_risk_atr = (structural_stop - float(row.close)) / atr

    checks = (
        ("LIQUIDITY_HIGH_SWEPT", sweep_depth_atr >= MIN_SWEEP_ATR),
        ("RALLY_IMPULSE", impulse_atr >= MIN_IMPULSE_ATR),
        ("OVEREXTENDED_FROM_EMA20", extension_from_ema_atr >= MIN_EXTENSION_FROM_EMA_ATR),
        (
            "BEARISH_SWEEP_RECLAIM",
            float(row.close) < float(row.open)
            and float(row.close) < swept_level
            and body_atr >= MIN_BODY_ATR
            and rejection_atr >= MIN_REJECTION_ATR
            and reclaim_atr >= MIN_RECLAIM_ATR
            and close_location >= MIN_DIRECTIONAL_CLOSE_LOCATION,
        ),
        ("NOT_LATE_CHASE", float(row.close) >= ema20 - MAX_CHASE_BEYOND_EMA_ATR * atr),
        ("RISK_GEOMETRY", MIN_SIGNAL_RISK_ATR <= signal_risk_atr <= MAX_SIGNAL_RISK_ATR),
    )
    failed = [name for name, passed in checks if not passed]
    return not failed, {
        "swept_level": swept_level,
        "sweep_price": sweep_price,
        "structural_stop": structural_stop,
        "sweep_depth_atr": sweep_depth_atr,
        "impulse_atr": impulse_atr,
        "extension_from_ema_atr": extension_from_ema_atr,
        "rejection_atr": rejection_atr,
        "reclaim_atr": reclaim_atr,
        "body_atr": body_atr,
        "close_location": close_location,
    }, failed


def _long_candidate(
    closed: Sequence[Bar],
    *,
    row: Bar,
    atr: float,
    ema20: float,
) -> tuple[bool, dict[str, float], list[str]]:
    prior = closed[-(SWEEP_LOOKBACK + 1):-1]
    impulse_window = closed[-(IMPULSE_LOOKBACK + 1):-1]
    swept_level = min(float(item.low) for item in prior)
    sweep_price = float(row.low)
    sweep_depth_atr = (swept_level - sweep_price) / atr
    impulse_atr = (max(float(item.high) for item in impulse_window) - sweep_price) / atr
    extension_from_ema_atr = (ema20 - sweep_price) / atr
    rejection_atr = (float(row.close) - sweep_price) / atr
    reclaim_atr = (float(row.close) - swept_level) / atr
    body_atr = (float(row.close) - float(row.open)) / atr
    candle_range = max(float(row.high) - float(row.low), 1e-12)
    close_location = (float(row.close) - float(row.low)) / candle_range
    structural_stop = sweep_price - STOP_BUFFER_ATR * atr
    signal_risk_atr = (float(row.close) - structural_stop) / atr

    checks = (
        ("LIQUIDITY_LOW_SWEPT", sweep_depth_atr >= MIN_SWEEP_ATR),
        ("SELLOFF_IMPULSE", impulse_atr >= MIN_IMPULSE_ATR),
        ("OVEREXTENDED_FROM_EMA20", extension_from_ema_atr >= MIN_EXTENSION_FROM_EMA_ATR),
        (
            "BULLISH_SWEEP_RECLAIM",
            float(row.close) > float(row.open)
            and float(row.close) > swept_level
            and body_atr >= MIN_BODY_ATR
            and rejection_atr >= MIN_REJECTION_ATR
            and reclaim_atr >= MIN_RECLAIM_ATR
            and close_location >= MIN_DIRECTIONAL_CLOSE_LOCATION,
        ),
        ("NOT_LATE_CHASE", float(row.close) <= ema20 + MAX_CHASE_BEYOND_EMA_ATR * atr),
        ("RISK_GEOMETRY", MIN_SIGNAL_RISK_ATR <= signal_risk_atr <= MAX_SIGNAL_RISK_ATR),
    )
    failed = [name for name, passed in checks if not passed]
    return not failed, {
        "swept_level": swept_level,
        "sweep_price": sweep_price,
        "structural_stop": structural_stop,
        "sweep_depth_atr": sweep_depth_atr,
        "impulse_atr": impulse_atr,
        "extension_from_ema_atr": extension_from_ema_atr,
        "rejection_atr": rejection_atr,
        "reclaim_atr": reclaim_atr,
        "body_atr": body_atr,
        "close_location": close_location,
    }, failed


def evaluate_xau_m15_liquidity_sweep_fade(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> XauM15LiquiditySweepFadeSignal:
    """Point-in-time formalization of the observed Telegram XAU fade setup.

    SHORT: impulsive rally -> fresh buy-side liquidity sweep -> bearish reclaim.
    LONG: exact price-axis mirror.  No proprietary Telegram rule is assumed;
    only reproducible structure visible in the supplied setup is encoded.
    """

    rows = tuple(sorted(bars, key=lambda value: ensure_utc(value.timestamp)))
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != TIMEFRAME for row in rows):
        return XauM15LiquiditySweepFadeSignal(None, False, True, reason="INVALID_M15_BUNDLE")

    closed = _closed_rows(rows, as_of=as_of)
    minimum = max(EMA_CONTEXT_PERIOD + 5, SWEEP_LOOKBACK + IMPULSE_LOOKBACK + 5)
    if len(closed) < minimum:
        return XauM15LiquiditySweepFadeSignal(None, False, True, reason="INSUFFICIENT_M15_HISTORY")

    atr = _atr_at_end(closed, ATR_PERIOD)
    if atr is None:
        return XauM15LiquiditySweepFadeSignal(None, False, True, reason="M15_ATR_UNAVAILABLE")
    ema20 = _ema([float(item.close) for item in closed], EMA_CONTEXT_PERIOD)[-1]
    row = closed[-1]
    signal_at = ensure_utc(row.timestamp)
    next_entry_at = _next_bar_open(rows, row)

    short_pass, short_metrics, short_failed = _short_candidate(
        closed, row=row, atr=atr, ema20=ema20
    )
    long_pass, long_metrics, long_failed = _long_candidate(
        closed, row=row, atr=atr, ema20=ema20
    )

    if short_pass and long_pass:
        return XauM15LiquiditySweepFadeSignal(
            None,
            False,
            True,
            signal_bar_at=signal_at,
            next_entry_at=next_entry_at,
            atr=atr,
            ema20=ema20,
            reason="AMBIGUOUS_BIDIRECTIONAL_SWEEP",
        )
    if short_pass:
        direction, metrics = "SHORT", short_metrics
    elif long_pass:
        direction, metrics = "LONG", long_metrics
    else:
        return XauM15LiquiditySweepFadeSignal(
            None,
            False,
            True,
            signal_bar_at=signal_at,
            next_entry_at=next_entry_at,
            atr=atr,
            ema20=ema20,
            reason=(
                "M15_SWEEP_FADE_NOT_MET:SHORT["
                + ",".join(short_failed)
                + "]|LONG["
                + ",".join(long_failed)
                + "]"
            ),
        )

    now = ensure_utc(as_of)
    active = next_entry_at <= now <= next_entry_at + timedelta(seconds=ENTRY_WINDOW_SECONDS)
    return XauM15LiquiditySweepFadeSignal(
        direction,
        active,
        True,
        signal_bar_at=signal_at,
        next_entry_at=next_entry_at,
        atr=atr,
        ema20=ema20,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_M15_OPEN",
        **metrics,
    )


def build_xau_m15_liquidity_sweep_fade_plan(
    signal: XauM15LiquiditySweepFadeSignal,
    *,
    current_price: float,
) -> TradePlan:
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active XAU M15 liquidity-sweep fade signal required")
    atr = float(signal.atr or 0.0)
    stop = float(signal.structural_stop or 0.0)
    price = float(current_price)
    if not all(isfinite(value) and value > 0 for value in (atr, stop, price)):
        raise ValueError("valid ATR, structural stop and current price required")

    if signal.direction == "SHORT":
        if stop <= price:
            raise ValueError("SHORT structural stop must remain above entry")
        risk = stop - price
        tp1 = price - TP1_R * risk
        tp2 = price - TP2_R * risk
        confirmation = "M15_BUYSIDE_LIQUIDITY_SWEEP_BEARISH_RECLAIM"
    else:
        if stop >= price:
            raise ValueError("LONG structural stop must remain below entry")
        risk = price - stop
        tp1 = price + TP1_R * risk
        tp2 = price + TP2_R * risk
        confirmation = "M15_SELLSIDE_LIQUIDITY_SWEEP_BULLISH_RECLAIM"

    risk_atr = risk / atr
    if not MIN_SIGNAL_RISK_ATR <= risk_atr <= MAX_SIGNAL_RISK_ATR + 0.75:
        raise ValueError("live sweep-fade risk geometry outside bounded ATR range")
    if min(tp1, tp2) <= 0:
        raise ValueError("take-profit price must remain positive")

    zone_half = demo_entry_zone_half_width(price=price, current_atr=atr)
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
            pullback_atr=signal.rejection_atr,
            zone_distance_atr=signal.sweep_depth_atr,
            confirmation=confirmation,
            fvg_age_minutes=0,
            fvg_status="NOT_REQUIRED",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="TELEGRAM_LADDER_0P3R_TO_1P8R_BROKER_TP1_1P2R_TP2_1P8R",
        ),
    )
    return plan


def forward_rank(signal: XauM15LiquiditySweepFadeSignal) -> PairRank:
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


def build_xau_m15_liquidity_sweep_fade_analysis(
    *,
    signal: XauM15LiquiditySweepFadeSignal,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg,
    as_of: datetime,
    external_guard_flags: Mapping[str, bool],
):
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("directional XAU M15 liquidity-sweep fade signal required")
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
    plan = build_xau_m15_liquidity_sweep_fade_plan(signal, current_price=float(m5[-1].close))

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
    return replace(
        base,
        symbol=SYMBOL,
        direction=signal.direction,
        setup_type=SetupType.LIQUIDITY_SWEEP_REVERSAL,
        trigger_confirmed=True,
        trade_plan=plan,
        conviction_components={
            "xau_m15_liquidity_sweep_fade": FORWARD_DEMO_SCORE,
            "sweep_depth_atr": signal.sweep_depth_atr,
            "impulse_atr": signal.impulse_atr,
            "extension_from_ema_atr": signal.extension_from_ema_atr,
            "rejection_atr": signal.rejection_atr,
            "reclaim_atr": signal.reclaim_atr,
        },
        computed_guards={
            "STALE_SIGNAL": False,
            "CHASE_BLOCK": False,
            "RR_BLOCK": False,
            "STRUCTURE_INVALID": False,
            **dict(external_guard_flags),
        },
        decision=decision,
    )
