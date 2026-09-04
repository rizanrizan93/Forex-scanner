from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite

from .liquidity import FairValueGap, LiquidityKind
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


def _structural_stop_anchor(direction: str, *, entry_low: float, entry_high: float, m5, m15, h1) -> float | None:
    """Choose the nearest valid structural invalidation anchor.

    Sweep/reclaim evidence is preferred, then the M5 pullback swing, M15 swing,
    and finally H1 swing. The selected level must sit beyond the raw entry zone
    in the invalidation direction; an ATR buffer is applied by the caller.
    """
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    attr = "last_swing_low" if direction == "LONG" else "last_swing_high"
    boundary = float(entry_low if direction == "LONG" else entry_high)
    candidates: list[tuple[int, float]] = []

    sweep = getattr(m15, "sweep", None)
    if (
        sweep is not None
        and bool(getattr(sweep, "valid", False))
        and getattr(sweep, "direction", None) == wanted
    ):
        level = getattr(sweep, "level", None)
        if level is not None:
            value = float(level)
            if (direction == "LONG" and value < boundary) or (direction == "SHORT" and value > boundary):
                candidates.append((0, value))

    for priority, snapshot in ((1, m5), (2, m15), (3, h1)):
        level = getattr(snapshot, attr, None)
        if level is None:
            continue
        value = float(level)
        if (direction == "LONG" and value < boundary) or (direction == "SHORT" and value > boundary):
            candidates.append((priority, value))

    if not candidates:
        return None
    best_priority = min(priority for priority, _ in candidates)
    preferred = [value for priority, value in candidates if priority == best_priority]
    return max(preferred) if direction == "LONG" else min(preferred)


def _liquidity_priority(kind) -> int:
    """Rank liquidity targets from local/internal to external/HTF."""
    try:
        normalized = LiquidityKind(kind)
    except (TypeError, ValueError):
        return 5
    if normalized in {
        LiquidityKind.ASIA_HIGH,
        LiquidityKind.ASIA_LOW,
        LiquidityKind.LONDON_HIGH,
        LiquidityKind.LONDON_LOW,
        LiquidityKind.NEW_YORK_HIGH,
        LiquidityKind.NEW_YORK_LOW,
    }:
        return 2
    if normalized in {LiquidityKind.EQUAL_HIGH, LiquidityKind.EQUAL_LOW}:
        return 3
    if normalized in {LiquidityKind.PDH, LiquidityKind.PDL}:
        return 4
    if normalized in {LiquidityKind.PWH, LiquidityKind.PWL}:
        return 5
    if normalized in {LiquidityKind.SWING_HIGH, LiquidityKind.SWING_LOW}:
        return 1
    return 6


def _structural_targets(
    direction: str,
    *,
    entry_low: float,
    entry_high: float,
    m15,
    h1,
    liquidity,
    tolerance: float,
) -> list[float]:
    """Return ordered structure/liquidity targets for TP construction.

    Priority is local M15 structure, H1 structure, session/internal liquidity,
    equal highs/lows, previous-day liquidity and then previous-week liquidity.
    Price ordering is still enforced so TP2 must sit beyond TP1.
    """
    reference = float(entry_high if direction == "LONG" else entry_low)
    attr = "last_swing_high" if direction == "LONG" else "last_swing_low"
    ranked: list[tuple[int, float]] = []

    for priority, snapshot in ((0, m15), (1, h1)):
        level = getattr(snapshot, attr, None)
        if level is None:
            continue
        price = float(level)
        if (direction == "LONG" and price > reference) or (direction == "SHORT" and price < reference):
            ranked.append((priority, price))

    levels = liquidity.levels_above(reference) if direction == "LONG" else liquidity.levels_below(reference)
    for level in levels:
        price = float(level.price)
        if (direction == "LONG" and price <= reference) or (direction == "SHORT" and price >= reference):
            continue
        ranked.append((_liquidity_priority(getattr(level, "kind", None)), price))

    ranked.sort(key=lambda item: (item[0], item[1] if direction == "LONG" else -item[1]))
    output: list[float] = []
    for _priority, price in ranked:
        if any(abs(price - existing) <= tolerance for existing in output):
            continue
        output.append(price)
    return output


def _next_farther_target(direction: str, targets: list[float], first: float, tolerance: float) -> float | None:
    if direction == "LONG":
        candidates = [price for price in targets if price > first + tolerance]
        return min(candidates) if candidates else None
    candidates = [price for price in targets if price < first - tolerance]
    return max(candidates) if candidates else None


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
    """Build a DEMO plan after a wave-aware entry reaction.

    Entry remains anchored to the raw FVG. Stops use structural invalidation
    (sweep/M5/M15/H1) plus an ATR buffer. Profit targets follow market structure
    and liquidity before any RR-derived fallback is used.
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
    anchor = _structural_stop_anchor(
        direction,
        entry_low=entry_low,
        entry_high=entry_high,
        m5=m5,
        m15=m15,
        h1=h1,
    )
    if anchor is None:
        return None

    targets = _structural_targets(
        direction,
        entry_low=entry_low,
        entry_high=entry_high,
        m15=m15,
        h1=h1,
        liquidity=liquidity,
        tolerance=tolerance,
    )
    if not targets:
        return None

    if direction == "LONG":
        stop = min(float(anchor), entry_low) - buffer
        risk = entry_high - stop
        if not isfinite(risk) or risk <= 0:
            return None
        chase = max(0.0, float(current_price) - entry_high) / current_atr
        tp1 = targets[0]
        rr1 = (tp1 - entry_high) / risk
        tp2 = _next_farther_target(direction, targets, tp1, tolerance)
        if tp2 is None:
            fallback_rr = max(2.0, rr1 + 0.50)
            tp2 = entry_high + fallback_rr * risk
        rr2 = (tp2 - entry_high) / risk
    else:
        stop = max(float(anchor), entry_high) + buffer
        risk = stop - entry_low
        if not isfinite(risk) or risk <= 0:
            return None
        chase = max(0.0, entry_low - float(current_price)) / current_atr
        tp1 = targets[0]
        rr1 = (entry_low - tp1) / risk
        tp2 = _next_farther_target(direction, targets, tp1, tolerance)
        if tp2 is None:
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
