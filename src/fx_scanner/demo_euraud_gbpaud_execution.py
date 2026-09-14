from __future__ import annotations

"""Exact DEMO execution adapters for the frozen EURAUD/GBPAUD strategies.

Signal rules are delegated to the already-frozen broker-native forward evaluators.
The broker order carries a 2 ATR initial SL and a deliberately remote 20R safety TP;
the strategy's authoritative exit is the dedicated D1 Chandelier/max-120 manager.
The remote TP exists because the shared cTrader order contract requires server-side
SL/TP geometry. It is not used as the research strategy's ordinary profit objective.
"""

from datetime import datetime
from math import isfinite
from typing import Mapping, Sequence

from .demo_euraud_gbpaud_forward_evidence import (
    EURAUD_STRATEGY_ID,
    GBPAUD_STRATEGY_ID,
    PAIR_SPECS,
    evaluate_euraud,
    evaluate_gbpaud,
)
from .demo_five_core_router import (
    D1_ENTRY_WINDOW_SECONDS,
    FiveCoreSignal,
    _build_execution_analysis,
    _entry_window,
)
from .demo_trade_plan_geometry import DemoPlanGeometryEvidence, remember_plan_evidence
from .models import Bar, ensure_utc
from .strategy import SetupType, TradePlan

DEMO_EXECUTION_CONTRACT = "EURAUD_GBPAUD_FROZEN_DEMO_V1"
EXECUTION_SYMBOLS = ("EURAUD", "GBPAUD")
FETCH_SYMBOLS = ("EURAUD", "GBPAUD", "GBPUSD", "AUDUSD")
INITIAL_STOP_ATR = 2.0
REMOTE_SAFETY_TP_R = 20.0
ENTRY_WINDOW_SECONDS = D1_ENTRY_WINDOW_SECONDS


