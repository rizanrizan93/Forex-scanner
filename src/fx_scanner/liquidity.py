from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .exceptions import DataContractError
from .models import Bar, ensure_utc
from .sessions import active_sessions
from .technical import atr, detect_displacement


class LiquidityKind(StrEnum):
    PDH = "PDH"
    PDL = "PDL"
    PWH = "PWH"
    PWL = "PWL"
    ASIA_HIGH = "ASIA_HIGH"
    ASIA_LOW = "ASIA_LOW"
    LONDON_HIGH = "LONDON_HIGH"
    LONDON_LOW = "LONDON_LOW"
    NEW_YORK_HIGH = "NEW_YORK_HIGH"
    NEW_YORK_LOW = "NEW_YORK_LOW"
    EQUAL_HIGH = "EQUAL_HIGH"
    EQUAL_LOW = "EQUAL_LOW"
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    kind: LiquidityKind
    price: float
    observed_at: datetime
    touches: int = 1
    strength: float = 1.0
    active: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.price, bool) or not isfinite(float(self.price)) or self.price <= 0:
            raise DataContractError("liquidity level price must be positive finite")
        object.__setattr__(self, "price", float(self.price))
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        if isinstance(self.touches, bool) or self.touches <= 0:
            raise DataContractError("liquidity level touches must be positive integer")
        if not isinstance(self.active, bool):
            raise DataContractError("liquidity level active must be boolean")
        if isinstance(self.strength, bool) or not isfinite(float(self.strength)) or self.strength < 0:
            raise DataContractError("liquidity level strength must be non-negative finite")


@dataclass(frozen=True, slots=True)
class DealingRange:
    low: float
    high: float
    equilibrium: float
    location: float
    zone: str

    def __post_init__(self) -> None:
        if any(isinstance(x, bool) for x in (self.low, self.high, self.equilibrium, self.location)):
            raise DataContractError("dealing range values cannot be boolean")
        if not (isfinite(self.low) and isfinite(self.high)) or self.low <= 0 or self.high <= self.low:
            raise DataContractError("dealing range is invalid")
        if not 0 <= self.location <= 1:
            raise DataContractError("dealing range location must be in [0,1]")
        if not self.low < self.equilibrium < self.high:
            raise DataContractError("dealing range equilibrium must be inside range")
        expected_equilibrium = (self.low + self.high) / 2.0
        if abs(self.equilibrium - expected_equilibrium) > 1e-9:
            raise DataContractError("dealing range equilibrium mismatch")
        if self.zone not in {"DISCOUNT", "EQUILIBRIUM", "PREMIUM"}:
            raise DataContractError("dealing range zone is invalid")


@dataclass(frozen=True, slots=True)
class FairValueGap:
    direction: str
    lower: float
    upper: float
    origin_at: datetime
    status: str
    fill_fraction: float

    def __post_init__(self) -> None:
        if any(isinstance(x, bool) for x in (self.lower, self.upper, self.fill_fraction)):
            raise DataContractError("FVG numeric values cannot be boolean")
        if self.direction not in {"BULLISH", "BEARISH"}:
            raise DataContractError("FVG direction is invalid")
        if not (0 < self.lower < self.upper):
            raise DataContractError("FVG bounds are invalid")
        object.__setattr__(self, "origin_at", ensure_utc(self.origin_at))
        if self.status not in {"OPEN", "PARTIAL", "FILLED"}:
            raise DataContractError("FVG status is invalid")
        if not 0 <= self.fill_fraction <= 1:
            raise DataContractError("FVG fill_fraction must be in [0,1]")


@dataclass(frozen=True, slots=True)
class OrderBlock:
    direction: str
    lower: float
    upper: float
    origin_at: datetime
    displacement_at: datetime
    caused_break: bool
    mitigated: bool
    invalidated: bool

    def __post_init__(self) -> None:
        if any(isinstance(x, bool) for x in (self.lower, self.upper)):
            raise DataContractError("order-block bounds cannot be boolean")
        if not all(isinstance(x, bool) for x in (self.caused_break, self.mitigated, self.invalidated)):
            raise DataContractError("order-block flags must be boolean")
        if self.direction not in {"BULLISH", "BEARISH"}:
            raise DataContractError("order-block direction is invalid")
        if not (0 < self.lower < self.upper):
            raise DataContractError("order-block bounds are invalid")
        object.__setattr__(self, "origin_at", ensure_utc(self.origin_at))
        object.__setattr__(self, "displacement_at", ensure_utc(self.displacement_at))


