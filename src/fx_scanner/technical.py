from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .exceptions import DataContractError
from .models import Bar


@dataclass(frozen=True, slots=True)
class DisplacementSignal:
    direction: str
    body_ratio: float
    range_atr_ratio: float
    close_location: float
    tick_activity_ratio: float | None
    valid: bool


@dataclass(frozen=True, slots=True)
class FVGSignal:
    direction: str
    lower: float
    upper: float
    size_atr: float
    valid: bool


@dataclass(frozen=True, slots=True)
class SweepSignal:
    direction: str
    level: float
    penetration_atr: float
    reclaimed: bool
    valid: bool


@dataclass(frozen=True, slots=True)
class StructureSnapshot:
    trend: str
    last_swing_high: float | None
    last_swing_low: float | None
    bos: str | None
    mss: str | None
    displacement: DisplacementSignal | None
    fvg: FVGSignal | None
    sweep: SweepSignal | None


def _validate_bars(bars: list[Bar], minimum: int = 3) -> None:
    if len(bars) < minimum:
        raise DataContractError(f"at least {minimum} bars are required")
    symbols = {b.symbol for b in bars}
    timeframes = {b.timeframe for b in bars}
    if len(symbols) != 1 or len(timeframes) != 1:
        raise DataContractError("technical analysis requires one symbol/timeframe")
    if any(bars[i].timestamp >= bars[i + 1].timestamp for i in range(len(bars) - 1)):
        raise DataContractError("bars must be strictly chronological")


def true_ranges(bars: list[Bar]) -> list[float]:
    _validate_bars(bars, 2)
    out: list[float] = []
    previous_close = bars[0].close
    for bar in bars:
        out.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
        previous_close = bar.close
    return out


def atr(bars: list[Bar], period: int = 14) -> float:
    if period <= 0:
        raise DataContractError("ATR period must be positive")
    ranges = true_ranges(bars)
    sample = ranges[-min(period, len(ranges)):]
    value = sum(sample) / len(sample)
    if value <= 0:
        raise DataContractError("ATR must be positive")
    return value


def detect_displacement(
    bars: list[Bar],
    *,
    atr_period: int = 14,
    body_median_period: int = 20,
    body_multiplier: float = 1.5,
    range_atr_multiplier: float = 1.2,
    close_location_min: float = 0.80,
    tick_activity_multiplier: float = 1.0,
) -> DisplacementSignal:
    _validate_bars(bars, 3)
    current = bars[-1]
    previous = bars[:-1]
    body = abs(current.close - current.open)
    bodies = [abs(b.close - b.open) for b in previous[-body_median_period:]]
    body_med = median(bodies) if bodies else 0.0
    current_atr = atr(bars, atr_period)
    candle_range = current.high - current.low
    if candle_range <= 0:
        return DisplacementSignal("NONE", 0.0, 0.0, 0.0, None, False)

    bullish = current.close > current.open
    bearish = current.close < current.open
    if bullish:
        close_location = (current.close - current.low) / candle_range
        direction = "BULLISH"
    elif bearish:
        close_location = (current.high - current.close) / candle_range
        direction = "BEARISH"
    else:
        close_location = 0.0
        direction = "NONE"

    body_ratio = body / body_med if body_med > 0 else 0.0
    range_ratio = candle_range / current_atr

    prior_ticks = [b.tick_count for b in previous[-body_median_period:]]
    tick_med = median(prior_ticks) if prior_ticks else 0.0
    tick_ratio = current.tick_count / tick_med if tick_med > 0 else None

    tick_ok = tick_ratio is None or tick_ratio >= tick_activity_multiplier
    valid = (
        direction != "NONE"
        and body_ratio >= body_multiplier
        and range_ratio >= range_atr_multiplier
        and close_location >= close_location_min
        and tick_ok
    )
    return DisplacementSignal(direction, body_ratio, range_ratio, close_location, tick_ratio, valid)


def detect_fvg(
    bars: list[Bar],
    *,
    atr_period: int = 14,
    minimum_atr: float = 0.10,
) -> FVGSignal | None:
    _validate_bars(bars, 3)
    left, _, right = bars[-3], bars[-2], bars[-1]
    current_atr = atr(bars, atr_period)
    if right.low > left.high:
        lower, upper = left.high, right.low
        size = upper - lower
        return FVGSignal("BULLISH", lower, upper, size / current_atr, size / current_atr >= minimum_atr)
    if right.high < left.low:
        lower, upper = right.high, left.low
        size = upper - lower
        return FVGSignal("BEARISH", lower, upper, size / current_atr, size / current_atr >= minimum_atr)
    return None


def _pivot_highs(bars: list[Bar], lookback: int) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i in range(lookback, len(bars) - lookback):
        value = bars[i].high
        neighborhood = [b.high for b in bars[i - lookback:i + lookback + 1]]
        if value == max(neighborhood) and neighborhood.count(value) == 1:
            out.append((i, value))
    return out


