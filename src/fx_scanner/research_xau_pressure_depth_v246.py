from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_xau_zone_path_v174 import wilson_lower_bound
from .research_xau_zone_reversal_depth_v225 import DepthEpisode

RESEARCH_VERSION = "XAU_PRESSURE_TO_DEPTH_V246_1"
ARTIFACT_CONTRACT = "XAU_PRESSURE_TO_DEPTH_V246_1_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False

PRE_TOUCH_BARS = 8
MIN_PRE_TOUCH_BARS = 5

# Positive signed pressure means buyers dominate. Negative means sellers dominate.
# Opposing-pressure is re-oriented to the zone: positive means pressure is still
# pushing price deeper into the zone; negative means counter-pressure is already
# resisting the incoming move.
PRESSURE_BUCKETS = (
    (-100.0, -40.0, "COUNTER_STRONG"),
    (-40.0, -15.0, "COUNTER_MODERATE"),
    (-15.0, 15.0, "BALANCED"),
    (15.0, 40.0, "OPPOSING_MODERATE"),
    (40.0, 100.000001, "OPPOSING_STRONG"),
)


@dataclass(frozen=True, slots=True)
class PressureDepthEpisode:
    zone_id: str
    timeframe: str
    direction: str
    touch_at: str
    outcome: str
    reaction_hit: bool
    break_hit: bool
    turning_depth: float | None
    max_depth_reached: float
    zone_width: float
    atr_points: float
    pressure_proxy_score: float
    opposing_pressure_score: float
    opposing_pressure_bucket: str
    approach_velocity_atr_per_minute: float
    mean_body_efficiency: float
    mean_close_location: float
    pre_touch_bars: int


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def opposing_pressure_bucket(value: float) -> str:
    score = float(value)
    for low, high, label in PRESSURE_BUCKETS:
        if low <= score < high:
            return label
    return "OPPOSING_STRONG" if score >= 0 else "COUNTER_STRONG"


def _bar_force(row: pd.Series) -> tuple[float, float, float]:
    high = float(row["high"])
    low = float(row["low"])
    open_ = float(row["open"])
    close = float(row["close"])
    span = max(high - low, 1e-12)

    body_efficiency = (close - open_) / span
    close_location = ((close - low) / span) * 2.0 - 1.0
    force = 0.60 * body_efficiency + 0.40 * close_location
    return (
        _clip(force, -1.0, 1.0),
        _clip(body_efficiency, -1.0, 1.0),
        _clip(close_location, -1.0, 1.0),
    )


def pressure_features_before_touch(
    price_m1: pd.DataFrame,
    *,
    touch_at: Any,
    atr_points: float,
    bars: int = PRE_TOUCH_BARS,
) -> dict[str, Any] | None:
    """Causal OHLC pressure proxy using only completed M1 bars before first touch.

    This is not historical DOM/order-flow. HistData V193 contains OHLC only, so
    the proxy measures candle efficiency, close location and approach velocity.
    True cTrader Level-II pressure is validated separately prospectively.
    """
    stamp = pd.Timestamp(ensure_utc(pd.Timestamp(touch_at).to_pydatetime()))
    frame = price_m1.copy()
    ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    idx = int(ts.searchsorted(stamp, side="left"))
    start = max(0, idx - int(bars))
    window = frame.iloc[start:idx].copy()
    if len(window) < MIN_PRE_TOUCH_BARS:
        return None

    forces: list[float] = []
    body_eff: list[float] = []
    close_locs: list[float] = []
    for _, row in window.iterrows():
        force, body, close_loc = _bar_force(row)
        forces.append(force)
        body_eff.append(body)
        close_locs.append(close_loc)

    weights = np.arange(1, len(forces) + 1, dtype=float)
    weights /= weights.sum()
    weighted_force = float(np.dot(np.asarray(forces, dtype=float), weights))

    first_open = float(window.iloc[0]["open"])
    last_close = float(window.iloc[-1]["close"])
    atr = max(float(atr_points), 1e-12)
    velocity = (last_close - first_open) / atr / max(len(window), 1)
    velocity_component = _clip(velocity * 4.0, -1.0, 1.0)

    recent_ranges = (
        window["high"].astype(float) - window["low"].astype(float)
    ).to_numpy(dtype=float)
    recent = float(np.median(recent_ranges[-3:])) if len(recent_ranges) >= 3 else float(np.median(recent_ranges))
    baseline = float(np.median(recent_ranges)) if len(recent_ranges) else 0.0
    expansion = 0.0 if baseline <= 0 else _clip((recent / baseline) - 1.0, -1.0, 1.0)
    expansion_component = expansion * (1.0 if weighted_force >= 0 else -1.0)

    combined = (
        0.68 * weighted_force
        + 0.22 * velocity_component
        + 0.10 * expansion_component
    )
    signed_score = _clip(combined, -1.0, 1.0) * 100.0

    return {
        "pressure_proxy_score": signed_score,
        "approach_velocity_atr_per_minute": velocity,
        "mean_body_efficiency": float(np.mean(body_eff)),
        "mean_close_location": float(np.mean(close_locs)),
        "pre_touch_bars": len(window),
    }


