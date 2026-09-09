from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .models import Bar
from .technical import atr

# The brochure does not disclose its periods. This first DEMO shadow profile is
# intentionally chosen to fit the existing fast-path history budget without
# increasing cTrader request volume or changing execution behavior.
FOUR_EMA_PROFILE = "SCALP_9_20_34_50"
FOUR_EMA_PERIODS = (9, 20, 34, 50)


@dataclass(frozen=True, slots=True)
class FourEMAFeatures:
    profile: str
    periods: tuple[int, int, int, int]
    available: bool
    mature: bool
    bars_count: int
    history_multiple: float
    alignment: str
    directional_aligned: bool
    opposite_aligned: bool
    price_side_slow_ok: bool
    ema_fast: float | None
    ema_mid1: float | None
    ema_mid2: float | None
    ema_slow: float | None
    separation_atr: float | None
    prior_separation_atr: float | None
    expansion_ratio: float | None
    spread_state: str
    slope_fast_atr: float | None
    slope_mid1_atr: float | None
    slope_mid2_atr: float | None
    slope_slow_atr: float | None
    directional_slopes: bool
    pullback_distance_atr: float | None
    pullback_near_fast_cluster: bool
    brochure_periods_confirmed: bool = False
    policy_effect: str = "OBSERVATION_ONLY"

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["periods"] = list(self.periods)
        return payload


def _validate_periods(periods: Sequence[int]) -> tuple[int, int, int, int]:
    values = tuple(int(value) for value in periods)
    if len(values) != 4:
        raise ValueError("four EMA periods are required")
    if any(value <= 1 for value in values):
        raise ValueError("EMA periods must be greater than one")
    if tuple(sorted(values)) != values or len(set(values)) != 4:
        raise ValueError("EMA periods must be strictly increasing")
    return values  # type: ignore[return-value]


def _ema_series(values: Sequence[float], period: int) -> tuple[float, ...]:
    if not values:
        return ()
    alpha = 2.0 / (float(period) + 1.0)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
    return tuple(output)


def _direction_tokens(direction: str) -> tuple[str, str, float]:
    normalized = str(direction).upper().strip()
    if normalized == "LONG":
        return "BULLISH", "BEARISH", 1.0
    if normalized == "SHORT":
        return "BEARISH", "BULLISH", -1.0
    raise ValueError("direction must be LONG or SHORT")


def _empty_features(
    *,
    periods: tuple[int, int, int, int],
    bars_count: int,
    history_multiple: float,
) -> FourEMAFeatures:
    return FourEMAFeatures(
        profile=FOUR_EMA_PROFILE,
        periods=periods,
        available=False,
        mature=False,
        bars_count=bars_count,
        history_multiple=history_multiple,
        alignment="UNAVAILABLE",
        directional_aligned=False,
        opposite_aligned=False,
        price_side_slow_ok=False,
        ema_fast=None,
        ema_mid1=None,
        ema_mid2=None,
        ema_slow=None,
        separation_atr=None,
        prior_separation_atr=None,
        expansion_ratio=None,
        spread_state="UNAVAILABLE",
        slope_fast_atr=None,
        slope_mid1_atr=None,
        slope_mid2_atr=None,
        slope_slow_atr=None,
        directional_slopes=False,
        pullback_distance_atr=None,
        pullback_near_fast_cluster=False,
    )