def _parse_dt(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return ensure_utc(parsed)


def _snapshot_to_signal(snapshot: Mapping[str, object], *, as_of: datetime) -> FiveCoreSignal:
    symbol = str(snapshot.get("symbol") or "").upper()
    strategy_id = str(snapshot.get("strategy_id") or "")
    direction = str(snapshot.get("direction") or "").upper() or None
    signal_bar_at = _parse_dt(snapshot.get("signal_bar_at"))
    next_entry_at = _parse_dt(snapshot.get("next_entry_at"))
    atr_raw = snapshot.get("atr14")
    atr = None if atr_raw is None else float(atr_raw)

    if direction not in {"LONG", "SHORT"}:
        return FiveCoreSignal(
            symbol=symbol,
            strategy_id=strategy_id,
            direction=None,
            active=False,
            execution_eligible=True,
            signal_bar_at=signal_bar_at,
            next_entry_at=next_entry_at,
            atr=atr,
            reason=str(snapshot.get("reason") or "NO_SIGNAL"),
        )
    if signal_bar_at is None or next_entry_at is None or atr is None or not isfinite(atr) or atr <= 0:
        return FiveCoreSignal(
            symbol=symbol,
            strategy_id=strategy_id,
            direction=direction,
            active=False,
            execution_eligible=True,
            signal_bar_at=signal_bar_at,
            next_entry_at=next_entry_at,
            atr=atr,
            reason="FROZEN_SIGNAL_GEOMETRY_INCOMPLETE",
        )

    active = _entry_window(next_entry_at, as_of, ENTRY_WINDOW_SECONDS)
    return FiveCoreSignal(
        symbol=symbol,
        strategy_id=strategy_id,
        direction=direction,
        active=active,
        execution_eligible=True,
        signal_bar_at=signal_bar_at,
        next_entry_at=next_entry_at,
        atr=atr,
        reason="ENTRY_WINDOW_ACTIVE" if active else "WAIT_NEXT_D1_OPEN",
    )


def evaluate_euraud_demo_signal(
    bars: Sequence[Bar], *, as_of: datetime
) -> FiveCoreSignal:
    snapshot = evaluate_euraud(bars, as_of=as_of)
    return _snapshot_to_signal(snapshot, as_of=as_of)


def evaluate_gbpaud_demo_signal(
    bundles: Mapping[str, Sequence[Bar]], *, as_of: datetime
) -> FiveCoreSignal:
    snapshot = evaluate_gbpaud(bundles, as_of=as_of)
    return _snapshot_to_signal(snapshot, as_of=as_of)


def _chandelier_entry_plan(
    signal: FiveCoreSignal,
    *,
    current_price: float,
    trail_atr: float,
) -> TradePlan:
    if not signal.active or signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("active frozen D1 signal required")
    atr_value = float(signal.atr or 0.0)
    price = float(current_price)
    if not isfinite(atr_value) or atr_value <= 0 or not isfinite(price) or price <= 0:
        raise ValueError("valid current price and ATR required")

    risk = INITIAL_STOP_ATR * atr_value
    zone_half = max(price * 1e-7, atr_value * 0.001)
    if signal.direction == "LONG":
        stop = price - risk
        safety_tp = price + REMOTE_SAFETY_TP_R * risk
    else:
        stop = price + risk
        safety_tp = price - REMOTE_SAFETY_TP_R * risk
        if safety_tp <= 0:
            # This is practically unreachable for FX with a 40 ATR offset, but
            # fail closed instead of manufacturing invalid broker geometry.
            raise ValueError("remote safety TP would be non-positive")

    plan = TradePlan(
        direction=signal.direction,
        entry_low=price - zone_half,
        entry_high=price + zone_half,
        stop_loss=stop,
        tp1=None,
        tp2=safety_tp,
        rr1=None,
        rr2=REMOTE_SAFETY_TP_R,
        chase_distance_atr=0.0,
    )
    remember_plan_evidence(
        plan,
        DemoPlanGeometryEvidence(
            entry_mode=signal.strategy_id,
            pullback_atr=0.0,
            zone_distance_atr=0.0,
            confirmation="FROZEN_D1_RULE_CONFIRMED",
            fvg_age_minutes=0,
            fvg_status="NOT_APPLICABLE",
            fvg_fill_fraction=0.0,
            chase_monitor_distance_atr=0.0,
            exit_model=(
                f"D1_2ATR_INITIAL_STOP_CHANDELIER_{trail_atr:g}ATR_MAX120_"
                f"REMOTE_{REMOTE_SAFETY_TP_R:g}R_SAFETY_TP"
            ),
        ),
    )
    return plan


def build_euraud_plan(signal: FiveCoreSignal, *, current_price: float) -> TradePlan:
    if signal.symbol != "EURAUD" or signal.strategy_id != EURAUD_STRATEGY_ID:
        raise ValueError("EURAUD frozen strategy signal required")
    return _chandelier_entry_plan(
        signal,
        current_price=current_price,
        trail_atr=float(PAIR_SPECS["EURAUD"]["trail_atr"]),
    )


def build_gbpaud_plan(signal: FiveCoreSignal, *, current_price: float) -> TradePlan:
    if signal.symbol != "GBPAUD" or signal.strategy_id != GBPAUD_STRATEGY_ID:
        raise ValueError("GBPAUD frozen strategy signal required")
    return _chandelier_entry_plan(
        signal,
        current_price=current_price,
        trail_atr=float(PAIR_SPECS["GBPAUD"]["trail_atr"]),
    )


def build_euraud_execution_analysis(**kwargs):
    return _build_execution_analysis(
        **kwargs,
        plan_builder=build_euraud_plan,
        setup_type=SetupType.TREND_CONTINUATION,
    )


def build_gbpaud_execution_analysis(**kwargs):
    return _build_execution_analysis(
        **kwargs,
        plan_builder=build_gbpaud_plan,
        setup_type=SetupType.TREND_CONTINUATION,
    )