def condition_depth_episodes(
    price_m1: pd.DataFrame,
    episodes: Sequence[DepthEpisode],
) -> tuple[PressureDepthEpisode, ...]:
    rows: list[PressureDepthEpisode] = []
    for episode in episodes:
        features = pressure_features_before_touch(
            price_m1,
            touch_at=episode.touch_at,
            atr_points=episode.atr_points,
        )
        if not features:
            continue
        signed = float(features["pressure_proxy_score"])
        # LONG demand: sellers push deeper, so negative market pressure becomes
        # positive opposing pressure. SHORT supply is the mirror image.
        opposing = -signed if episode.direction == "LONG" else signed
        opposing = _clip(opposing, -100.0, 100.0)
        rows.append(
            PressureDepthEpisode(
                zone_id=episode.zone_id,
                timeframe=episode.timeframe,
                direction=episode.direction,
                touch_at=ensure_utc(episode.touch_at).isoformat(),
                outcome=episode.outcome,
                reaction_hit=episode.reaction_hit,
                break_hit=episode.break_hit,
                turning_depth=episode.turning_depth,
                max_depth_reached=episode.max_depth_reached,
                zone_width=episode.zone_width,
                atr_points=episode.atr_points,
                pressure_proxy_score=signed,
                opposing_pressure_score=opposing,
                opposing_pressure_bucket=opposing_pressure_bucket(opposing),
                approach_velocity_atr_per_minute=float(features["approach_velocity_atr_per_minute"]),
                mean_body_efficiency=float(features["mean_body_efficiency"]),
                mean_close_location=float(features["mean_close_location"]),
                pre_touch_bars=int(features["pre_touch_bars"]),
            )
        )
    return tuple(rows)


def _quantile(values: Sequence[float], q: float) -> float | None:
    clean = [float(v) for v in values if isfinite(float(v))]
    return None if not clean else float(np.quantile(np.asarray(clean, dtype=float), q))


def _summary(rows: Sequence[PressureDepthEpisode]) -> dict[str, Any]:
    items = list(rows)
    holds = [r for r in items if r.reaction_hit and r.turning_depth is not None]
    turning = [float(r.turning_depth) for r in holds if r.turning_depth is not None]
    max_depth = [float(r.max_depth_reached) for r in items]
    breaks = sum(bool(r.break_hit) for r in items)

    return {
        "n": len(items),
        "holds_050": len(holds),
        "hold_rate": None if not items else len(holds) / len(items),
        "hold_wilson_lower_95": wilson_lower_bound(len(holds), len(items)),
        "breaks": breaks,
        "break_rate": None if not items else breaks / len(items),
        "turning_depth_p25": _quantile(turning, 0.25),
        "turning_depth_median": _quantile(turning, 0.50),
        "turning_depth_p75": _quantile(turning, 0.75),
        "max_penetration_p50": _quantile(max_depth, 0.50),
        "max_penetration_p75": _quantile(max_depth, 0.75),
        "max_penetration_p90": _quantile(max_depth, 0.90),
        "mean_opposing_pressure": None if not items else float(np.mean([r.opposing_pressure_score for r in items])),
        "mean_approach_velocity_atr_per_minute": None if not items else float(np.mean([r.approach_velocity_atr_per_minute for r in items])),
    }


def pressure_depth_report(rows: Sequence[PressureDepthEpisode]) -> dict[str, Any]:
    items = list(rows)
    by_bucket: dict[str, Any] = {}
    for _low, _high, label in PRESSURE_BUCKETS:
        by_bucket[label] = _summary([r for r in items if r.opposing_pressure_bucket == label])

    by_timeframe: dict[str, Any] = {}
    for timeframe in ("H4", "H1", "M15"):
        tf = [r for r in items if r.timeframe == timeframe]
        by_timeframe[timeframe] = {
            "ALL": _summary(tf),
            "LONG": _summary([r for r in tf if r.direction == "LONG"]),
            "SHORT": _summary([r for r in tf if r.direction == "SHORT"]),
            "BY_PRESSURE_BUCKET": {
                label: _summary([r for r in tf if r.opposing_pressure_bucket == label])
                for _low, _high, label in PRESSURE_BUCKETS
            },
        }

    return {
        "all": _summary(items),
        "by_pressure_bucket": by_bucket,
        "by_timeframe": by_timeframe,
        "interpretation": (
            "Positive opposing-pressure means the incoming move was still pushing deeper "
            "into the zone immediately before first touch. Historical 2012-2026 values are "
            "a causal M1 OHLC pressure proxy, not true DOM/order-flow. True cTrader Level-II "
            "pressure must be calibrated prospectively."
        ),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def serialize_pressure_episode(row: PressureDepthEpisode) -> dict[str, Any]:
    return asdict(row)
