from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_technical_strategy import analyze_demo_pair_mtf
from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .demo_xau_m15_canonical_policy import (
    CANONICAL_POLICY_CONTRACT,
    evaluate_canonical_xau_decision,
)
from .demo_xau_m15_ema_smc_reclaim import (
    MIN_H1_BARS,
    MIN_M15_BARS,
    STRATEGY_ID,
    STRATEGY_PROFILE,
    SYMBOL,
    evaluate_xau_m15_ema_smc_reclaim,
)
from .demo_xau_m15_ict_layer import ICT_LAYER_CONTRACT, evaluate_ict_execution_context
from .guards import evaluate_hard_guards
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import SetupType, TradePlan

STRATEGY_CONTRACT = "EMA_SMC_RECLAIM_M15_DEMO_EXECUTION_V1"
ENTRY_WINDOW_SECONDS = 10 * 60
TP1_R = 1.50
TP2_R = 3.00
MIN_EXECUTION_SCORE = 75.0
MIN_LIVE_RR = 1.0
MAX_LIVE_RISK_ATR = 3.0


@dataclass(frozen=True, slots=True)
class XauM15EmaSmcReclaimSignal:
    direction: str | None
    score: float
    active: bool
    execution_eligible: bool
    signal_bar_at: datetime | None = None
    next_entry_at: datetime | None = None
    atr: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    structural_stop: float | None = None
    liquidity_target: float | None = None
    projected_rr: float | None = None
    reason: str = "NO_SIGNAL"
    symbol: str = SYMBOL
    strategy_id: str = STRATEGY_ID
    strategy_profile: str = STRATEGY_PROFILE
    contract: str = STRATEGY_CONTRACT
    ict_layer_contract: str = ICT_LAYER_CONTRACT
    ict_evidence: dict[str, Any] | None = None
    canonical_policy_contract: str = CANONICAL_POLICY_CONTRACT
    canonical_evidence: dict[str, Any] | None = None

    def evidence(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("signal_bar_at", "next_entry_at"):
            value = payload.get(key)
            payload[key] = None if value is None else ensure_utc(value).isoformat()
        return payload


def _closed_rows(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    timeframe_minutes: int,
) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=timeframe_minutes) <= now
    )


def _next_bar_open(bars: Sequence[Bar], signal_bar: Bar, *, timeframe_minutes: int) -> datetime:
    signal_at = ensure_utc(signal_bar.timestamp)
    for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp)):
        if ensure_utc(row.timestamp) > signal_at:
            return ensure_utc(row.timestamp)
    return signal_at + timedelta(minutes=timeframe_minutes)


