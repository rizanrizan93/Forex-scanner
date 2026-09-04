from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite

from .liquidity import FairValueGap
from .strategy import TradePlan
from .technical import atr


@dataclass(frozen=True, slots=True)
class WaveEntryAssessment:
    ready: bool
    mode: str
    reason: str
    pullback_atr: float
    zone_distance_atr: float
    confirmation: str


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name}_INVALID") from exc
    if not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name}_OUT_OF_RANGE")
    return value


def demo_wave_thresholds() -> tuple[float, float, float]:
    """Return DEMO-only wave-entry thresholds.

    The 2 ATR calibration chase ceiling remains a candidate-monitoring ceiling;
    it is no longer permission to execute in the middle of an impulse leg.
    """
    minimum_pullback_atr = _env_float(
        "CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", 0.25, minimum=0.05, maximum=1.50
    )
    max_zone_distance_atr = _env_float(
        "CTRADER_DEMO_WAVE_MAX_ZONE_ATR", 0.50, minimum=0.05, maximum=1.00
    )
    momentum_max_zone_atr = _env_float(
        "CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", 0.20, minimum=0.0, maximum=0.50
    )
    if momentum_max_zone_atr > max_zone_distance_atr:
        raise ValueError("CTRADER_DEMO_MOMENTUM_ZONE_EXCEEDS_PULLBACK_ZONE")
    return minimum_pullback_atr, max_zone_distance_atr, momentum_max_zone_atr


def _nearest_directional_gap(
    direction,
    m5,
    liquidity,
    current_price: float,
    *,
    current_atr: float | None = None,
    max_chase_atr: float | None = None,
) -> FairValueGap | None:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    candidates = [
        gap
        for gap in liquidity.fvgs
        if gap.direction == wanted and gap.status in {"OPEN", "PARTIAL"}
    ]
    if m5.fvg is not None and m5.fvg.valid and m5.fvg.direction == wanted:
        synthetic = FairValueGap(
            wanted,
            m5.fvg.lower,
            m5.fvg.upper,
            liquidity.observed_at,
            "OPEN",
            0.0,
        )
        if not any(
            abs(gap.lower - synthetic.lower) <= 1e-12
            and abs(gap.upper - synthetic.upper) <= 1e-12
            for gap in candidates
        ):
            candidates.append(synthetic)
    if not candidates:
        return None

    def zone_distance(gap: FairValueGap) -> float:
        if gap.lower <= current_price <= gap.upper:
            return 0.0
        if current_price < gap.lower:
            return gap.lower - current_price
        return current_price - gap.upper

    def chase_distance(gap: FairValueGap) -> float:
        if current_atr is None or current_atr <= 0:
            return 0.0
        if direction == "LONG":
            return max(0.0, float(current_price) - float(gap.upper)) / current_atr
        return max(0.0, float(gap.lower) - float(current_price)) / current_atr

    def is_chase_eligible(gap: FairValueGap) -> bool:
        if max_chase_atr is None or current_atr is None or current_atr <= 0:
            return True
        return chase_distance(gap) <= float(max_chase_atr)

    return min(
        candidates,
        key=lambda gap: (
            0 if is_chase_eligible(gap) else 1,
            zone_distance(gap),
            0 if gap.status == "PARTIAL" else 1,
            -gap.lower if direction == "LONG" else gap.upper,
        ),
    )


def _aligned_confirmation(snapshot, wanted: str) -> tuple[str, bool, bool]:
    break_aligned = snapshot.mss == wanted or snapshot.bos == wanted
    sweep = getattr(snapshot, "sweep", None)
    sweep_aligned = bool(
        sweep is not None
        and bool(getattr(sweep, "valid", False))
        and getattr(sweep, "direction", None) == wanted
    )
    displacement = getattr(snapshot, "displacement", None)
    displacement_aligned = bool(
        displacement is not None
        and bool(getattr(displacement, "valid", False))
        and getattr(displacement, "direction", None) == wanted
    )
    if break_aligned:
        return "M5_STRUCTURE_BREAK", break_aligned, displacement_aligned
    if sweep_aligned:
        return "M5_SWEEP_RECLAIM", break_aligned, displacement_aligned
    if displacement_aligned:
        return "M5_DISPLACEMENT", break_aligned, displacement_aligned
    return "NONE", break_aligned, displacement_aligned


