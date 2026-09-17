from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .models import Bar, ensure_utc

ICT_LAYER_CONTRACT = "ICT_XAU_M15_EXECUTION_CONTEXT_V1"
SYMBOL = "XAUUSD"
NY_TZ = ZoneInfo("America/New_York")
DEALING_RANGE_LOOKBACK = 32
ENTRY_PATTERN_LOOKBACK = 14
LIQUIDITY_SWEEP_LOOKBACK = 8
MIN_SESSION_BARS = 4
DISPLACEMENT_BODY_ATR = 0.80
OTE_MIN = 0.62
OTE_MAX = 0.79


@dataclass(frozen=True, slots=True)
class IctExecutionContext:
    contract: str
    direction: str
    available: bool
    execution_ready: bool
    reasons: tuple[str, ...]
    previous_day_high: float | None
    previous_day_low: float | None
    asian_high: float | None
    asian_low: float | None
    london_high: float | None
    london_low: float | None
    new_york_high: float | None
    new_york_low: float | None
    swept_liquidity: tuple[str, ...]
    dealing_range_low: float | None
    dealing_range_high: float | None
    equilibrium: float | None
    dealing_range_position: float | None
    premium_discount_ok: bool
    ote_low: float | None
    ote_high: float | None
    ote_retest: bool
    order_block_low: float | None
    order_block_high: float | None
    order_block_retest: bool
    fvg_low: float | None
    fvg_high: float | None
    fvg_retest: bool
    internal_liquidity_target: float | None
    external_liquidity_target: float | None
    confluence_count: int
    anti_chase_ok: bool

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _completed_rows(bars: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(bars, key=lambda item: ensure_utc(item.timestamp))
        if str(row.symbol).upper() == SYMBOL
        and str(row.timeframe).upper() == "M15"
        and ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )


def _previous_trading_day_levels(rows: Sequence[Bar], *, as_of: datetime) -> tuple[float | None, float | None]:
    current_date = ensure_utc(as_of).astimezone(NY_TZ).date()
    grouped: dict[date, list[Bar]] = {}
    for row in rows:
        local_date = ensure_utc(row.timestamp).astimezone(NY_TZ).date()
        if local_date < current_date:
            grouped.setdefault(local_date, []).append(row)
    if not grouped:
        return None, None
    prior = max(grouped)
    day_rows = grouped[prior]
    return max(float(row.high) for row in day_rows), min(float(row.low) for row in day_rows)


def _session_range(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
    end_hour: int,
    duration_hours: int,
) -> tuple[float | None, float | None]:
    now_local = ensure_utc(as_of).astimezone(NY_TZ)
    for offset in range(0, 6):
        session_day = now_local.date() - timedelta(days=offset)
        end_local = datetime.combine(session_day, time(hour=end_hour), tzinfo=NY_TZ)
        start_local = end_local - timedelta(hours=duration_hours)
        if end_local > now_local:
            continue
        selected = [
            row
            for row in rows
            if start_local <= ensure_utc(row.timestamp).astimezone(NY_TZ) < end_local
        ]
        if len(selected) >= MIN_SESSION_BARS:
            return max(float(row.high) for row in selected), min(float(row.low) for row in selected)
    return None, None


def _overlaps(bar: Bar, low: float | None, high: float | None) -> bool:
    if low is None or high is None:
        return False
    zone_low, zone_high = sorted((float(low), float(high)))
    return float(bar.low) <= zone_high and float(bar.high) >= zone_low


def _recent_fvg(rows: Sequence[Bar], *, direction: str) -> tuple[float | None, float | None]:
    start = max(2, len(rows) - ENTRY_PATTERN_LOOKBACK)
    latest: tuple[float, float] | None = None
    for index in range(start, len(rows)):
        left = rows[index - 2]
        current = rows[index]
        if direction == "LONG" and float(current.low) > float(left.high):
            latest = (float(left.high), float(current.low))
        elif direction == "SHORT" and float(current.high) < float(left.low):
            latest = (float(current.high), float(left.low))
    return latest if latest is not None else (None, None)


def _recent_order_block(
    rows: Sequence[Bar],
    *,
    direction: str,
    atr_value: float,
) -> tuple[float | None, float | None]:
    start = max(2, len(rows) - ENTRY_PATTERN_LOOKBACK)
    displacement_index: int | None = None
    for index in range(start, len(rows)):
        row = rows[index]
        body = abs(float(row.close) - float(row.open))
        candle_range = max(float(row.high) - float(row.low), 1e-12)
        if direction == "LONG":
            close_location = (float(row.close) - float(row.low)) / candle_range
            directional = float(row.close) > float(row.open) and close_location >= 0.70
        else:
            close_location = (float(row.high) - float(row.close)) / candle_range
            directional = float(row.close) < float(row.open) and close_location >= 0.70
        if directional and body >= DISPLACEMENT_BODY_ATR * atr_value:
            displacement_index = index
    if displacement_index is None:
        return None, None

    for index in range(displacement_index - 1, max(-1, displacement_index - 7), -1):
        row = rows[index]
        opposite = (
            float(row.close) < float(row.open)
            if direction == "LONG"
            else float(row.close) > float(row.open)
        )
        if opposite:
            return float(row.low), float(row.high)
    return None, None