@dataclass(frozen=True, slots=True)
class LiquidityMap:
    symbol: str
    observed_at: datetime
    levels: tuple[LiquidityLevel, ...]
    dealing_range: DealingRange | None
    fvgs: tuple[FairValueGap, ...]
    order_blocks: tuple[OrderBlock, ...]

    def __post_init__(self) -> None:
        symbol = str(self.symbol).upper().strip()
        if len(symbol) != 6:
            raise DataContractError("liquidity-map symbol must be a six-character FX pair")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        if any(level.observed_at > self.observed_at for level in self.levels):
            raise DataContractError("liquidity level cannot be observed in the future")
        if any(gap.origin_at > self.observed_at for gap in self.fvgs):
            raise DataContractError("FVG origin cannot be in the future")
        if any(block.origin_at > self.observed_at or block.displacement_at > self.observed_at for block in self.order_blocks):
            raise DataContractError("order-block evidence cannot be in the future")

    def levels_above(self, price: float) -> tuple[LiquidityLevel, ...]:
        return tuple(sorted((x for x in self.levels if x.active and x.price > price), key=lambda x: x.price))

    def levels_below(self, price: float) -> tuple[LiquidityLevel, ...]:
        return tuple(sorted((x for x in self.levels if x.active and x.price < price), key=lambda x: x.price, reverse=True))


def _validate_series(bars: Sequence[Bar], timeframe: str | None = None, minimum: int = 1) -> None:
    if len(bars) < minimum:
        raise DataContractError(f"at least {minimum} bars are required")
    symbols = {b.symbol for b in bars}
    tfs = {b.timeframe for b in bars}
    if len(symbols) != 1 or len(tfs) != 1:
        raise DataContractError("liquidity analysis requires one symbol/timeframe")
    if timeframe is not None and next(iter(tfs)) != timeframe.upper():
        raise DataContractError(f"expected {timeframe} bars")
    if any(bars[i].timestamp >= bars[i + 1].timestamp for i in range(len(bars) - 1)):
        raise DataContractError("bars must be strictly chronological")


def _pivots(bars: Sequence[Bar], lookback: int, high: bool) -> list[tuple[int, float]]:
    if lookback < 1:
        raise DataContractError("pivot lookback must be positive")
    attr = "high" if high else "low"
    out: list[tuple[int, float]] = []
    for i in range(lookback, len(bars) - lookback):
        value = float(getattr(bars[i], attr))
        values = [float(getattr(x, attr)) for x in bars[i - lookback:i + lookback + 1]]
        extreme = max(values) if high else min(values)
        if value == extreme and values.count(value) == 1:
            out.append((i, value))
    return out


def previous_day_levels(d1_bars: Sequence[Bar], *, as_of: datetime) -> tuple[LiquidityLevel, ...]:
    _validate_series(d1_bars, "D1", 1)
    cutoff = ensure_utc(as_of)
    completed = [b for b in d1_bars if b.timestamp.date() < cutoff.date()]
    if not completed:
        return ()
    bar = completed[-1]
    return (
        LiquidityLevel(LiquidityKind.PDH, bar.high, bar.timestamp),
        LiquidityLevel(LiquidityKind.PDL, bar.low, bar.timestamp),
    )


def previous_week_levels(d1_bars: Sequence[Bar], *, as_of: datetime) -> tuple[LiquidityLevel, ...]:
    _validate_series(d1_bars, "D1", 2)
    cutoff = ensure_utc(as_of)
    current_week = cutoff.isocalendar()[:2]
    groups: dict[tuple[int, int], list[Bar]] = {}
    for bar in d1_bars:
        if bar.timestamp >= cutoff:
            continue
        key = bar.timestamp.isocalendar()[:2]
        if key == current_week:
            continue
        groups.setdefault(key, []).append(bar)
    if not groups:
        return ()
    latest_key = max(groups)
    week = groups[latest_key]
    observed = max(b.timestamp for b in week)
    return (
        LiquidityLevel(LiquidityKind.PWH, max(b.high for b in week), observed),
        LiquidityLevel(LiquidityKind.PWL, min(b.low for b in week), observed),
    )


def equal_levels(
    bars: Sequence[Bar],
    *,
    atr_period: int = 14,
    pivot_lookback: int = 2,
    tolerance_atr: float = 0.15,
    minimum_touches: int = 2,
    scan_bars: int = 80,
) -> tuple[LiquidityLevel, ...]:
    _validate_series(bars, minimum=max(atr_period, pivot_lookback * 2 + 1))
    if not 0 < tolerance_atr <= 1 or minimum_touches < 2 or scan_bars < 5:
        raise DataContractError("equal-level parameters are invalid")
    sample = list(bars[-scan_bars:])
    current_atr = atr(sample, atr_period)
    tolerance = current_atr * tolerance_atr

    def cluster(points: list[tuple[int, float]], kind: LiquidityKind) -> list[LiquidityLevel]:
        levels: list[LiquidityLevel] = []
        used: set[int] = set()
        for idx, (_, price) in enumerate(points):
            if idx in used:
                continue
            group = [(idx, price)]
            for j in range(idx + 1, len(points)):
                if j in used:
                    continue
                if abs(points[j][1] - price) <= tolerance:
                    group.append((j, points[j][1]))
            if len(group) < minimum_touches:
                continue
            used.update(x[0] for x in group)
            avg = sum(x[1] for x in group) / len(group)
            last_point_index = points[max(x[0] for x in group)][0]
            observed_at = sample[last_point_index].timestamp
            levels.append(
                LiquidityLevel(
                    kind,
                    avg,
                    observed_at,
                    touches=len(group),
                    strength=min(1.0, len(group) / 4.0),
                )
            )
        return levels

    highs = _pivots(sample, pivot_lookback, True)
    lows = _pivots(sample, pivot_lookback, False)
    return tuple(cluster(highs, LiquidityKind.EQUAL_HIGH) + cluster(lows, LiquidityKind.EQUAL_LOW))