def assess_demo_wave_entry(
    *,
    direction: str,
    current_price: float,
    entry_low: float,
    entry_high: float,
    h1,
    m15,
    m5,
    m5_bars,
    current_atr: float,
) -> WaveEntryAssessment:
    """Require a structural pullback/reaction before DEMO execution.

    LONG prioritizes a higher-low reaction; SHORT prioritizes a lower-high
    reaction. A momentum continuation is retained only as a secondary path when
    price is still very close to the structural entry zone and M5 has both an
    aligned structure break and displacement.
    """
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if not isfinite(current_atr) or current_atr <= 0:
        raise ValueError("current_atr must be positive finite")

    minimum_pullback_atr, max_zone_atr, momentum_zone_atr = demo_wave_thresholds()
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    opposite = "BEARISH" if wanted == "BULLISH" else "BULLISH"

    zone_distance = 0.0
    if current_price < entry_low:
        zone_distance = (entry_low - current_price) / current_atr
    elif current_price > entry_high:
        zone_distance = (current_price - entry_high) / current_atr

    prior = tuple(m5_bars[-13:-1]) if len(m5_bars) > 1 else tuple(m5_bars)
    if not prior:
        return WaveEntryAssessment(False, "WAIT", "INSUFFICIENT_WAVE_BARS", 0.0, zone_distance, "NONE")

    if direction == "LONG":
        recent_extreme = max(float(bar.high) for bar in prior)
        pullback_atr = max(0.0, recent_extreme - current_price) / current_atr
        anchor = m15.last_swing_low
        if anchor is None:
            anchor = h1.last_swing_low
        anchor_valid = anchor is not None and current_price > float(anchor)
    else:
        recent_extreme = min(float(bar.low) for bar in prior)
        pullback_atr = max(0.0, current_price - recent_extreme) / current_atr
        anchor = m15.last_swing_high
        if anchor is None:
            anchor = h1.last_swing_high
        anchor_valid = anchor is not None and current_price < float(anchor)

    transition_aligned = any(
        snapshot.mss == wanted or snapshot.bos == wanted
        for snapshot in (h1, m15)
    )
    trend_aligned = bool(
        h1.trend != opposite
        and m15.trend != opposite
        and (h1.trend == wanted or m15.trend == wanted or transition_aligned)
    )
    confirmation, break_aligned, displacement_aligned = _aligned_confirmation(m5, wanted)

    momentum_ready = bool(
        trend_aligned
        and anchor_valid
        and zone_distance <= momentum_zone_atr
        and pullback_atr < minimum_pullback_atr
        and break_aligned
        and displacement_aligned
    )
    if momentum_ready:
        return WaveEntryAssessment(
            True,
            "MOMENTUM_CONTINUATION",
            "READY",
            pullback_atr,
            zone_distance,
            confirmation,
        )

    pullback_ready = bool(
        trend_aligned
        and anchor_valid
        and pullback_atr >= minimum_pullback_atr
        and zone_distance <= max_zone_atr
        and confirmation != "NONE"
    )
    if pullback_ready:
        mode = "HL_PULLBACK" if direction == "LONG" else "LH_PULLBACK"
        return WaveEntryAssessment(True, mode, "READY", pullback_atr, zone_distance, confirmation)

    if not trend_aligned:
        reason = "HTF_M15_NOT_ALIGNED"
    elif not anchor_valid:
        reason = "SWING_ANCHOR_INVALID"
    elif zone_distance > max_zone_atr:
        reason = "WAIT_RETRACE_TO_ENTRY_ZONE"
    elif pullback_atr < minimum_pullback_atr:
        reason = "WAIT_HL_LH_PULLBACK"
    elif confirmation == "NONE":
        reason = "WAIT_M5_REACTION_CONFIRMATION"
    else:
        reason = "WAVE_ENTRY_NOT_READY"
    return WaveEntryAssessment(False, "WAIT", reason, pullback_atr, zone_distance, confirmation)