def evaluate_xau_m15_ema_smc_reclaim_execution(
    m15_bars: Sequence[Bar],
    h1_bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> XauM15EmaSmcReclaimSignal:
    """Fail-closed DEMO execution wrapper around the canonical XAU model.

    The EMA/SMC model creates directional evidence, the ICT layer validates
    location/liquidity, and the canonical policy is final execution authority.
    Only completed M15/H1 candles are used. Counter-trend scalps remain research
    only and impulse-without-retracement is blocked by construction.
    """

    m15_all = tuple(sorted(m15_bars, key=lambda value: ensure_utc(value.timestamp)))
    h1_all = tuple(sorted(h1_bars, key=lambda value: ensure_utc(value.timestamp)))
    if any(str(row.symbol).upper() != SYMBOL for row in (*m15_all, *h1_all)):
        return XauM15EmaSmcReclaimSignal(None, 0.0, False, False, reason="INVALID_SYMBOL_BUNDLE")

    m15 = _closed_rows(m15_all, as_of=as_of, timeframe_minutes=15)
    h1 = _closed_rows(h1_all, as_of=as_of, timeframe_minutes=60)
    if len(m15) < MIN_M15_BARS or len(h1) < MIN_H1_BARS:
        return XauM15EmaSmcReclaimSignal(
            None,
            0.0,
            False,
            False,
            reason="INSUFFICIENT_CLOSED_HISTORY",
        )

    result = evaluate_xau_m15_ema_smc_reclaim(m15, h1)
    direction = result.selected_direction
    selected = result.long if direction == "LONG" else result.short if direction == "SHORT" else None
    signal_bar = m15[-1]
    signal_at = ensure_utc(signal_bar.timestamp)
    next_entry_at = _next_bar_open(m15_all, signal_bar, timeframe_minutes=15)

    if selected is None or not selected.active or selected.score < MIN_EXECUTION_SCORE:
        return XauM15EmaSmcReclaimSignal(
            direction,
            float(result.score),
            False,
            False,
            signal_bar_at=signal_at,
            next_entry_at=next_entry_at,
            reason=f"MODEL_{result.state}",
        )

    evidence = dict(selected.evidence)
    atr = evidence.get("atr14")
    stop = evidence.get("structural_stop")
    target = evidence.get("liquidity_target")
    projected_rr = evidence.get("projected_rr")
    ema20 = evidence.get("ema20")
    ema50 = evidence.get("ema50")
    ema200 = evidence.get("ema200")
    close = float(evidence.get("price") or signal_bar.close)

    numeric = (atr, stop, ema20, ema50, ema200)
    if not all(value is not None and isfinite(float(value)) and float(value) > 0.0 for value in numeric):
        return XauM15EmaSmcReclaimSignal(
            direction,
            float(selected.score),
            False,
            False,
            signal_bar_at=signal_at,
            next_entry_at=next_entry_at,
            reason="INVALID_EXECUTION_GEOMETRY",
        )

    atr_value = float(atr)
    stop_value = float(stop)
    ict = evaluate_ict_execution_context(
        m15_all,
        direction=str(direction),
        atr_value=atr_value,
        as_of=as_of,
    )
    ict_payload = ict.to_payload()
    if not ict.execution_ready:
        block_reason = ",".join(ict.reasons) if ict.reasons else "UNKNOWN"
        return XauM15EmaSmcReclaimSignal(
            direction,
            float(selected.score),
            False,
            False,
            signal_bar_at=signal_at,
            next_entry_at=next_entry_at,
            atr=atr_value,
            ema20=float(ema20),
            ema50=float(ema50),
            ema200=float(ema200),
            structural_stop=stop_value,
            liquidity_target=None if target is None else float(target),
            projected_rr=None if projected_rr is None else float(projected_rr),
            reason=f"ICT_CONTEXT_BLOCK:{block_reason}",
            ict_evidence=ict_payload,
        )

    canonical = evaluate_canonical_xau_decision(
        direction=direction,
        score=float(selected.score),
        evidence=evidence,
        ict_evidence=ict_payload,
    )
    canonical_payload = canonical.to_payload()
    if not canonical.execution_ready:
        block_reason = ",".join(canonical.reasons) if canonical.reasons else "UNKNOWN"
        return XauM15EmaSmcReclaimSignal(
            direction,
            float(selected.score),
            False,
            False,
            signal_bar_at=signal_at,
            next_entry_at=next_entry_at,
            atr=atr_value,
            ema20=float(ema20),
            ema50=float(ema50),
            ema200=float(ema200),
            structural_stop=stop_value,
            liquidity_target=None if target is None else float(target),
            projected_rr=None if projected_rr is None else float(projected_rr),
            reason=f"CANONICAL_POLICY_BLOCK:{block_reason}",
            ict_evidence=ict_payload,
            canonical_evidence=canonical_payload,
        )

    risk = close - stop_value if direction == "LONG" else stop_value - close
    risk_atr = risk / atr_value if atr_value > 0.0 else 999.0

    external_target = ict.external_liquidity_target
    target_value = None if target is None else float(target)
    if external_target is not None:
        external_value = float(external_target)
        if (direction == "LONG" and external_value > close) or (
            direction == "SHORT" and external_value < close
        ):
            target_value = external_value

    rr_value: float | None = None
    if risk > 0.0 and target_value is not None:
        rr_value = (
            (target_value - close) / risk
            if direction == "LONG"
            else (close - target_value) / risk
        )
    elif projected_rr is not None:
        rr_value = float(projected_rr)

    geometry_ok = (
        risk > 0.0
        and risk_atr <= MAX_LIVE_RISK_ATR
        and rr_value is not None
        and isfinite(rr_value)
        and rr_value >= MIN_LIVE_RR
    )
    now = ensure_utc(as_of)
    active_window = next_entry_at <= now <= next_entry_at + timedelta(seconds=ENTRY_WINDOW_SECONDS)
    active = bool(geometry_ok and active_window)

    if not geometry_ok:
        reason = "RR_OR_STOP_GEOMETRY_BLOCK"
    elif not active_window:
        reason = "WAIT_NEXT_M15_OPEN" if now < next_entry_at else "ENTRY_WINDOW_EXPIRED"
    else:
        reason = "ENTRY_WINDOW_ACTIVE"

    return XauM15EmaSmcReclaimSignal(
        direction,
        float(selected.score),
        active,
        active,
        signal_bar_at=signal_at,
        next_entry_at=next_entry_at,
        atr=atr_value,
        ema20=float(ema20),
        ema50=float(ema50),
        ema200=float(ema200),
        structural_stop=stop_value,
        liquidity_target=target_value,
        projected_rr=rr_value,
        reason=reason,
        ict_evidence=ict_payload,
        canonical_evidence=canonical_payload,
    )


def build_xau_m15_ema_smc_reclaim_plan(
    signal: XauM15EmaSmcReclaimSignal,
    *,
    current_price: float,
) -> TradePlan:
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active XAU EMA-SMC reclaim signal required")
    price = float(current_price)
    atr = float(signal.atr or 0.0)
    stop = float(signal.structural_stop or 0.0)
    if not all(isfinite(value) and value > 0.0 for value in (price, atr, stop)):
        raise ValueError("valid price, ATR and structural stop required")

    if signal.direction == "LONG":
        if stop >= price:
            raise ValueError("LONG structural stop must remain below live entry")
        risk = price - stop
        tp1 = price + TP1_R * risk
        tp2 = price + TP2_R * risk
        confirmation = "M15_CANONICAL_BULLISH_RECLAIM_RETEST_ICT_CONTEXT"
    else:
        if stop <= price:
            raise ValueError("SHORT structural stop must remain above live entry")
        risk = stop - price
        tp1 = price - TP1_R * risk
        tp2 = price - TP2_R * risk
        confirmation = "M15_CANONICAL_BEARISH_RECLAIM_RETEST_ICT_CONTEXT"

    risk_atr = risk / atr
    if not isfinite(risk_atr) or risk_atr <= 0.0 or risk_atr > MAX_LIVE_RISK_ATR + 0.50:
        raise ValueError("live EMA-SMC reclaim risk geometry outside ATR bound")
    if min(tp1, tp2) <= 0.0:
        raise ValueError("take-profit price must remain positive")

    ict = dict(signal.ict_evidence or {})
    fvg_status = "ICT_FVG_RETEST" if bool(ict.get("fvg_retest")) else "ICT_CONTEXT_VALIDATED"
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
            pullback_atr=None,
            zone_distance_atr=None,
            confirmation=confirmation,
            fvg_age_minutes=0,
            fvg_status=fvg_status,
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model="CANONICAL_POSITION_AWARE_1P5R_3R_EXTERNAL_LIQUIDITY_V1",
        ),
    )
    return plan