def _session_kind(name: str, high: bool) -> LiquidityKind:
    mapping = {
        ("ASIA", True): LiquidityKind.ASIA_HIGH,
        ("ASIA", False): LiquidityKind.ASIA_LOW,
        ("LONDON", True): LiquidityKind.LONDON_HIGH,
        ("LONDON", False): LiquidityKind.LONDON_LOW,
        ("NEW_YORK", True): LiquidityKind.NEW_YORK_HIGH,
        ("NEW_YORK", False): LiquidityKind.NEW_YORK_LOW,
    }
    return mapping[(name, high)]


def previous_session_levels(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    session_config: Mapping,
) -> tuple[LiquidityLevel, ...]:
    _validate_series(bars, minimum=2)
    now = ensure_utc(as_of)
    output: list[LiquidityLevel] = []
    for name, cfg in session_config["sessions"].items():
        if name not in {"ASIA", "LONDON", "NEW_YORK"}:
            continue
        zone = ZoneInfo(cfg["timezone"])
        groups: dict[object, list[Bar]] = {}
        for bar in bars:
            if bar.timestamp >= now:
                continue
            if name not in active_sessions(bar.timestamp, session_config):
                continue
            local_date = bar.timestamp.astimezone(zone).date()
            groups.setdefault(local_date, []).append(bar)
        if not groups:
            continue
        current_local_date = now.astimezone(zone).date()
        if name in active_sessions(now, session_config):
            groups.pop(current_local_date, None)
        if not groups:
            continue
        date_key = max(groups)
        group = groups[date_key]
        observed = max(b.timestamp for b in group)
        output.extend(
            (
                LiquidityLevel(_session_kind(name, True), max(b.high for b in group), observed),
                LiquidityLevel(_session_kind(name, False), min(b.low for b in group), observed),
            )
        )
    return tuple(output)


def dealing_range(
    bars: Sequence[Bar],
    *,
    current_price: float,
    pivot_lookback: int = 2,
    equilibrium_band: float = 0.05,
) -> DealingRange | None:
    _validate_series(bars, minimum=pivot_lookback * 2 + 3)
    if not 0 <= equilibrium_band < 0.5:
        raise DataContractError("equilibrium_band must be in [0,0.5)")
    highs = _pivots(bars, pivot_lookback, True)
    lows = _pivots(bars, pivot_lookback, False)
    if not highs or not lows:
        return None
    high = highs[-1][1]
    low = lows[-1][1]
    if low >= high:
        return None
    location = max(0.0, min(1.0, (current_price - low) / (high - low)))
    if location < 0.5 - equilibrium_band:
        zone = "DISCOUNT"
    elif location > 0.5 + equilibrium_band:
        zone = "PREMIUM"
    else:
        zone = "EQUILIBRIUM"
    return DealingRange(low, high, (low + high) / 2.0, location, zone)


def scan_fvgs(
    bars: Sequence[Bar],
    *,
    atr_period: int = 14,
    minimum_atr: float = 0.10,
    scan_bars: int = 60,
) -> tuple[FairValueGap, ...]:
    _validate_series(bars, minimum=max(atr_period, 3))
    sample = list(bars[-scan_bars:])
    current_atr = atr(sample, atr_period)
    out: list[FairValueGap] = []
    for i in range(2, len(sample)):
        left, right = sample[i - 2], sample[i]
        direction: str | None = None
        lower = upper = 0.0
        if right.low > left.high:
            direction, lower, upper = "BULLISH", left.high, right.low
        elif right.high < left.low:
            direction, lower, upper = "BEARISH", right.high, left.low
        if direction is None or (upper - lower) / current_atr < minimum_atr:
            continue
        later = sample[i + 1:]
        fill_fraction = 0.0
        if direction == "BULLISH":
            deepest = min((b.low for b in later), default=upper)
            fill_fraction = max(0.0, min(1.0, (upper - deepest) / (upper - lower)))
        else:
            highest = max((b.high for b in later), default=lower)
            fill_fraction = max(0.0, min(1.0, (highest - lower) / (upper - lower)))
        status = "FILLED" if fill_fraction >= 1.0 else "PARTIAL" if fill_fraction > 0 else "OPEN"
        out.append(FairValueGap(direction, lower, upper, right.timestamp, status, fill_fraction))
    return tuple(out)


