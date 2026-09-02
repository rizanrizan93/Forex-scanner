from __future__ import annotations

from math import isfinite

from .liquidity import FairValueGap
from .strategy import TradePlan
from .technical import atr


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

    # Prefer a currently tradeable FVG first. If none are within the hard
    # chase limit, still return the nearest stale geometry so CHASE_BLOCK is
    # surfaced explicitly rather than silently degrading to plan=None.
    return min(
        candidates,
        key=lambda gap: (
            0 if is_chase_eligible(gap) else 1,
            zone_distance(gap),
            0 if gap.status == "PARTIAL" else 1,
            -gap.lower if direction == "LONG" else gap.upper,
        ),
    )


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
    """Explicit DEMO technical-scalping trade-plan builder.

    The builder prefers the nearest OPEN/PARTIAL directional FVG that is still
    inside the configured hard chase limit. If every FVG is already chased, it
    preserves the nearest stale plan so CHASE_BLOCK remains observable.

    A TP2 fallback is created only after at least one structural liquidity
    target exists. Zero-target geometry remains fail-closed.
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
