"""RIZAN Cross-Asset Lead–Lag: causal research primitives and read-only pressure.

No broker imports, order submission or baseline policy changes. Timestamps are
completed-bar availability times, never bar opens. Missing prices are not filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

MODEL_VERSION = "RIZAN_CROSS_ASSET_LEAD_LAG_V1"
LAGS = (0, 1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120)
HORIZONS = (5, 10, 15, 30, 60)
INSTRUMENTS = {
    "XAUUSD": (
        "DXY",
        "US2Y",
        "US10Y",
        "REAL10Y",
        "EURUSD",
        "USDJPY",
        "GBPUSD",
        "USDCHF",
        "XAGUSD",
        "SPX",
        "NQ",
        "VIX",
        "WTI",
        "COPPER",
    ),
    "EURUSD": (
        "DXY",
        "US2Y",
        "US10Y",
        "DE2Y",
        "DE10Y",
        "US2Y_DE2Y",
        "US10Y_DE10Y",
        "GBPUSD",
        "USDCHF",
        "EURGBP",
        "USDJPY",
        "SPX",
        "VIX",
    ),
}


def utc_index(index) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(index)
    if result.tz is None:
        raise ValueError("EXPLICIT_SOURCE_TIMEZONE_REQUIRED")
    return result.tz_convert("UTC")


def completed_close(
    frame: pd.DataFrame,
    *,
    source_timezone: str | None = None,
    bar_minutes: int = 1,
    timestamp_is_open: bool = True,
) -> pd.Series:
    """Reject duplicate/corrupt bars rather than silently repair vendor data."""
    f = frame.copy()
    index = (
        pd.DatetimeIndex(f.pop("timestamp"))
        if "timestamp" in f
        else pd.DatetimeIndex(f.index)
    )
    if index.tz is None:
        if source_timezone is None:
            raise ValueError("EXPLICIT_SOURCE_TIMEZONE_REQUIRED")
        index = index.tz_localize(
            source_timezone, ambiguous="raise", nonexistent="raise"
        )
    index = utc_index(index)
    if timestamp_is_open:
        index += pd.Timedelta(minutes=bar_minutes)
    if index.has_duplicates:
        raise ValueError("DUPLICATE_BAR")
    values = pd.to_numeric(f.close, errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("INVALID_CLOSE")
    return pd.Series(values, index=index).sort_index()


def synchronize(series: dict[str, pd.Series], minutes: int) -> pd.DataFrame:
    """Only fully covered regular buckets. Preserve gaps, weekends and outages."""
    if minutes not in (1, 5, 15):
        raise ValueError("UNSUPPORTED_TIMEFRAME")
    out = {}
    for name, values in series.items():
        values = values.copy()
        values.index = utc_index(values.index)
        if values.index.has_duplicates:
            raise ValueError("DUPLICATE_BAR")
        # Source contract is M1 close availability; no interpolation or ffill.
        bucket = values.resample(f"{minutes}min", closed="right", label="right")
        out[name] = bucket.last().where(bucket.count() == minutes)
    return pd.DataFrame(out).sort_index()


def sessions(index: pd.DatetimeIndex) -> pd.Series:
    """DST-aware cash working sessions, disjoint London–NY overlap."""
    index = utc_index(index)
    london = index.tz_convert("Europe/London")
    ny = index.tz_convert("America/New_York")
    lon = (london.hour >= 8) & (london.hour < 17)
    newyork = (ny.hour >= 8) & (ny.hour < 17)
    asia = (index.hour >= 0) & (index.hour < 8)
    return pd.Series(
        np.select(
            [lon & newyork, lon, newyork, asia],
            ["LONDON_NEW_YORK_OVERLAP", "LONDON", "NEW_YORK", "ASIA"],
            default="OFF_SESSION",
        ),
        index=index,
    )


def regimes(target: pd.Series) -> pd.DataFrame:
    """Past-only proxies; trend and volatility are separate, overlapping axes."""
    ret = np.log(target).diff()
    vol = ret.rolling(48, min_periods=48).std()
    reference = vol.rolling(480, min_periods=120).median().shift(1)
    fast = target.ewm(span=24, adjust=False).mean()
    slow = target.ewm(span=96, adjust=False).mean()
    scale = target * vol * np.sqrt(24)
    trend = (fast - slow) / scale.replace(0, np.nan)
    return pd.DataFrame(
        {
            "trend": np.select(
                [trend > 1, trend < -1], ["BULL_TREND", "BEAR_TREND"], default="RANGE"
            ),
            "volatility": np.where(
                vol > reference, "HIGH_VOLATILITY", "LOW_VOLATILITY"
            ),
            "realized_volatility": vol,
        },
        index=target.index,
    )


def event_windows(index, events: pd.DataFrame | None, pre=15, post=30) -> pd.Series:
    if events is None:
        return pd.Series("UNKNOWN_EVENT_COVERAGE", index=index)
    state = pd.Series("NON_EVENT", index=index)
    for event in events.itertuples():
        at = pd.Timestamp(event.timestamp)
        if at.tzinfo is None:
            raise ValueError("EVENT_TIMEZONE_REQUIRED")
        mask = (index >= at - pd.Timedelta(minutes=pre)) & (
            index <= at + pd.Timedelta(minutes=post)
        )
        state.loc[mask] = str(event.category)
    return state


def paired_returns(
    prices: pd.DataFrame,
    leader: str,
    target: str,
    minutes: int,
    lag: int,
    horizon: int | None = None,
    kind="price",
) -> pd.DataFrame:
    """Lag means leader close at t predicts target increment ending at t+lag.

    Lag 0 is a contemporaneous control, never a tradable candidate. Conditional
    horizons use target(t+h)/target(t); all intervening bars must be present.
    """
    if lag % minutes or (horizon is not None and horizon % minutes):
        raise ValueError("LAG_NOT_RESOLVABLE_ON_TIMEFRAME")
    a, b = prices[leader], prices[target]
    x = a.diff() if kind == "yield" else np.log(a.where(a > 0)).diff()
    r = np.log(b.where(b > 0)).diff()
    steps = (horizon if horizon is not None else lag) // minutes
    if horizon is None:
        y = r.shift(-steps)
        valid = b.notna().rolling(steps + 2).sum().shift(-steps) == steps + 2
    else:
        y = np.log(b.shift(-steps) / b)
        valid = b.notna().rolling(steps + 1).sum().shift(-steps) == steps + 1
    # Standardize using information strictly preceding the leader move.
    mean = x.rolling(96, min_periods=48).mean().shift(1)
    std = x.rolling(96, min_periods=48).std().shift(1).replace(0, np.nan)
    z = (x - mean) / std
    return pd.DataFrame(
        {
            "x": x,
            "y": y.where(valid),
            "z": z,
            "target_now": r,
            "target_prev": r.shift(1),
        },
        index=prices.index,
    ).replace([np.inf, -np.inf], np.nan)


def independent_events(
    frame: pd.DataFrame, threshold: float, embargo_minutes: int
) -> pd.DataFrame:
    """Greedy chronological de-overlap, measured in elapsed time not row count."""
    eligible = frame.dropna(subset=["x", "y", "z"]).loc[
        lambda f: f.z.abs() >= threshold
    ]
    keep = []
    until = None
    for at in eligible.index:
        if until is None or at > until:
            keep.append(at)
            until = at + pd.Timedelta(minutes=embargo_minutes)
    return eligible.loc[keep]


def block_bootstrap(
    values, *, block=8, repeats=500, seed=7291
) -> tuple[float | None, float | None]:
    x = np.asarray(values, float)
    x = x[np.isfinite(x)]
    if len(x) < 20:
        return None, None
    rng = np.random.default_rng(seed)
    block = min(block, len(x))
    estimates = []
    for _ in range(repeats):
        starts = rng.integers(0, len(x), size=int(np.ceil(len(x) / block)))
        sample = np.concatenate(
            [x[(start + np.arange(block)) % len(x)] for start in starts]
        )[: len(x)]
        estimates.append(sample.mean())
    return tuple(float(v) for v in np.quantile(estimates, [0.025, 0.975]))


def fdr_bh(pvalues) -> np.ndarray:
    """Benjamini–Hochberg across the complete declared candidate family."""
    p = np.asarray(pvalues, float)
    p = np.where(np.isfinite(p), p, 1.0)
    order = np.argsort(p)
    adjusted = p[order] * len(p) / np.arange(1, len(p) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty(len(p))
    result[order] = np.clip(adjusted, 0, 1)
    return result


def conditional_stats(
    frame: pd.DataFrame, sign: int, threshold: float, horizon: int
) -> dict:
    sampled = independent_events(frame, threshold, max(horizon, 5))
    hit = (sign * np.sign(sampled.x.to_numpy()) * sampled.y.to_numpy() > 0).astype(
        float
    )
    lo, hi = block_bootstrap(hit)
    return {
        "events": len(sampled),
        "probability": float(hit.mean()) if len(hit) else None,
        "ci_low": lo,
        "ci_high": hi,
        "mean_signed_return": float((sign * np.sign(sampled.x) * sampled.y).mean())
        if len(hit)
        else None,
    }


@dataclass(frozen=True)
class Calibration:
    leader: str
    target: str
    lag_minutes: int
    sign: int
    threshold: float
    oos_probability: float
    ci_low: float
    session: str
    regime: str
    trained_until: str
    expires_at: str
    approved: bool = False
    baseline_improvement_verified: bool = False
    model_version: str = MODEL_VERSION


def pressure_state(
    *,
    target: str,
    now: datetime,
    observations: dict[str, dict],
    calibrations: list[Calibration],
    context: dict[str, Any],
    max_age_seconds: int = 90,
) -> dict:
    """Read-only inference; empirical probabilities, never invented consensus.

    Calibrations are conditional on a matching session/regime, immutable and
    past-trained. Disagreement exposes weighted vote fraction separately from
    probability. Independent execution is permanently unavailable here.
    """
    now = now.astimezone(UTC)
    result = {
        "model_version": MODEL_VERSION,
        "target_symbol": target,
        "observed_at": now.isoformat(),
        "state": "NO_SIGNAL",
        "direction": "NEUTRAL",
        "execution_authority": False,
        "execution_influence": False,
        "confidence": None,
        "confidence_label": "UNAVAILABLE",
        "leaders": [],
        "reference_geometry": context.get("reference_geometry", {}),
        "execution_geometry": context.get("execution_geometry", {}),
        "context": context,
        "reason": "NO_ACCEPTED_CALIBRATION",
        "source_health": {},
    }
    active = []
    stale = False
    for c in calibrations:
        if c.target != target or not c.approved or not c.baseline_improvement_verified:
            continue
        try:
            trained, expires = pd.Timestamp(c.trained_until), pd.Timestamp(c.expires_at)
            if (
                trained.tzinfo is None
                or expires.tzinfo is None
                or not trained < now <= expires
            ):
                continue
            if c.session != context.get("session") or c.regime != context.get("regime"):
                continue
            o = observations.get(c.leader, {})
            at = pd.Timestamp(o.get("observed_at"))
            age = (pd.Timestamp(now) - at).total_seconds()
            fresh = at.tzinfo is not None and 0 <= age <= max_age_seconds
            fresh = fresh and o.get("source_healthy") is True
            z = float(o.get("zscore", float("nan")))
            if not isfinite(z):
                fresh = False
            result["source_health"][c.leader] = {
                "fresh": fresh,
                "age_seconds": age,
                "latency_ms": o.get("latency_ms"),
                "last_success_at": o.get("last_success_at"),
            }
            if not fresh:
                stale = True
                continue
            if abs(z) < c.threshold:
                continue
            if (
                c.lag_minutes <= 0
                or c.sign not in (-1, 1)
                or not 0.5 < c.ci_low <= c.oos_probability <= 1
            ):
                continue
            active.append((c, 1 if z * c.sign > 0 else -1))
            result["leaders"].append(
                {
                    "symbol": c.leader,
                    "zscore": z,
                    "lag_minutes": c.lag_minutes,
                    "probability": c.oos_probability,
                }
            )
        except (ValueError, TypeError, OverflowError):
            stale = True
            result["source_health"][c.leader] = {
                "fresh": False,
                "error": "INVALID_OBSERVATION",
            }
    if stale:
        result.update(
            state="STALE_DATA", reason="ACCEPTED_LEADER_FEED_STALE_OR_MISSING"
        )
    elif active:
        weights = np.array([c.ci_low - 0.5 for c, _ in active])
        sides = np.array([s for _, s in active])
        net = float(np.dot(weights, sides))
        direction = 1 if net > 0 else -1 if net < 0 else 0
        agreeing = [(c, s) for c, s in active if s == direction]
        consensus = (
            float(weights[sides == direction].sum() / weights.sum())
            if direction
            else 0.5
        )
        result["consensus"] = 100 * consensus
        result["direction"] = (
            "BULLISH" if direction == 1 else "BEARISH" if direction == -1 else "MIXED"
        )
        result.update(
            state="LEADERS_MOVING", reason="PRICE_STRUCTURE_VALIDATION_REQUIRED"
        )
        # One model's OOS estimate is calibrated. Multi-leader probability needs
        # its own held-out joint calibration, not an average of marginal rates.
        if len(agreeing) == 1 and len(active) == 1:
            probability = agreeing[0][0].oos_probability
            result["confidence"] = round(probability * 100, 2)
            result["confidence_label"] = (
                "LOW"
                if probability < 0.6
                else "MEDIUM"
                if probability < 0.7
                else "HIGH"
                if probability < 0.8
                else "VERY HIGH"
            )
        result["expected_response_minutes"] = [
            min(c.lag_minutes for c, _ in active),
            max(c.lag_minutes for c, _ in active),
        ]
        reaction = context.get("target_reaction_direction")
        if direction and reaction in (-direction, 0):
            result.update(
                state="CROSS_ASSET_DIVERGENCE", reason="TARGET_NOT_YET_REPRICED"
            )
        elif direction and reaction == direction:
            result.update(
                state="XAU_REPRICING_STARTED"
                if target == "XAUUSD"
                else "TARGET_REPRICING_STARTED"
            )
        if direction and context.get("h1_valid") and context.get("m15_valid"):
            result["state"] = "STRUCTURE_CONFIRMING"
            if context.get("valid_sd_liquidity_area") and context.get(
                "m5_pocket_valid"
            ):
                result["state"] = "ENTRY_APPROACHING"
        if context.get("structural_invalidation"):
            result.update(state="INVALIDATED", reason="STRUCTURAL_INVALIDATION")
    if context.get("event_state") != "CLEAR":
        result.update(state="EVENT_BLOCK", reason="EVENT_RISK_OR_COVERAGE_UNKNOWN")
    # This module never emits an executable READY/order, even if structure aligns.
    return result