def _pivot_lows(bars: list[Bar], lookback: int) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i in range(lookback, len(bars) - lookback):
        value = bars[i].low
        neighborhood = [b.low for b in bars[i - lookback:i + lookback + 1]]
        if value == min(neighborhood) and neighborhood.count(value) == 1:
            out.append((i, value))
    return out


def detect_sweep(
    bars: list[Bar],
    *,
    lookback: int = 2,
    atr_period: int = 14,
    reclaim_bars: int = 3,
) -> SweepSignal | None:
    if reclaim_bars < 1:
        raise DataContractError("reclaim_bars must be positive")
    minimum_bars = lookback * 2 + 1 + reclaim_bars
    _validate_bars(bars, max(5, minimum_bars))
    current_atr = atr(bars, atr_period)

    # Liquidity level must be established before the sweep/reclaim window.
    # Otherwise the penetration candle itself can become the newest pivot and
    # erase the level that was actually swept.
    anchor_bars = bars[:-reclaim_bars]
    highs = _pivot_highs(anchor_bars, lookback)
    lows = _pivot_lows(anchor_bars, lookback)
    recent = bars[-reclaim_bars:]

    bearish: SweepSignal | None = None
    bullish: SweepSignal | None = None

    if highs:
        level = highs[-1][1]
        penetrators = [b for b in recent if b.high > level]
        if penetrators:
            max_high = max(b.high for b in penetrators)
            reclaimed = bars[-1].close < level
            bearish = SweepSignal("BEARISH", level, (max_high - level) / current_atr, reclaimed, reclaimed)

    if lows:
        level = lows[-1][1]
        penetrators = [b for b in recent if b.low < level]
        if penetrators:
            min_low = min(b.low for b in penetrators)
            reclaimed = bars[-1].close > level
            bullish = SweepSignal("BULLISH", level, (level - min_low) / current_atr, reclaimed, reclaimed)

    valid = [candidate for candidate in (bearish, bullish) if candidate is not None and candidate.valid]
    if len(valid) == 2:
        return SweepSignal(
            "AMBIGUOUS",
            0.0,
            max(valid[0].penetration_atr, valid[1].penetration_atr),
            False,
            False,
        )
    if len(valid) == 1:
        return valid[0]
    if bearish and bullish:
        return SweepSignal(
            "AMBIGUOUS",
            0.0,
            max(bearish.penetration_atr, bullish.penetration_atr),
            False,
            False,
        )
    return bearish or bullish


def structure_snapshot(
    bars: list[Bar],
    *,
    swing_lookback: int = 2,
    atr_period: int = 14,
    sweep_reclaim_bars: int = 3,
) -> StructureSnapshot:
    _validate_bars(bars, max(7, swing_lookback * 2 + 3))
    highs = _pivot_highs(bars, swing_lookback)
    lows = _pivot_lows(bars, swing_lookback)
    last_high = highs[-1][1] if highs else None
    last_low = lows[-1][1] if lows else None
    close = bars[-1].close

    bos: str | None = None
    if last_high is not None and close > last_high:
        bos = "BULLISH"
    elif last_low is not None and close < last_low:
        bos = "BEARISH"

    if len(highs) >= 2 and len(lows) >= 2:
        higher_high = highs[-1][1] > highs[-2][1]
        higher_low = lows[-1][1] > lows[-2][1]
        lower_high = highs[-1][1] < highs[-2][1]
        lower_low = lows[-1][1] < lows[-2][1]
        if higher_high and higher_low:
            trend = "BULLISH"
        elif lower_high and lower_low:
            trend = "BEARISH"
        else:
            trend = "RANGE"
    else:
        trend = "UNKNOWN"

    displacement = detect_displacement(bars, atr_period=atr_period)
    sweep = detect_sweep(
        bars,
        lookback=swing_lookback,
        atr_period=atr_period,
        reclaim_bars=sweep_reclaim_bars,
    )
    mss: str | None = None
    if (
        bos == "BULLISH"
        and sweep is not None and sweep.valid and sweep.direction == "BULLISH"
        and displacement.valid and displacement.direction == "BULLISH"
    ):
        mss = "BULLISH"
    elif (
        bos == "BEARISH"
        and sweep is not None and sweep.valid and sweep.direction == "BEARISH"
        and displacement.valid and displacement.direction == "BEARISH"
    ):
        mss = "BEARISH"

    return StructureSnapshot(
        trend=trend,
        last_swing_high=last_high,
        last_swing_low=last_low,
        bos=bos,
        mss=mss,
        displacement=displacement,
        fvg=detect_fvg(bars, atr_period=atr_period),
        sweep=sweep,
    )