def _ote_zone(rows: Sequence[Bar], *, direction: str) -> tuple[float | None, float | None]:
    recent = tuple(rows[-ENTRY_PATTERN_LOOKBACK:])
    if len(recent) < 4:
        return None, None
    if direction == "LONG":
        high_index = max(range(len(recent)), key=lambda idx: float(recent[idx].high))
        if high_index <= 0:
            return None, None
        swing_high = float(recent[high_index].high)
        swing_low = min(float(row.low) for row in recent[: high_index + 1])
        leg = swing_high - swing_low
        if leg <= 0.0:
            return None, None
        return swing_high - OTE_MAX * leg, swing_high - OTE_MIN * leg

    low_index = min(range(len(recent)), key=lambda idx: float(recent[idx].low))
    if low_index <= 0:
        return None, None
    swing_low = float(recent[low_index].low)
    swing_high = max(float(row.high) for row in recent[: low_index + 1])
    leg = swing_high - swing_low
    if leg <= 0.0:
        return None, None
    return swing_low + OTE_MIN * leg, swing_low + OTE_MAX * leg


def _pivot_targets(rows: Sequence[Bar], *, direction: str, price: float) -> float | None:
    recent = tuple(rows[-24:])
    pivots: list[float] = []
    for index in range(2, len(recent) - 2):
        center = recent[index]
        if direction == "LONG":
            value = float(center.high)
            if all(value >= float(recent[index + delta].high) for delta in (-2, -1, 1, 2)) and value > price:
                pivots.append(value)
        else:
            value = float(center.low)
            if all(value <= float(recent[index + delta].low) for delta in (-2, -1, 1, 2)) and value < price:
                pivots.append(value)
    if not pivots:
        return None
    return min(pivots) if direction == "LONG" else max(pivots)


def _external_target(
    *,
    direction: str,
    price: float,
    previous_day_high: float | None,
    previous_day_low: float | None,
    asian_high: float | None,
    asian_low: float | None,
    london_high: float | None,
    london_low: float | None,
    new_york_high: float | None,
    new_york_low: float | None,
    dealing_high: float,
    dealing_low: float,
) -> float | None:
    if direction == "LONG":
        candidates = [
            previous_day_high,
            asian_high,
            london_high,
            new_york_high,
            dealing_high,
        ]
        valid = [float(value) for value in candidates if value is not None and float(value) > price]
        return min(valid) if valid else None
    candidates = [
        previous_day_low,
        asian_low,
        london_low,
        new_york_low,
        dealing_low,
    ]
    valid = [float(value) for value in candidates if value is not None and float(value) < price]
    return max(valid) if valid else None


def _swept_liquidity(
    rows: Sequence[Bar],
    *,
    direction: str,
    levels: dict[str, float | None],
) -> tuple[str, ...]:
    recent = tuple(rows[-LIQUIDITY_SWEEP_LOOKBACK:])
    swept: list[str] = []
    for name, value in levels.items():
        if value is None:
            continue
        level = float(value)
        for row in recent:
            if direction == "LONG":
                if float(row.low) < level and float(row.close) > level:
                    swept.append(name)
                    break
            else:
                if float(row.high) > level and float(row.close) < level:
                    swept.append(name)
                    break
    return tuple(sorted(set(swept)))


