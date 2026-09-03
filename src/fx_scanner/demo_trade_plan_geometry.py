from __future__ import annotations

from math import isfinite

from .liquidity import FairValueGap, OrderBlock
from .strategy import TradePlan
from .technical import atr


def _zone_distance(lower: float, upper: float, current_price: float) -> float:
    if lower <= current_price <= upper:
        return 0.0
    if current_price < lower:
        return lower - current_price
    return current_price - upper


def _zone_chase(
    direction: str,
    lower: float,
    upper: float,
    current_price: float,
    current_atr: float,
) -> float:
    if direction == "LONG":
        return max(0.0, float(current_price) - float(upper)) / current_atr
    return max(0.0, float(lower) - float(current_price)) / current_atr


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

    def chase_distance(gap: FairValueGap) -> float:
        if current_atr is None or current_atr <= 0:
            return 0.0
        return _zone_chase(
            direction,
            float(gap.lower),
            float(gap.upper),
            current_price,
            current_atr,
        )

    def is_chase_eligible(gap: FairValueGap) -> bool:
        if max_chase_atr is None or current_atr is None or current_atr <= 0:
            return True
        return chase_distance(gap) <= float(max_chase_atr)

    return min(
        candidates,
        key=lambda gap: (
            0 if is_chase_eligible(gap) else 1,
            _zone_distance(float(gap.lower), float(gap.upper), current_price),
            0 if gap.status == "PARTIAL" else 1,
            -gap.lower if direction == "LONG" else gap.upper,
        ),
    )


def _nearest_directional_order_block(
    direction: str,
    liquidity,
    current_price: float,
    *,
    current_atr: float,
    max_chase_atr: float,
) -> OrderBlock | None:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    candidates = [
        block
        for block in liquidity.order_blocks
        if block.direction == wanted
        and block.caused_break
        and not block.invalidated
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda block: (
            0
            if _zone_chase(
                direction,
                float(block.lower),
                float(block.upper),
                current_price,
                current_atr,
            ) <= float(max_chase_atr)
            else 1,
            _zone_distance(float(block.lower), float(block.upper), current_price),
            0 if block.mitigated else 1,
            -block.lower if direction == "LONG" else block.upper,
        ),
    )


def _breakout_retest_zone(
    direction: str,
    m15,
    *,
    current_atr: float,
    minimum_entry_zone_atr: float,
) -> tuple[float, float] | None:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    if m15.bos != wanted:
        return None

    level = m15.last_swing_high if direction == "LONG" else m15.last_swing_low
    if level is None or not isfinite(float(level)) or float(level) <= 0:
        return None

    half_width = max(
        current_atr * float(minimum_entry_zone_atr) * 0.50,
        current_atr * 0.025,
    )
    lower = float(level) - half_width
    upper = float(level) + half_width
    if lower <= 0 or upper <= lower:
        return None
    return lower, upper


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

    Entry-zone priority is directional OPEN/PARTIAL FVG, then a valid
    break-causing order block, then an M15 BOS retest zone. Every path uses the
    same hard chase limit and the same structural-target fail-closed behavior.
    No setup path can bypass RR, chase, structure, spread, correlation, or risk
    guards in the calling strategy/execution layers.

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
    block = None
    source = "FVG"
    if gap is not None:
        raw_entry_low, raw_entry_high = float(gap.lower), float(gap.upper)
    else:
        block = _nearest_directional_order_block(
            direction,
            liquidity,
            current_price,
            current_atr=current_atr,
            max_chase_atr=float(chase_block_atr),
        )
        if block is not None:
            source = "ORDER_BLOCK"
            raw_entry_low, raw_entry_high = float(block.lower), float(block.upper)
        else:
            retest = _breakout_retest_zone(
                direction,
                m15,
                current_atr=current_atr,
                minimum_entry_zone_atr=float(minimum_entry_zone_atr),
            )
            if retest is None:
                return None
            source = "BREAKOUT_RETEST"
            raw_entry_low, raw_entry_high = retest

    if raw_entry_high - raw_entry_low < current_atr * float(minimum_entry_zone_atr):
        return None

    entry_low, entry_high = raw_entry_low, raw_entry_high
    raw_chase = _zone_chase(
        direction,
        raw_entry_low,
        raw_entry_high,
        current_price,
        current_atr,
    )
    if 0.0 < raw_chase <= float(chase_block_atr):
        if direction == "LONG":
            entry_high = float(current_price)
        else:
            entry_low = float(current_price)

    buffer = current_atr * float(sl_buffer_atr)
    tolerance = current_atr * 0.05

    if direction == "LONG":
        anchor = None
        if m15.sweep is not None and m15.sweep.valid and m15.sweep.direction == "BULLISH":
            anchor = m15.sweep.level
        if anchor is None and block is not None:
            anchor = block.lower
        if anchor is None:
            anchor = h1.last_swing_low
        if anchor is None:
            return None

        stop = min(float(anchor), raw_entry_low) - buffer
        risk = entry_high - stop
        if not isfinite(risk) or risk <= 0:
            return None
        chase = _zone_chase(direction, entry_low, entry_high, current_price, current_atr)

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
        if anchor is None and block is not None:
            anchor = block.upper
        if anchor is None:
            anchor = h1.last_swing_high
        if anchor is None:
            return None

        stop = max(float(anchor), raw_entry_high) + buffer
        risk = stop - entry_low
        if not isfinite(risk) or risk <= 0:
            return None
        chase = _zone_chase(direction, entry_low, entry_high, current_price, current_atr)

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