def forward_rank(signal: XauM15EmaSmcReclaimSignal) -> PairRank:
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("directional EMA-SMC reclaim signal required")
    edge = float(signal.score) if signal.direction == "LONG" else -float(signal.score)
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


def build_xau_m15_ema_smc_reclaim_analysis(
    *,
    signal: XauM15EmaSmcReclaimSignal,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg,
    as_of: datetime,
    external_guard_flags: Mapping[str, bool],
):
    if signal.direction not in {"LONG", "SHORT"} or not signal.execution_eligible:
        raise ValueError("execution-eligible EMA-SMC reclaim signal required")
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
    plan = build_xau_m15_ema_smc_reclaim_plan(signal, current_price=float(m5[-1].close))

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
        conviction_score=float(signal.score),
        coverage=1.0,
        pair_coverage=1.0,
        state=state,
        guards=guard_result.active_guards,
        missing_components=(),
        pair_missing_components=(),
    )
    ict = dict(signal.ict_evidence or {})
    canonical = dict(signal.canonical_evidence or {})
    return replace(
        base,
        symbol=SYMBOL,
        direction=signal.direction,
        setup_type=SetupType.TREND_CONTINUATION,
        trigger_confirmed=True,
        trade_plan=plan,
        conviction_components={
            "xau_m15_ema_smc_reclaim": float(signal.score),
            "projected_liquidity_rr": signal.projected_rr,
            "ema20": signal.ema20,
            "ema50": signal.ema50,
            "ema200": signal.ema200,
            "ict_confluence_count": ict.get("confluence_count"),
            "ict_dealing_range_position": ict.get("dealing_range_position"),
            "ict_external_liquidity_target": ict.get("external_liquidity_target"),
            "canonical_policy_ready": 1.0 if canonical.get("execution_ready") else 0.0,
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
