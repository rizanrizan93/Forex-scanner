from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Sequence

from .models import Bar
from .technical import atr

DONCHIAN_ATR_H1_PROFILE = "DONCHIAN_20_ATR14_H1"
DONCHIAN_LOOKBACK = 20
ATR_PERIOD = 14
BREAKOUT_BUFFER_ATR = 0.10


@dataclass(frozen=True, slots=True)
class DonchianATRH1Features:
    profile: str
    timeframe: str
    lookback: int
    atr_period: int
    breakout_buffer_atr: float
    available: bool
    mature: bool
    bars_count: int
    direction: str
    channel_upper: float | None
    channel_lower: float | None
    channel_width_atr: float | None
    atr_value: float | None
    breakout_level: float | None
    breakout_distance_atr: float | None
    breakout_triggered: bool
    close_beyond_channel: bool
    intrabar_beyond_channel: bool
    policy_effect: str = "OBSERVATION_ONLY"
    contract_version: int = 1

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_direction(direction: str) -> str:
    value = str(direction).upper().strip()
    if value not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    return value


def _empty_features(
    *,
    bars_count: int,
    direction: str,
    lookback: int,
    atr_period: int,
    breakout_buffer_atr: float,
) -> DonchianATRH1Features:
    return DonchianATRH1Features(
        profile=DONCHIAN_ATR_H1_PROFILE,
        timeframe="H1",
        lookback=lookback,
        atr_period=atr_period,
        breakout_buffer_atr=breakout_buffer_atr,
        available=False,
        mature=False,
        bars_count=bars_count,
        direction=direction,
        channel_upper=None,
        channel_lower=None,
        channel_width_atr=None,
        atr_value=None,
        breakout_level=None,
        breakout_distance_atr=None,
        breakout_triggered=False,
        close_beyond_channel=False,
        intrabar_beyond_channel=False,
    )


def build_donchian_atr_h1_features(
    bars: Sequence[Bar],
    *,
    direction: str,
    lookback: int = DONCHIAN_LOOKBACK,
    atr_period: int = ATR_PERIOD,
    breakout_buffer_atr: float = BREAKOUT_BUFFER_ATR,
) -> DonchianATRH1Features:
    """Build point-in-time Donchian/ATR H1 breakout evidence.

    The current H1 bar is excluded from the Donchian channel, preventing a
    look-ahead/self-reference error. A trigger requires the current close to
    clear the prior channel by an ATR-normalized buffer. The feature is strictly
    observation-only and has no order authority.
    """
    direction = _normalize_direction(direction)
    if int(lookback) < 2:
        raise ValueError("lookback must be >= 2")
    if int(atr_period) < 2:
        raise ValueError("atr_period must be >= 2")
    if not isfinite(float(breakout_buffer_atr)) or float(breakout_buffer_atr) < 0:
        raise ValueError("breakout_buffer_atr must be finite and >= 0")

    rows = tuple(bar for bar in bars if str(bar.timeframe).upper() == "H1")
    bars_count = len(rows)
    minimum = max(int(lookback) + 1, int(atr_period) + 1)
    if bars_count < minimum:
        return _empty_features(
            bars_count=bars_count,
            direction=direction,
            lookback=int(lookback),
            atr_period=int(atr_period),
            breakout_buffer_atr=float(breakout_buffer_atr),
        )

    current = rows[-1]
    prior = rows[-(int(lookback) + 1):-1]
    channel_upper = max(float(bar.high) for bar in prior)
    channel_lower = min(float(bar.low) for bar in prior)

    try:
        atr_value = float(atr(list(rows), int(atr_period)))
    except Exception:
        atr_value = 0.0
    if not isfinite(atr_value) or atr_value <= 0:
        return _empty_features(
            bars_count=bars_count,
            direction=direction,
            lookback=int(lookback),
            atr_period=int(atr_period),
            breakout_buffer_atr=float(breakout_buffer_atr),
        )

    buffer_abs = float(breakout_buffer_atr) * atr_value
    if direction == "LONG":
        breakout_level = channel_upper + buffer_abs
        breakout_distance_atr = (float(current.close) - channel_upper) / atr_value
        close_beyond = float(current.close) > channel_upper
        intrabar_beyond = float(current.high) > channel_upper
        triggered = float(current.close) >= breakout_level
    else:
        breakout_level = channel_lower - buffer_abs
        breakout_distance_atr = (channel_lower - float(current.close)) / atr_value
        close_beyond = float(current.close) < channel_lower
        intrabar_beyond = float(current.low) < channel_lower
        triggered = float(current.close) <= breakout_level

    return DonchianATRH1Features(
        profile=DONCHIAN_ATR_H1_PROFILE,
        timeframe="H1",
        lookback=int(lookback),
        atr_period=int(atr_period),
        breakout_buffer_atr=float(breakout_buffer_atr),
        available=True,
        mature=bars_count >= 2 * int(lookback),
        bars_count=bars_count,
        direction=direction,
        channel_upper=channel_upper,
        channel_lower=channel_lower,
        channel_width_atr=(channel_upper - channel_lower) / atr_value,
        atr_value=atr_value,
        breakout_level=breakout_level,
        breakout_distance_atr=breakout_distance_atr,
        breakout_triggered=triggered,
        close_beyond_channel=close_beyond,
        intrabar_beyond_channel=intrabar_beyond,
    )