def build_demo_trade_plan(
    *,
    direction: str,
    current_price: float,
    m15,
    h1,
    m5,
    liquidity,
    m5_bars,
    atr_period: int,
    sl_buffer_atr: float,
    minimum_entry_zone_atr: float,
    chase_block_atr: float = 0.50,
) -> TradePlan | None:
    """Build a DEMO plan only after a wave-aware entry reaction.

    The broad DEMO chase allowance is used only to keep a candidate observable.
    Actual execution now requires either an HL/LH pullback reaction near the raw
    FVG entry zone, or a much tighter momentum-continuation exception. The raw
    FVG is never extended to current price, preventing mid-wave market chasing.
    """
    current_atr = float(atr(list(m5_bars), atr_period))
    if not isfinite(current_atr) or current_atr <= 0:
        return None

    gap = _nearest_directional_gap(
        direction,
        m5,
        liquidity,
        current_price,
        current_atr=current_atr,
        max_chase_atr=float(chase_block_atr),
    )
    if gap is None:
        return None

    entry_low, entry_high = float(gap.lower), float(gap.upper)
    if entry_high - entry_low < current_atr * float(minimum_entry_zone_atr):
        return None

    wave = assess_demo_wave_entry(
        direction=direction,
        current_price=float(current_price),
        entry_low=entry_low,
        entry_high=entry_high,
        h1=h1,
        m15=m15,
        m5=m5,
        m5_bars=m5_bars,
        current_atr=current_atr,
    )
    if not wave.ready:
        return None

    buffer = current_atr * float(sl_buffer_atr)
    tolerance = current_atr * 0.05

    if direction == "LONG":
        anchor = None
        if m15.sweep is not None and m15.sweep.valid and m15.sweep.direction == "BULLISH":
            anchor = m15.sweep.level
        if anchor is None:
            anchor = h1.last_swing_low
        if anchor is None:
            return None

        stop = min(float(anchor), entry_low) - buffer
        risk = entry_high - stop
        if not isfinite(risk) or risk <= 0:
            return None
        chase = max(0.0, float(current_price) - entry_high) / current_atr

        targets = []
        for level in liquidity.levels_above(entry_high):
            price = float(level.price)
            if price <= entry_high:
                continue
            if not targets or abs(price - targets[-1]) > tolerance:
                targets.append(price)
        if not targets:
            return None
        tp1 = targets[0]
        rr1 = (tp1 - entry_high) / risk
        if len(targets) > 1:
            tp2 = targets[1]
        else:
            fallback_rr = max(2.0, rr1 + 0.50)
            tp2 = entry_high + fallback_rr * risk
        rr2 = (tp2 - entry_high) / risk
    else:
        anchor = None
        if m15.sweep is not None and m15.sweep.valid and m15.sweep.direction == "BEARISH":
            anchor = m15.sweep.level
        if anchor is None:
            anchor = h1.last_swing_high
        if anchor is None:
            return None

        stop = max(float(anchor), entry_high) + buffer
        risk = stop - entry_low
        if not isfinite(risk) or risk <= 0:
            return None
        chase = max(0.0, entry_low - float(current_price)) / current_atr

        targets = []
        for level in liquidity.levels_below(entry_low):
            price = float(level.price)
            if price >= entry_low:
                continue
            if not targets or abs(price - targets[-1]) > tolerance:
                targets.append(price)
        if not targets:
            return None
        tp1 = targets[0]
        rr1 = (entry_low - tp1) / risk
        if len(targets) > 1:
            tp2 = targets[1]
        else:
            fallback_rr = max(2.0, rr1 + 0.50)
            tp2 = entry_low - fallback_rr * risk
        rr2 = (entry_low - tp2) / risk

    return TradePlan(
        direction,
        entry_low,
        entry_high,
        stop,
        tp1,
        tp2,
        rr1,
        rr2,
        chase,
    )


def install_demo_trade_plan_geometry_patch() -> None:
    """Deprecated compatibility shim; explicit DEMO producer no longer calls it."""
    from . import strategy

    strategy._build_trade_plan = build_demo_trade_plan
