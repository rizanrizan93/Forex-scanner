from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict
from datetime import datetime, timedelta
from math import isfinite, sqrt
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_sd_liquidity_v345 import (
    load_price_frame,
    resample_ohlc,
)
from .xau_sd_liquidity_engine_v342 import (
    SDZone,
    TF_PARAMS as ENGINE_TF_PARAMS,
    detect_zones as engine_detect_zones,
)

RESEARCH_VERSION = "XAU_RIZAN_ZONE_TOUCH_DECAY_V352_1"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False

TARGET_ATR = 0.50
BREAK_BUFFER_ATR = 0.05

# Preserve current runtime definitions for H1/H4. H2 uses the midpoint of
# the H1/H4 detection thresholds and geometric-midpoint lifecycle/horizon.
H2_PARAMS = {
    "departure_range_atr": (
        float(ENGINE_TF_PARAMS["H1"]["departure_range_atr"])
        + float(ENGINE_TF_PARAMS["H4"]["departure_range_atr"])
    ) / 2.0,
    "departure_body_fraction": (
        float(ENGINE_TF_PARAMS["H1"]["departure_body_fraction"])
        + float(ENGINE_TF_PARAMS["H4"]["departure_body_fraction"])
    ) / 2.0,
    "max_base_range_atr": (
        float(ENGINE_TF_PARAMS["H1"]["max_base_range_atr"])
        + float(ENGINE_TF_PARAMS["H4"]["max_base_range_atr"])
    ) / 2.0,
    "lookback_structure": int(
        round(
            (
                int(ENGINE_TF_PARAMS["H1"]["lookback_structure"])
                + int(ENGINE_TF_PARAMS["H4"]["lookback_structure"])
            )
            / 2.0
        )
    ),
    "lifecycle_hours": 24.0
    * sqrt(
        (float(ENGINE_TF_PARAMS["H1"]["lifecycle_hours"]) / 24.0)
        * (float(ENGINE_TF_PARAMS["H4"]["lifecycle_hours"]) / 24.0)
    ),
}

TF_MINUTES = {"H1": 60, "H2": 120, "H4": 240}
REACTION_HORIZON_HOURS = {"H1": 12.0, "H2": 20.0, "H4": 32.0}
LIFECYCLE_HOURS = {
    "H1": float(ENGINE_TF_PARAMS["H1"]["lifecycle_hours"]),
    "H2": float(H2_PARAMS["lifecycle_hours"]),
    "H4": float(ENGINE_TF_PARAMS["H4"]["lifecycle_hours"]),
}
SUPERSESSION_GAP_HOURS = {"H1": 2.1, "H2": 4.1, "H4": 8.1}


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _q(values: Sequence[float], q: float) -> float | None:
    clean = [float(v) for v in values if isfinite(float(v))]
    if not clean:
        return None
    return float(np.quantile(np.asarray(clean, dtype=float), q))


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = p + z * z / (2.0 * total)
    margin = z * sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (center - margin) / denominator)