def scan_order_blocks(
    bars: Sequence[Bar],
    *,
    atr_period: int = 14,
    search_bars: int = 40,
    origin_lookback: int = 5,
) -> tuple[OrderBlock, ...]:
    _validate_series(bars, minimum=max(atr_period + 3, origin_lookback + 3))
    sample = list(bars[-search_bars:])
    out: list[OrderBlock] = []
    for i in range(max(3, origin_lookback), len(sample)):
        prefix = sample[: i + 1]
        signal = detect_displacement(prefix, atr_period=min(atr_period, max(2, len(prefix) - 1)))
        if not signal.valid:
            continue
        displacement_bar = sample[i]
        prior = sample[max(0, i - origin_lookback):i]
        if signal.direction == "BULLISH":
            structure_high = max(b.high for b in sample[max(0, i - origin_lookback - 3):i])
            caused_break = displacement_bar.close > structure_high
            candidates = [b for b in reversed(prior) if b.close < b.open]
        else:
            structure_low = min(b.low for b in sample[max(0, i - origin_lookback - 3):i])
            caused_break = displacement_bar.close < structure_low
            candidates = [b for b in reversed(prior) if b.close > b.open]
        if not caused_break or not candidates:
            continue
        origin = candidates[0]
        lower, upper = origin.low, origin.high
        later = sample[i + 1:]
        if signal.direction == "BULLISH":
            mitigated = any(b.low <= upper and b.high >= lower for b in later)
            invalidated = any(b.close < lower for b in later)
        else:
            mitigated = any(b.high >= lower and b.low <= upper for b in later)
            invalidated = any(b.close > upper for b in later)
        out.append(
            OrderBlock(
                signal.direction,
                lower,
                upper,
                origin.timestamp,
                displacement_bar.timestamp,
                True,
                mitigated,
                invalidated,
            )
        )
    return tuple(out)


def build_liquidity_map(
    *,
    d1_bars: Sequence[Bar],
    h1_bars: Sequence[Bar],
    intraday_bars: Sequence[Bar],
    as_of: datetime,
    current_price: float,
    session_config: Mapping,
    pivot_lookback: int = 2,
    atr_period: int = 14,
    tolerance_atr: float = 0.15,
    minimum_touches: int = 2,
    equal_scan_bars: int = 80,
    equilibrium_band: float = 0.05,
    fvg_scan_bars: int = 60,
    order_block_search_bars: int = 40,
    order_block_origin_lookback: int = 5,
) -> LiquidityMap:
    _validate_series(d1_bars, "D1", 2)
    _validate_series(h1_bars, "H1", max(atr_period, 7))
    _validate_series(intraday_bars, minimum=max(atr_period, 7))
    symbols = {d1_bars[0].symbol, h1_bars[0].symbol, intraday_bars[0].symbol}
    if len(symbols) != 1:
        raise DataContractError("liquidity map inputs must use one symbol")

    levels = list(previous_day_levels(d1_bars, as_of=as_of))
    levels.extend(previous_week_levels(d1_bars, as_of=as_of))
    levels.extend(previous_session_levels(intraday_bars, as_of=as_of, session_config=session_config))
    levels.extend(
        equal_levels(
            h1_bars,
            atr_period=atr_period,
            pivot_lookback=pivot_lookback,
            tolerance_atr=tolerance_atr,
            minimum_touches=minimum_touches,
            scan_bars=equal_scan_bars,
        )
    )
    highs = _pivots(h1_bars, pivot_lookback, True)
    lows = _pivots(h1_bars, pivot_lookback, False)
    if highs:
        i, price = highs[-1]
        levels.append(LiquidityLevel(LiquidityKind.SWING_HIGH, price, h1_bars[i].timestamp))
    if lows:
        i, price = lows[-1]
        levels.append(LiquidityLevel(LiquidityKind.SWING_LOW, price, h1_bars[i].timestamp))

    observed = ensure_utc(as_of)
    return LiquidityMap(
        d1_bars[0].symbol,
        observed,
        tuple(levels),
        dealing_range(
            h1_bars,
            current_price=current_price,
            pivot_lookback=pivot_lookback,
            equilibrium_band=equilibrium_band,
        ),
        scan_fvgs(intraday_bars, atr_period=atr_period, scan_bars=fvg_scan_bars),
        scan_order_blocks(
            intraday_bars,
            atr_period=atr_period,
            search_bars=order_block_search_bars,
            origin_lookback=order_block_origin_lookback,
        ),
    )