def evaluate_ict_execution_context(
    m15_bars: Sequence[Bar],
    *,
    direction: str,
    atr_value: float,
    as_of: datetime,
) -> IctExecutionContext:
    if direction not in {"LONG", "SHORT"} or not isfinite(float(atr_value)) or float(atr_value) <= 0.0:
        return IctExecutionContext(
            ICT_LAYER_CONTRACT,
            direction,
            False,
            False,
            ("INVALID_DIRECTION_OR_ATR",),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (),
            None,
            None,
            None,
            None,
            False,
            None,
            None,
            False,
            None,
            None,
            False,
            None,
            None,
            False,
            None,
            None,
            0,
            False,
        )

    rows = _completed_rows(m15_bars, as_of=as_of)
    if len(rows) < DEALING_RANGE_LOOKBACK:
        return IctExecutionContext(
            ICT_LAYER_CONTRACT,
            direction,
            False,
            False,
            ("INSUFFICIENT_M15_HISTORY",),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (),
            None,
            None,
            None,
            None,
            False,
            None,
            None,
            False,
            None,
            None,
            False,
            None,
            None,
            False,
            None,
            None,
            0,
            False,
        )

    current = rows[-1]
    price = float(current.close)
    previous_day_high, previous_day_low = _previous_trading_day_levels(rows, as_of=as_of)
    asian_high, asian_low = _session_range(rows, as_of=as_of, end_hour=0, duration_hours=4)
    london_high, london_low = _session_range(rows, as_of=as_of, end_hour=5, duration_hours=3)
    new_york_high, new_york_low = _session_range(rows, as_of=as_of, end_hour=10, duration_hours=3)

    dealing = rows[-DEALING_RANGE_LOOKBACK:]
    dealing_low = min(float(row.low) for row in dealing)
    dealing_high = max(float(row.high) for row in dealing)
    dealing_width = dealing_high - dealing_low
    equilibrium = dealing_low + 0.50 * dealing_width
    position = None if dealing_width <= 0.0 else (price - dealing_low) / dealing_width

    if direction == "LONG":
        premium_discount_ok = float(current.low) <= equilibrium
        anti_chase_ok = position is not None and position <= 0.80
    else:
        premium_discount_ok = float(current.high) >= equilibrium
        anti_chase_ok = position is not None and position >= 0.20

    ote_low, ote_high = _ote_zone(rows, direction=direction)
    ote_retest = _overlaps(current, ote_low, ote_high)
    ob_low, ob_high = _recent_order_block(rows, direction=direction, atr_value=float(atr_value))
    order_block_retest = _overlaps(current, ob_low, ob_high)
    fvg_low, fvg_high = _recent_fvg(rows, direction=direction)
    fvg_retest = _overlaps(current, fvg_low, fvg_high)

    sweep_levels = {
        "PDL" if direction == "LONG" else "PDH": previous_day_low if direction == "LONG" else previous_day_high,
        "ASIA_LOW" if direction == "LONG" else "ASIA_HIGH": asian_low if direction == "LONG" else asian_high,
        "LONDON_LOW" if direction == "LONG" else "LONDON_HIGH": london_low if direction == "LONG" else london_high,
        "NEW_YORK_LOW" if direction == "LONG" else "NEW_YORK_HIGH": new_york_low if direction == "LONG" else new_york_high,
    }
    swept = _swept_liquidity(rows, direction=direction, levels=sweep_levels)

    internal_target = _pivot_targets(rows, direction=direction, price=price)
    external_target = _external_target(
        direction=direction,
        price=price,
        previous_day_high=previous_day_high,
        previous_day_low=previous_day_low,
        asian_high=asian_high,
        asian_low=asian_low,
        london_high=london_high,
        london_low=london_low,
        new_york_high=new_york_high,
        new_york_low=new_york_low,
        dealing_high=dealing_high,
        dealing_low=dealing_low,
    )

    context_available = previous_day_high is not None and previous_day_low is not None
    location_ok = bool(premium_discount_ok or ote_retest)
    confluence_count = sum(
        int(flag)
        for flag in (
            ote_retest,
            order_block_retest,
            fvg_retest,
            bool(swept),
        )
    )

    reasons: list[str] = []
    if not context_available:
        reasons.append("PREVIOUS_DAY_LIQUIDITY_UNAVAILABLE")
    if not location_ok:
        reasons.append("PREMIUM_DISCOUNT_OR_OTE_LOCATION_REQUIRED")
    if not (order_block_retest or fvg_retest):
        reasons.append("ORDER_BLOCK_OR_FVG_RETEST_REQUIRED")
    if external_target is None:
        reasons.append("EXTERNAL_LIQUIDITY_TARGET_UNAVAILABLE")
    if not anti_chase_ok:
        reasons.append("ICT_ANTI_CHASE_BLOCK")
    if confluence_count < 2:
        reasons.append("ICT_MIN_CONFLUENCE_NOT_MET")

    execution_ready = not reasons
    return IctExecutionContext(
        contract=ICT_LAYER_CONTRACT,
        direction=direction,
        available=True,
        execution_ready=execution_ready,
        reasons=tuple(reasons),
        previous_day_high=previous_day_high,
        previous_day_low=previous_day_low,
        asian_high=asian_high,
        asian_low=asian_low,
        london_high=london_high,
        london_low=london_low,
        new_york_high=new_york_high,
        new_york_low=new_york_low,
        swept_liquidity=swept,
        dealing_range_low=dealing_low,
        dealing_range_high=dealing_high,
        equilibrium=equilibrium,
        dealing_range_position=position,
        premium_discount_ok=premium_discount_ok,
        ote_low=ote_low,
        ote_high=ote_high,
        ote_retest=ote_retest,
        order_block_low=ob_low,
        order_block_high=ob_high,
        order_block_retest=order_block_retest,
        fvg_low=fvg_low,
        fvg_high=fvg_high,
        fvg_retest=fvg_retest,
        internal_liquidity_target=internal_target,
        external_liquidity_target=external_target,
        confluence_count=confluence_count,
        anti_chase_ok=anti_chase_ok,
    )