def build_four_ema_features(
    bars: Sequence[Bar],
    *,
    direction: str,
    periods: Sequence[int] = FOUR_EMA_PERIODS,
    atr_period: int = 14,
    slope_lookback: int = 5,
    expansion_lookback: int = 5,
    pullback_cluster_atr: float = 0.25,
) -> FourEMAFeatures:
    """Build deterministic four-EMA shadow features without execution authority.

    `available` requires at least one slow-period history window. `mature` is a
    stricter two-window diagnostic and is deliberately not an execution gate.
    EMA values are normalized with ATR so symbols with different price scales
    remain comparable during DEMO calibration.
    """
    period_tuple = _validate_periods(periods)
    wanted, opposite, sign = _direction_tokens(direction)
    if slope_lookback < 1 or expansion_lookback < 1:
        raise ValueError("EMA lookbacks must be positive")
    if pullback_cluster_atr < 0:
        raise ValueError("pullback_cluster_atr cannot be negative")

    rows = tuple(bars)
    bars_count = len(rows)
    slow_period = period_tuple[-1]
    history_multiple = bars_count / float(slow_period)
    if bars_count < slow_period or bars_count < 2:
        return _empty_features(
            periods=period_tuple,
            bars_count=bars_count,
            history_multiple=history_multiple,
        )

    closes = tuple(float(bar.close) for bar in rows)
    series = tuple(_ema_series(closes, period) for period in period_tuple)
    current = tuple(values[-1] for values in series)

    if current[0] > current[1] > current[2] > current[3]:
        alignment = "BULLISH"
    elif current[0] < current[1] < current[2] < current[3]:
        alignment = "BEARISH"
    else:
        alignment = "MIXED"

    try:
        atr_value = float(atr(list(rows), atr_period))
    except Exception:
        atr_value = 0.0
    if not isfinite(atr_value) or atr_value <= 0:
        return _empty_features(
            periods=period_tuple,
            bars_count=bars_count,
            history_multiple=history_multiple,
        )

    separation = sum(abs(current[index] - current[index + 1]) for index in range(3)) / atr_value

    prior_index = max(0, len(rows) - 1 - expansion_lookback)
    prior = tuple(values[prior_index] for values in series)
    prior_separation = sum(abs(prior[index] - prior[index + 1]) for index in range(3)) / atr_value
    expansion_ratio = None
    if prior_separation > 1e-12:
        expansion_ratio = separation / prior_separation

    if expansion_ratio is None:
        spread_state = "STABLE"
    elif expansion_ratio >= 1.10:
        spread_state = "EXPANDING"
    elif expansion_ratio <= 0.90:
        spread_state = "COMPRESSING"
    else:
        spread_state = "STABLE"

    slope_index = max(0, len(rows) - 1 - slope_lookback)
    slope_denominator = atr_value * max(1, len(rows) - 1 - slope_index)
    slopes = tuple((values[-1] - values[slope_index]) / slope_denominator for values in series)
    directional_slopes = all(sign * value > 0.0 for value in slopes)

    latest_close = closes[-1]
    price_side_slow_ok = latest_close > current[3] if wanted == "BULLISH" else latest_close < current[3]
    cluster_low = min(current[0], current[1])
    cluster_high = max(current[0], current[1])
    if cluster_low <= latest_close <= cluster_high:
        pullback_distance = 0.0
    else:
        pullback_distance = min(abs(latest_close - cluster_low), abs(latest_close - cluster_high)) / atr_value

    return FourEMAFeatures(
        profile=FOUR_EMA_PROFILE,
        periods=period_tuple,
        available=True,
        mature=bars_count >= 2 * slow_period,
        bars_count=bars_count,
        history_multiple=history_multiple,
        alignment=alignment,
        directional_aligned=alignment == wanted,
        opposite_aligned=alignment == opposite,
        price_side_slow_ok=price_side_slow_ok,
        ema_fast=current[0],
        ema_mid1=current[1],
        ema_mid2=current[2],
        ema_slow=current[3],
        separation_atr=separation,
        prior_separation_atr=prior_separation,
        expansion_ratio=expansion_ratio,
        spread_state=spread_state,
        slope_fast_atr=slopes[0],
        slope_mid1_atr=slopes[1],
        slope_mid2_atr=slopes[2],
        slope_slow_atr=slopes[3],
        directional_slopes=directional_slopes,
        pullback_distance_atr=pullback_distance,
        pullback_near_fast_cluster=pullback_distance <= pullback_cluster_atr,
    )


def build_four_ema_bundle(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    *,
    direction: str,
    atr_period: int = 14,
) -> dict[str, Any]:
    timeframes: dict[str, dict[str, Any]] = {}
    for timeframe in ("H1", "M15", "M5"):
        features = build_four_ema_features(
            bars_by_timeframe.get(timeframe, ()),
            direction=direction,
            atr_period=atr_period,
        )
        timeframes[timeframe.lower()] = features.to_payload()

    available = [row for row in timeframes.values() if bool(row.get("available"))]
    directional = [row for row in available if bool(row.get("directional_aligned"))]
    mature = [row for row in available if bool(row.get("mature"))]
    return {
        "profile": FOUR_EMA_PROFILE,
        "periods": list(FOUR_EMA_PERIODS),
        "brochure_periods_confirmed": False,
        "policy_effect": "OBSERVATION_ONLY",
        "available_timeframes": len(available),
        "mature_timeframes": len(mature),
        "directional_confluence": len(directional),
        "h1": timeframes["h1"],
        "m15": timeframes["m15"],
        "m5": timeframes["m5"],
    }