def _bar_frame(bars: Iterable[Any]) -> pd.DataFrame:
    rows = []
    for bar in bars:
        ts = getattr(bar, "timestamp", None)
        if ts is None:
            continue
        rows.append(
            {
                "timestamp": pd.Timestamp(ensure_utc(ts)),
                "open": float(getattr(bar, "open")),
                "high": float(getattr(bar, "high")),
                "low": float(getattr(bar, "low")),
                "close": float(getattr(bar, "close")),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    return (
        pd.DataFrame(rows)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=max(6, period // 2)).mean()


def _bars_from_frame(frame: pd.DataFrame, timeframe: str) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            symbol="XAUUSD",
            timeframe=timeframe,
            timestamp=ensure_utc(pd.Timestamp(row["timestamp"]).to_pydatetime()),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_count=1,
            spread_avg=0.0,
            spread_max=0.0,
        )
        for _, row in frame.iterrows()
    )


def _stable_id(
    *,
    timeframe: str,
    direction: str,
    origin_at: datetime,
    available_at: datetime,
    low: float,
    high: float,
) -> str:
    import hashlib

    raw = (
        f"{timeframe}|{direction}|{ensure_utc(origin_at).isoformat()}|"
        f"{ensure_utc(available_at).isoformat()}|{low:.6f}|{high:.6f}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _pattern(direction: str, pre_close: float, base_mid: float) -> str:
    if direction == "LONG":
        return "DBR" if pre_close > base_mid else "RBR"
    return "RBD" if pre_close < base_mid else "DBD"


def _zone_geometry(base: pd.DataFrame, direction: str) -> tuple[float, float, float, float]:
    low = float(base["low"].min())
    high = float(base["high"].max())
    body_high = float(
        pd.concat([base["open"], base["close"]], axis=1).max(axis=1).max()
    )
    body_low = float(
        pd.concat([base["open"], base["close"]], axis=1).min(axis=1).min()
    )
    if direction == "LONG":
        proximal = min(high, body_high)
        distal = low
    else:
        proximal = max(low, body_low)
        distal = high
    return low, high, proximal, distal


def detect_h2_zones(bars: Iterable[Any], *, as_of: datetime) -> tuple[SDZone, ...]:
    frame = _bar_frame(bars)
    if len(frame) < 24:
        return ()
    known_delta = pd.Timedelta(hours=2)
    frame = frame[
        (frame["timestamp"] + known_delta) <= pd.Timestamp(ensure_utc(as_of))
    ].copy()
    if len(frame) < 24:
        return ()
    frame["atr14"] = _atr(frame)
    p = H2_PARAMS
    zones: list[SDZone] = []

    for i in range(18, len(frame)):
        departure = frame.iloc[i]
        atr = _f(departure.get("atr14"))
        if atr is None or atr <= 0:
            continue
        o, h, l, c = (
            float(departure["open"]),
            float(departure["high"]),
            float(departure["low"]),
            float(departure["close"]),
        )
        rng = max(h - l, 1e-9)
        range_atr = rng / atr
        body_fraction = abs(c - o) / rng
        if range_atr < float(p["departure_range_atr"]):
            continue
        if body_fraction < float(p["departure_body_fraction"]):
            continue
        direction = "LONG" if c > o else "SHORT" if c < o else ""
        if not direction:
            continue

        best: tuple[float, int, pd.DataFrame] | None = None
        for base_len in (1, 2, 3):
            start = i - base_len
            if start < 10:
                continue
            base = frame.iloc[start:i].copy()
            width = float(base["high"].max() - base["low"].min())
            width_atr = width / atr
            if width_atr > float(p["max_base_range_atr"]):
                continue
            body_mean = float(
                (
                    (base["close"] - base["open"]).abs()
                    / (base["high"] - base["low"]).clip(lower=1e-9)
                ).mean()
            )
            compactness = width_atr + 0.35 * body_mean
            if best is None or compactness < best[0]:
                best = (compactness, base_len, base)
        if best is None:
            continue

        _, base_len, base = best
        low, high, proximal, distal = _zone_geometry(base, direction)
        width = high - low
        if width <= 0:
            continue
        departure_buffer = 0.05 * atr
        if direction == "LONG" and c <= high + departure_buffer:
            continue
        if direction == "SHORT" and c >= low - departure_buffer:
            continue

        structure_start = max(0, i - base_len - int(p["lookback_structure"]))
        structure_end = i - base_len
        prior = frame.iloc[structure_start:structure_end]
        if prior.empty:
            continue
        structural_bos = bool(
            c > float(prior["high"].max())
            if direction == "LONG"
            else c < float(prior["low"].min())
        )
        if not structural_bos and range_atr < 1.25:
            continue

        origin_at = ensure_utc(base.iloc[0]["timestamp"].to_pydatetime())
        available_at = ensure_utc((departure["timestamp"] + known_delta).to_pydatetime())
        pre_close = float(frame.iloc[i - base_len - 1]["close"])
        score = (
            45.0
            + 9.5
            + (16.0 if structural_bos else 5.0)
            + min(15.0, max(0.0, (range_atr - 0.8) * 12.0))
            + min(8.0, body_fraction * 8.0)
            - min(10.0, max(0.0, width / atr - 0.6) * 8.0)
        )
        zones.append(
            SDZone(
                zone_id=_stable_id(
                    timeframe="H2",
                    direction=direction,
                    origin_at=origin_at,
                    available_at=available_at,
                    low=low,
                    high=high,
                ),
                timeframe="H2",
                direction=direction,
                pattern=_pattern(direction, pre_close, (low + high) / 2.0),
                zone_class="STRUCTURAL_BOS" if structural_bos else "DISPLACEMENT",
                low=low,
                high=high,
                proximal=proximal,
                distal=distal,
                origin_at=origin_at,
                available_at=available_at,
                atr=float(atr),
                base_bars=base_len,
                base_range_atr=width / atr,
                departure_range_atr=range_atr,
                departure_body_fraction=body_fraction,
                structural_bos=structural_bos,
                score_seed=score,
            )
        )
    return tuple(zones)


def build_zones(price_m1: pd.DataFrame) -> tuple[SDZone, ...]:
    if price_m1.empty:
        return ()
    as_of = ensure_utc(pd.Timestamp(price_m1.iloc[-1]["timestamp"]).to_pydatetime()) + timedelta(minutes=1)
    output: list[SDZone] = []
    for timeframe, rule in (("H1", "1h"), ("H2", "2h"), ("H4", "4h")):
        frame = resample_ohlc(price_m1, rule)
        bars = _bars_from_frame(frame, timeframe)
        if timeframe == "H2":
            output.extend(detect_h2_zones(bars, as_of=as_of))
        else:
            output.extend(engine_detect_zones(bars, timeframe=timeframe, as_of=as_of))
    return tuple(
        sorted(
            output,
            key=lambda z: (ensure_utc(z.available_at), z.timeframe, z.direction, z.zone_id),
        )
    )


def _overlap_ratio(a: SDZone, b: SDZone) -> float:
    overlap = max(0.0, min(float(a.high), float(b.high)) - max(float(a.low), float(b.low)))
    minimum = max(
        min(float(a.high) - float(a.low), float(b.high) - float(b.low)),
        1e-12,
    )
    return overlap / minimum


def causal_superseded_at(zones: Sequence[SDZone]) -> dict[str, datetime | None]:
    result = {z.zone_id: None for z in zones}
    recent: dict[tuple[str, str], list[SDZone]] = {}
    for zone in zones:
        key = (zone.timeframe, zone.direction)
        now = ensure_utc(zone.available_at)
        bucket = recent.setdefault(key, [])
        gap_limit = SUPERSESSION_GAP_HOURS[zone.timeframe]
        bucket[:] = [
            old
            for old in bucket
            if (now - ensure_utc(old.available_at)).total_seconds() / 3600.0 <= gap_limit
        ]
        for old in bucket:
            if result[old.zone_id] is None and _overlap_ratio(old, zone) >= 0.75:
                result[old.zone_id] = now
        bucket.append(zone)
    return result


def _zone_record(zone: SDZone) -> dict[str, Any]:
    row = asdict(zone)
    row["origin_at"] = ensure_utc(zone.origin_at).isoformat()
    row["available_at"] = ensure_utc(zone.available_at).isoformat()
    return row


def _bucket(prior_touches: int) -> str:
    return str(prior_touches) if prior_touches < 5 else "5+"


def evaluate_zone_touches(
    price_m1: pd.DataFrame,
    *,
    zone: SDZone,
    valid_until: datetime | None = None,
    price_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate sequential zone visits using vectorized touch boundaries.

    A distinct touch begins only after at least one full M1 bar outside the zone.
    The prior visit fails with RETOUCH_BEFORE_050 if the next distinct touch starts
    before a 0.50 ATR reaction. This keeps repeated-touch buckets non-overlapping.
    """
    ctx = price_context or {
        "timestamps": list(price_m1["timestamp"]),
        "high": price_m1["high"].to_numpy(dtype=float, copy=False),
        "low": price_m1["low"].to_numpy(dtype=float, copy=False),
        "close": price_m1["close"].to_numpy(dtype=float, copy=False),
    }
    timestamps = ctx["timestamps"]
    if not timestamps:
        return []
    highs = ctx["high"]
    lows = ctx["low"]
    closes = ctx["close"]

    available = ensure_utc(zone.available_at)
    start = bisect_left(timestamps, pd.Timestamp(available))
    expiry = available + timedelta(hours=LIFECYCLE_HOURS[zone.timeframe])
    if valid_until is not None:
        expiry = min(expiry, ensure_utc(valid_until))
    end = min(bisect_left(timestamps, pd.Timestamp(expiry)), len(timestamps))
    if end <= start:
        return []

    seg_high = highs[start:end]
    seg_low = lows[start:end]
    seg_close = closes[start:end]
    inside = (seg_high >= float(zone.low)) & (seg_low <= float(zone.high))
    previous_inside = np.r_[False, inside[:-1]]
    touch_rel = np.flatnonzero(inside & ~previous_inside)
    if len(touch_rel) == 0:
        return []

    target = (
        float(zone.proximal) + TARGET_ATR * float(zone.atr)
        if zone.direction == "LONG"
        else float(zone.proximal) - TARGET_ATR * float(zone.atr)
    )
    invalid_level = (
        float(zone.distal) - BREAK_BUFFER_ATR * float(zone.atr)
        if zone.direction == "LONG"
        else float(zone.distal) + BREAK_BUFFER_ATR * float(zone.atr)
    )
    invalid_mask = (
        seg_close < invalid_level
        if zone.direction == "LONG"
        else seg_close > invalid_level
    )
    invalid_rel = np.flatnonzero(invalid_mask)
    first_invalid_rel = int(invalid_rel[0]) if len(invalid_rel) else None

    width = max(float(zone.high) - float(zone.low), 1e-12)
    touches: list[dict[str, Any]] = []

    for position, rel_raw in enumerate(touch_rel):
        rel = int(rel_raw)
        if first_invalid_rel is not None and rel > first_invalid_rel:
            break
        absolute = start + rel
        touch_at = ensure_utc(timestamps[absolute].to_pydatetime()) + timedelta(minutes=1)
        horizon = min(
            touch_at + timedelta(hours=REACTION_HORIZON_HOURS[zone.timeframe]),
            expiry,
        )
        horizon_abs = min(bisect_left(timestamps, pd.Timestamp(horizon)), end)

        next_touch_abs: int | None = None
        if position + 1 < len(touch_rel):
            candidate = start + int(touch_rel[position + 1])
            if candidate < horizon_abs:
                next_touch_abs = candidate

        break_abs: int | None = None
        if first_invalid_rel is not None:
            candidate = start + first_invalid_rel
            if absolute <= candidate < horizon_abs:
                break_abs = candidate

        terminal_exclusive = horizon_abs
        if next_touch_abs is not None:
            terminal_exclusive = min(terminal_exclusive, next_touch_abs)
        if break_abs is not None:
            terminal_exclusive = min(terminal_exclusive, break_abs + 1)
        terminal_exclusive = max(absolute + 1, terminal_exclusive)

        if zone.direction == "LONG":
            target_mask = highs[absolute:terminal_exclusive] >= target
        else:
            target_mask = lows[absolute:terminal_exclusive] <= target
        target_positions = np.flatnonzero(target_mask)
        target_abs = (
            absolute + int(target_positions[0])
            if len(target_positions)
            else None
        )

        same_m1_ambiguity = bool(
            target_abs is not None
            and break_abs is not None
            and target_abs == break_abs
        )
        reaction_hit = False
        break_hit = False
        retouch_before_reversal = False

        if same_m1_ambiguity:
            outcome = "BREAK_AMBIGUOUS"
            outcome_abs = int(break_abs)
            break_hit = True
        elif break_abs is not None and (
            target_abs is None or break_abs < target_abs
        ):
            outcome = "BREAK"
            outcome_abs = int(break_abs)
            break_hit = True
        elif target_abs is not None:
            outcome_abs = int(target_abs)
            reaction_hit = True
            # For a successful target bar, exclude that bar from sweep
            # classification because intrabar target-vs-wick ordering is unknown.
            adverse_end = max(absolute + 1, outcome_abs)
            if zone.direction == "LONG":
                adverse_for_sweep = float(np.min(lows[absolute:adverse_end]))
                sweep_seen = adverse_for_sweep < float(zone.distal)
            else:
                adverse_for_sweep = float(np.max(highs[absolute:adverse_end]))
                sweep_seen = adverse_for_sweep > float(zone.distal)
            outcome = (
                "REVERSAL_050_AFTER_SWEEP"
                if sweep_seen
                else "REVERSAL_050_DIRECT"
            )
        elif next_touch_abs is not None:
            outcome = "RETOUCH_BEFORE_050"
            outcome_abs = next_touch_abs
            retouch_before_reversal = True
        else:
            outcome = "STALL"
            outcome_abs = max(absolute, horizon_abs - 1)

        if reaction_hit:
            adverse_end = max(absolute + 1, outcome_abs)
        elif retouch_before_reversal:
            adverse_end = max(absolute + 1, outcome_abs)
        else:
            adverse_end = min(end, outcome_abs + 1)
        adverse_end = max(absolute + 1, adverse_end)

        if zone.direction == "LONG":
            adverse = float(np.min(lows[absolute:adverse_end]))
            sweep_seen = adverse < float(zone.distal)
            turning_depth = (float(zone.high) - adverse) / width
            sweep_extension = max(0.0, float(zone.distal) - adverse)
        else:
            adverse = float(np.max(highs[absolute:adverse_end]))
            sweep_seen = adverse > float(zone.distal)
            turning_depth = (adverse - float(zone.low)) / width
            sweep_extension = max(0.0, adverse - float(zone.distal))

        # Preserve conservative target-bar handling for liquidity classification.
        if reaction_hit:
            if zone.direction == "LONG":
                adverse_success = float(np.min(lows[absolute:max(absolute + 1, outcome_abs)]))
                sweep_seen = adverse_success < float(zone.distal)
            else:
                adverse_success = float(np.max(highs[absolute:max(absolute + 1, outcome_abs)]))
                sweep_seen = adverse_success > float(zone.distal)
            outcome = (
                "REVERSAL_050_AFTER_SWEEP"
                if sweep_seen
                else "REVERSAL_050_DIRECT"
            )

        outcome_at = ensure_utc(timestamps[outcome_abs].to_pydatetime()) + timedelta(minutes=1)
        prior_touches = position
        touches.append(
            {
                **_zone_record(zone),
                "prior_touch_count": prior_touches,
                "touch_bucket": _bucket(prior_touches),
                "touch_number": prior_touches + 1,
                "touch_at": touch_at.isoformat(),
                "outcome_at": outcome_at.isoformat(),
                "outcome": outcome,
                "reaction_hit": reaction_hit,
                "break_hit": break_hit,
                "retouch_before_reversal": retouch_before_reversal,
                "sweep_seen": bool(sweep_seen),
                "reversal_after_sweep": bool(reaction_hit and sweep_seen),
                "direct_reversal": bool(reaction_hit and not sweep_seen),
                "target_price": target,
                "invalid_level": invalid_level,
                "turning_depth": turning_depth,
                "sweep_extension_points": sweep_extension,
                "sweep_extension_atr": sweep_extension / max(float(zone.atr), 1e-12),
                "sweep_extension_zone_width": sweep_extension / width,
                "same_m1_ambiguity": same_m1_ambiguity,
                "minutes_to_outcome": max(
                    0.0, (outcome_at - touch_at).total_seconds() / 60.0
                ),
            }
        )
        if break_hit:
            break

    return touches


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    reversals = [r for r in rows if bool(r.get("reaction_hit"))]
    direct = [r for r in reversals if bool(r.get("direct_reversal"))]
    sweeps = [r for r in rows if bool(r.get("sweep_seen"))]
    sweep_reversals = [r for r in rows if bool(r.get("reversal_after_sweep"))]
    breaks = [r for r in rows if bool(r.get("break_hit"))]
    retouches = [r for r in rows if bool(r.get("retouch_before_reversal"))]
    stalls = [r for r in rows if str(r.get("outcome") or "") == "STALL"]
    return {
        "episodes": total,
        "reversals_050_atr": len(reversals),
        "reversal_rate": None if total == 0 else len(reversals) / total,
        "reversal_wilson_lower_95": _wilson_lower(len(reversals), total),
        "direct_reversals": len(direct),
        "direct_reversal_rate": None if total == 0 else len(direct) / total,
        "liquidity_sweep_seen": len(sweeps),
        "liquidity_sweep_rate": None if total == 0 else len(sweeps) / total,
        "sweep_reversals": len(sweep_reversals),
        "reversal_rate_given_sweep": (
            None if not sweeps else len(sweep_reversals) / len(sweeps)
        ),
        "sweep_share_of_reversals": (
            None if not reversals else len(sweep_reversals) / len(reversals)
        ),
        "breaks": len(breaks),
        "break_rate": None if total == 0 else len(breaks) / total,
        "retouch_before_050": len(retouches),
        "retouch_before_050_rate": None if total == 0 else len(retouches) / total,
        "stalls": len(stalls),
        "turning_depth_p50": _q(
            [float(r["turning_depth"]) for r in reversals],
            0.50,
        ),
        "turning_depth_p75": _q(
            [float(r["turning_depth"]) for r in reversals],
            0.75,
        ),
        "sweep_extension_atr_p50": _q(
            [float(r["sweep_extension_atr"]) for r in sweep_reversals],
            0.50,
        ),
        "sweep_extension_atr_p75": _q(
            [float(r["sweep_extension_atr"]) for r in sweep_reversals],
            0.75,
        ),
        "sweep_extension_atr_p90": _q(
            [float(r["sweep_extension_atr"]) for r in sweep_reversals],
            0.90,
        ),
    }


def grouped_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for tf in ("H4", "H2", "H1"):
        tf_rows = [r for r in rows if r.get("timeframe") == tf]
        tf_out: dict[str, Any] = {}
        for direction in ("ALL", "LONG", "SHORT"):
            drows = tf_rows if direction == "ALL" else [
                r for r in tf_rows if r.get("direction") == direction
            ]
            tf_out[direction] = {
                bucket: _summary(
                    [r for r in drows if str(r.get("touch_bucket")) == bucket]
                )
                for bucket in ("0", "1", "2", "3", "4", "5+")
            }
        output[tf] = tf_out
    return output


def evaluate_year(price_m1: pd.DataFrame, *, target_year: int) -> dict[str, Any]:
    price_m1 = price_m1.copy()
    price_m1["timestamp"] = pd.to_datetime(price_m1["timestamp"], utc=True)
    zones = build_zones(price_m1)
    superseded = causal_superseded_at(zones)
    price_context = {
        "timestamps": list(price_m1["timestamp"]),
        "high": price_m1["high"].to_numpy(dtype=float, copy=False),
        "low": price_m1["low"].to_numpy(dtype=float, copy=False),
        "close": price_m1["close"].to_numpy(dtype=float, copy=False),
    }
    episodes: list[dict[str, Any]] = []

    for zone in zones:
        rows = evaluate_zone_touches(
            price_m1,
            zone=zone,
            valid_until=superseded.get(zone.zone_id),
            price_context=price_context,
        )
        for row in rows:
            touch_year = datetime.fromisoformat(
                str(row["touch_at"]).replace("Z", "+00:00")
            ).year
            if touch_year == int(target_year):
                episodes.append(row)

    episodes.sort(
        key=lambda r: (
            str(r["touch_at"]),
            str(r["timeframe"]),
            str(r["zone_id"]),
            int(r["prior_touch_count"]),
        )
    )
    return {
        "research_version": RESEARCH_VERSION,
        "year": int(target_year),
        "zone_count": len(
            [
                z for z in zones
                if ensure_utc(z.available_at).year == int(target_year)
            ]
        ),
        "episode_count": len(episodes),
        "episodes": episodes,
        "summary": grouped_summary(episodes),
        "contract": {
            "timeframes": ["H4", "H2", "H1"],
            "fresh_definition": "touch_bucket=0 means zero prior touches / first touch after zone formation",
            "touch_buckets": ["0", "1", "2", "3", "4", "5+"],
            "reversal": ">=0.50 parent ATR favorable move from proximal before close invalidation, retouch, or horizon",
            "retouch_rule": (
                "if price exits then re-enters the zone before reaching 0.50 ATR, "
                "that touch is RETOUCH_BEFORE_050 and not counted as a reversal"
            ),
            "break": "M1 close beyond distal plus 0.05 parent ATR",
            "liquidity_sweep": (
                "wick beyond distal before resolution without an earlier close invalidation"
            ),
            "horizons_hours": REACTION_HORIZON_HOURS,
            "h2_detection": {
                "logic": "same compact-base -> displacement detector as runtime H1/H4",
                "parameters": H2_PARAMS,
                "reason": "midpoint H1/H4 thresholds; H2 remains research-only",
            },
            "development_period": "2012-2024",
            "oos_period": "2025-2026",
            "execution_authority": False,
            "execution_influence": False,
        },
        "execution_authority": False,
        "execution_influence": False,
    }


def aggregate_years(shards: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(shards, key=lambda x: int(x["year"]))
    all_rows = [dict(r) for shard in ordered for r in list(shard.get("episodes") or [])]

    def select(start: int, end: int) -> list[dict[str, Any]]:
        out = []
        for row in all_rows:
            year = datetime.fromisoformat(
                str(row["touch_at"]).replace("Z", "+00:00")
            ).year
            if start <= year <= end:
                out.append(row)
        return out

    dev = select(2012, 2024)
    oos = select(2025, 2026)
    full = select(2012, 2026)
    return {
        "research_version": RESEARCH_VERSION,
        "years": [int(s["year"]) for s in ordered],
        "year_count": len(ordered),
        "episode_count": len(full),
        "periods": {
            "development_2012_2024": {
                "summary": grouped_summary(dev),
            },
            "oos_2025_2026": {
                "summary": grouped_summary(oos),
            },
            "full_2012_2026": {
                "summary": grouped_summary(full),
            },
        },
        "episodes": full,
        "promotion_policy": {
            "automatic_runtime_promotion": False,
            "forward_shadow_required": True,
            "reason": (
                "Touch-count reversal rates are descriptive conditioning evidence; "
                "they do not grant execution authority."
            ),
        },
        "execution_authority": False,
        "execution_influence": False,
    }
