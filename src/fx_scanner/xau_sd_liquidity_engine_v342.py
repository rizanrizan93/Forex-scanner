from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from math import isfinite
from typing import Any, Iterable, Sequence

import pandas as pd

from .models import ensure_utc

CONTRACT = "XAU_RIZAN_SD_LIQUIDITY_V342_1"
DISPLAY_NAME = "RIZAN SUPPLY DEMAND + LIQUIDITY"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False

# Frozen first-generation thresholds. They are deliberately simple and causal.
TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}

TF_PARAMS = {
    "H1": {
        "departure_range_atr": 0.90,
        "departure_body_fraction": 0.50,
        "max_base_range_atr": 1.25,
        "lookback_structure": 8,
        "lifecycle_hours": 24 * 21,
    },
    "H4": {
        "departure_range_atr": 0.80,
        "departure_body_fraction": 0.45,
        "max_base_range_atr": 1.35,
        "lookback_structure": 6,
        "lifecycle_hours": 24 * 60,
    },
}

# Existing V225 evidence already covers 2012-2026 and is used only as a prior.
# It is not presented as a calibrated probability for the current setup.
HISTORICAL_DEPTH_PRIOR = {
    "source": "XAU_ZONE_REVERSAL_DEPTH_V225_2",
    "years": list(range(2012, 2027)),
    "episodes_all_timeframes": 68094,
    "H4": {
        "touches": 4831,
        "hold_rate_050_atr": 0.7137238666942662,
        "wilson_lower_95": 0.7008115969520319,
        "turning_depth_median": 0.20026505669269531,
        "turning_depth_p75": 0.4440582246693734,
    },
    "H1": {
        "touches": 14570,
        "hold_rate_050_atr": 0.7096087851750171,
        "wilson_lower_95": 0.7021834162175125,
        "turning_depth_median": 0.2088400680004925,
        "turning_depth_p75": 0.4516372141372115,
    },
    "depth_coordinate": "FULL_ZONE_NEAR_EDGE_TO_FAR_EDGE",
    "note": (
        "Historical descriptive prior only. HOLD means >=0.50 ATR reaction before "
        "a causal distal-close break in the V225 replay."
    ),
}


@dataclass(frozen=True, slots=True)
class SDZone:
    zone_id: str
    timeframe: str
    direction: str
    pattern: str
    zone_class: str
    low: float
    high: float
    proximal: float
    distal: float
    origin_at: datetime
    available_at: datetime
    atr: float
    base_bars: int
    base_range_atr: float
    departure_range_atr: float
    departure_body_fraction: float
    structural_bos: bool
    score_seed: float


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _bar_frame(bars: Iterable[Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
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
    out = pd.DataFrame(rows).drop_duplicates("timestamp", keep="last")
    return out.sort_values("timestamp").reset_index(drop=True)


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


def _stable_id(
    *,
    timeframe: str,
    direction: str,
    origin_at: datetime,
    available_at: datetime,
    low: float,
    high: float,
) -> str:
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


def detect_zones(
    bars: Iterable[Any],
    *,
    timeframe: str,
    as_of: datetime,
) -> tuple[SDZone, ...]:
    """Detect compact base -> displacement zones without future pivots.

    A zone becomes available only after the departure candle closes. Structural
    confirmation uses only bars that were already complete before the base.
    """
    tf = str(timeframe).upper()
    if tf not in TF_PARAMS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    params = TF_PARAMS[tf]
    frame = _bar_frame(bars)
    if len(frame) < 24:
        return ()
    known_delta = pd.Timedelta(minutes=TF_MINUTES[tf])
    frame = frame[
        (frame["timestamp"] + known_delta) <= pd.Timestamp(ensure_utc(as_of))
    ].copy()
    if len(frame) < 24:
        return ()
    frame["atr14"] = _atr(frame)
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
        candle_range = max(h - l, 1e-9)
        range_atr = candle_range / atr
        body_fraction = abs(c - o) / candle_range
        if range_atr < float(params["departure_range_atr"]):
            continue
        if body_fraction < float(params["departure_body_fraction"]):
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
            if width_atr > float(params["max_base_range_atr"]):
                continue
            body_fraction_mean = float(
                (
                    (base["close"] - base["open"]).abs()
                    / (base["high"] - base["low"]).clip(lower=1e-9)
                ).mean()
            )
            compactness = width_atr + 0.35 * body_fraction_mean
            if best is None or compactness < best[0]:
                best = (compactness, base_len, base)
        if best is None:
            continue

        _, base_len, base = best
        low, high, proximal, distal = _zone_geometry(base, direction)
        width = high - low
        if width <= 0:
            continue

        # Departure must actually leave the base, not merely be a large candle.
        departure_buffer = 0.05 * atr
        if direction == "LONG" and c <= high + departure_buffer:
            continue
        if direction == "SHORT" and c >= low - departure_buffer:
            continue

        structure_start = max(0, i - base_len - int(params["lookback_structure"]))
        structure_end = i - base_len
        prior = frame.iloc[structure_start:structure_end]
        if prior.empty:
            continue
        structural_bos = bool(
            c > float(prior["high"].max())
            if direction == "LONG"
            else c < float(prior["low"].min())
        )
        # Very strong displacement may seed a zone before a full local BOS.
        if not structural_bos and range_atr < 1.25:
            continue

        origin_at = ensure_utc(base.iloc[0]["timestamp"].to_pydatetime())
        available_at = ensure_utc(
            (departure["timestamp"] + known_delta).to_pydatetime()
        )
        pre_close = float(frame.iloc[i - base_len - 1]["close"])
        zone_class = "STRUCTURAL_BOS" if structural_bos else "DISPLACEMENT"
        score = (
            45.0
            + (12.0 if tf == "H4" else 7.0)
            + (16.0 if structural_bos else 5.0)
            + min(15.0, max(0.0, (range_atr - 0.8) * 12.0))
            + min(8.0, body_fraction * 8.0)
            - min(10.0, max(0.0, width / atr - 0.6) * 8.0)
        )
        zones.append(
            SDZone(
                zone_id=_stable_id(
                    timeframe=tf,
                    direction=direction,
                    origin_at=origin_at,
                    available_at=available_at,
                    low=low,
                    high=high,
                ),
                timeframe=tf,
                direction=direction,
                pattern=_pattern(direction, pre_close, (low + high) / 2.0),
                zone_class=zone_class,
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


def _lifecycle(zone: SDZone, bars: Iterable[Any], *, as_of: datetime) -> dict[str, Any]:
    frame = _bar_frame(bars)
    if frame.empty:
        return {"active": True, "touch_count": 0, "freshness": "UNKNOWN"}
    known_delta = pd.Timedelta(minutes=TF_MINUTES[zone.timeframe])
    frame = frame.copy()
    frame["known_at"] = frame["timestamp"] + known_delta
    future = frame[
        (frame["known_at"] > pd.Timestamp(zone.available_at))
        & (frame["known_at"] <= pd.Timestamp(ensure_utc(as_of)))
    ]
    width = max(zone.high - zone.low, 1e-9)
    touch_count = 0
    was_inside = False
    first_touch_at: str | None = None
    last_touch_at: str | None = None
    invalidated_at: str | None = None
    max_mitigation = 0.0

    for _, row in future.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        ts = ensure_utc(row["known_at"].to_pydatetime())
        inside = high >= zone.low and low <= zone.high
        if inside and not was_inside:
            touch_count += 1
            if first_touch_at is None:
                first_touch_at = ts.isoformat()
        if inside:
            last_touch_at = ts.isoformat()
            if zone.direction == "LONG":
                adverse = max(zone.low, low)
                depth = (zone.high - adverse) / width
            else:
                adverse = min(zone.high, high)
                depth = (adverse - zone.low) / width
            max_mitigation = max(max_mitigation, min(1.5, max(0.0, depth)))
        invalid = (
            close < zone.distal - 0.05 * zone.atr
            if zone.direction == "LONG"
            else close > zone.distal + 0.05 * zone.atr
        )
        if invalid:
            invalidated_at = ts.isoformat()
            break
        was_inside = inside

    if invalidated_at:
        freshness = "BROKEN"
    elif touch_count == 0:
        freshness = "FRESH"
    elif max_mitigation >= 0.75:
        freshness = "DEEPLY_MITIGATED"
    elif max_mitigation >= 0.35:
        freshness = "PARTIALLY_MITIGATED"
    elif touch_count == 1:
        freshness = "FIRST_TEST"
    else:
        freshness = "RETESTED"
    age_hours = max(
        0.0, (ensure_utc(as_of) - ensure_utc(zone.available_at)).total_seconds() / 3600.0
    )
    expired = age_hours > float(TF_PARAMS[zone.timeframe]["lifecycle_hours"])
    return {
        "active": bool(not invalidated_at and not expired),
        "touch_count": touch_count,
        "first_touch_at": first_touch_at,
        "last_touch_at": last_touch_at,
        "invalidated_at": invalidated_at,
        "mitigation_depth": round(max_mitigation, 4),
        "freshness": "EXPIRED" if expired and not invalidated_at else freshness,
        "age_hours": round(age_hours, 2),
    }


def _distance(price: float, low: float, high: float) -> float:
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _dedupe(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda x: (
            str(x.get("timeframe")) == "H4",
            float(x.get("score") or 0.0),
            str(x.get("available_at") or ""),
        ),
        reverse=True,
    )
    kept: list[dict[str, Any]] = []
    for row in ordered:
        duplicate = False
        for other in kept:
            if row["direction"] != other["direction"] or row["timeframe"] != other["timeframe"]:
                continue
            overlap = max(
                0.0,
                min(float(row["high"]), float(other["high"]))
                - max(float(row["low"]), float(other["low"])),
            )
            minimum = max(
                min(
                    float(row["high"]) - float(row["low"]),
                    float(other["high"]) - float(other["low"]),
                ),
                1e-9,
            )
            if overlap / minimum >= 0.75:
                duplicate = True
                break
        if not duplicate:
            kept.append(row)
    return kept


def _market_structure(
    bars: Iterable[Any],
    *,
    timeframe: str,
    as_of: datetime,
) -> dict[str, Any]:
    frame = _bar_frame(bars)
    known_delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
    frame = frame[
        (frame["timestamp"] + known_delta) <= pd.Timestamp(ensure_utc(as_of))
    ].copy()
    if len(frame) < 24:
        return {"timeframe": timeframe, "state": "UNKNOWN"}
    frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
    last = frame.iloc[-1]
    prior = frame.iloc[-9:-1]
    close = float(last["close"])
    broke_high = close > float(prior["high"].max())
    broke_low = close < float(prior["low"].min())
    if broke_high and close >= float(last["ema20"]):
        state = "BULLISH_BREAK"
    elif broke_low and close <= float(last["ema20"]):
        state = "BEARISH_BREAK"
    elif close > float(last["ema20"]):
        state = "BULLISH_RANGE"
    elif close < float(last["ema20"]):
        state = "BEARISH_RANGE"
    else:
        state = "NEUTRAL"
    return {
        "timeframe": timeframe,
        "state": state,
        "last_close": close,
        "ema20": float(last["ema20"]),
        "prior_range_high": float(prior["high"].max()),
        "prior_range_low": float(prior["low"].min()),
    }


def _pivot_levels(
    bars: Iterable[Any],
    *,
    timeframe: str,
    as_of: datetime,
) -> list[dict[str, Any]]:
    frame = _bar_frame(bars)
    if len(frame) < 7:
        return []
    known_delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
    frame = frame[
        (frame["timestamp"] + known_delta) <= pd.Timestamp(ensure_utc(as_of))
    ].copy()
    if len(frame) < 7:
        return []
    frame["atr14"] = _atr(frame)
    output: list[dict[str, Any]] = []
    for i in range(2, len(frame) - 2):
        # A pivot is only known after two later candles close.
        known_at = ensure_utc(
            (frame.iloc[i + 2]["timestamp"] + known_delta).to_pydatetime()
        )
        if known_at >= ensure_utc(as_of):
            continue
        row = frame.iloc[i]
        around = frame.iloc[i - 2 : i + 3]
        atr = _f(row.get("atr14"))
        if atr is None or atr <= 0:
            continue
        if float(row["high"]) >= float(around["high"].max()):
            output.append(
                {
                    "side": "BUY_SIDE",
                    "price": float(row["high"]),
                    "source": f"{timeframe}_SWING_HIGH",
                    "available_at": known_at.isoformat(),
                    "atr": atr,
                }
            )
        if float(row["low"]) <= float(around["low"].min()):
            output.append(
                {
                    "side": "SELL_SIDE",
                    "price": float(row["low"]),
                    "source": f"{timeframe}_SWING_LOW",
                    "available_at": known_at.isoformat(),
                    "atr": atr,
                }
            )
    return output[-80:]


def _cluster_liquidity(
    levels: Sequence[dict[str, Any]],
    *,
    price_now: float,
    atr_reference: float,
) -> list[dict[str, Any]]:
    tolerance = max(0.08 * atr_reference, 0.75)
    sorted_levels = sorted(levels, key=lambda x: float(x["price"]))
    clusters: list[list[dict[str, Any]]] = []
    for level in sorted_levels:
        if not clusters:
            clusters.append([level])
            continue
        center = sum(float(x["price"]) for x in clusters[-1]) / len(clusters[-1])
        if abs(float(level["price"]) - center) <= tolerance:
            clusters[-1].append(level)
        else:
            clusters.append([level])
    output: list[dict[str, Any]] = []
    for cluster in clusters:
        center = sum(float(x["price"]) for x in cluster) / len(cluster)
        if abs(center - price_now) > 4.0 * atr_reference:
            continue
        side_counts = {
            "BUY_SIDE": sum(1 for x in cluster if x["side"] == "BUY_SIDE"),
            "SELL_SIDE": sum(1 for x in cluster if x["side"] == "SELL_SIDE"),
        }
        side = "BUY_SIDE" if side_counts["BUY_SIDE"] >= side_counts["SELL_SIDE"] else "SELL_SIDE"
        output.append(
            {
                "side": side,
                "price": center,
                "strength": len(cluster),
                "sources": sorted({str(x["source"]) for x in cluster}),
                "distance_atr": abs(center - price_now) / max(atr_reference, 1e-9),
            }
        )

    # Round-number candidates are liquidity hypotheses, not proof of resting stops.
    for step in (10.0, 25.0, 50.0):
        rounded = round(price_now / step) * step
        for candidate in (rounded - step, rounded, rounded + step):
            if abs(candidate - price_now) <= 3.0 * atr_reference:
                output.append(
                    {
                        "side": "BOTH",
                        "price": float(candidate),
                        "strength": 1,
                        "sources": [f"ROUND_{int(step)}"],
                        "distance_atr": abs(candidate - price_now) / max(atr_reference, 1e-9),
                    }
                )
    output.sort(key=lambda x: (float(x["distance_atr"]), -int(x["strength"])))
    return output[:24]


def _sweep_map(
    zone: dict[str, Any],
    *,
    zones: Sequence[dict[str, Any]],
    liquidity: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    direction = str(zone["direction"])
    atr = max(float(zone["atr"]), 1e-9)
    low, high = float(zone["low"]), float(zone["high"])
    band_low, band_high = low, high
    relevant_side = "SELL_SIDE" if direction == "LONG" else "BUY_SIDE"

    parents = []
    for other in zones:
        if other["zone_id"] == zone["zone_id"] or other["direction"] != direction:
            continue
        if other["timeframe"] != "H4":
            continue
        overlap = max(
            0.0,
            min(high, float(other["high"])) - max(low, float(other["low"])),
        )
        near = _distance(
            (low + high) / 2.0,
            float(other["low"]),
            float(other["high"]),
        )
        if overlap > 0 or near <= 0.50 * atr:
            parents.append(other)
            if direction == "LONG":
                band_low = min(band_low, float(other["low"]))
            else:
                band_high = max(band_high, float(other["high"]))

    selected_levels: list[dict[str, Any]] = []
    for level in liquidity:
        side = str(level.get("side") or "")
        px = float(level["price"])
        if side not in {relevant_side, "BOTH"}:
            continue
        if direction == "LONG":
            if px <= high and px >= low - atr:
                selected_levels.append(level)
                if px <= low:
                    band_low = min(band_low, px)
        else:
            if px >= low and px <= high + atr:
                selected_levels.append(level)
                if px >= high:
                    band_high = max(band_high, px)

    # Never let a distant, unrelated level inflate the decision band.
    band_low = max(band_low, low - atr)
    band_high = min(band_high, high + atr)
    extension = max(low - band_low, band_high - high, 0.0)
    return {
        "side": "BELOW_DEMAND" if direction == "LONG" else "ABOVE_SUPPLY",
        "low": band_low,
        "high": band_high,
        "extension_atr": extension / atr,
        "parent_extension": bool(parents),
        "liquidity_candidates": selected_levels[:10],
        "parent_zones": [
            {
                "zone_id": p["zone_id"],
                "timeframe": p["timeframe"],
                "low": p["low"],
                "high": p["high"],
                "score": p["score"],
            }
            for p in parents[:4]
        ],
        "warning": (
            "LIQUIDITY_SWEEP_POSSIBLE_BEFORE_REVERSAL"
            if extension > 0 or selected_levels
            else "NO_MAPPED_EXTENSION"
        ),
    }


def _micro_confirmation(
    zone: dict[str, Any],
    *,
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    price_now: float,
    as_of: datetime,
) -> dict[str, Any]:
    direction = str(zone["direction"])
    m5 = _bar_frame(bars_m5)
    m15 = _bar_frame(bars_m15)
    if len(m5) >= 20:
        frame = m5.copy()
        micro_tf = "M5"
    else:
        frame = m15.copy()
        micro_tf = "M15"
    known_delta = pd.Timedelta(minutes=TF_MINUTES[micro_tf])
    frame = frame[
        (frame["timestamp"] + known_delta) <= pd.Timestamp(ensure_utc(as_of))
    ].copy()
    if len(frame) < 20:
        return {"stage": "NO_MICRO_DATA", "confirmed": False}
    frame = frame.tail(96).copy()
    frame["atr14"] = _atr(frame)
    zone_low, zone_high = float(zone["low"]), float(zone["high"])
    atr = max(float(zone["atr"]), 1e-9)
    recent = frame.tail(30)
    touched = bool(
        ((recent["high"] >= zone_low) & (recent["low"] <= zone_high)).any()
    )
    sweep = bool(
        (recent["low"] < zone_low).any()
        if direction == "LONG"
        else (recent["high"] > zone_high).any()
    )

    reclaim_idx: int | None = None
    for i in range(1, len(recent)):
        row = recent.iloc[i]
        if direction == "LONG" and float(row["close"]) > zone_low and float(row["low"]) < zone_high:
            reclaim_idx = i
        if direction == "SHORT" and float(row["close"]) < zone_high and float(row["high"]) > zone_low:
            reclaim_idx = i
    if reclaim_idx is None:
        relation = (
            "INSIDE_ZONE"
            if zone_low <= price_now <= zone_high
            else "APPROACH"
            if _distance(price_now, zone_low, zone_high) <= atr
            else "FAR"
        )
        return {
            "stage": "SWEEP_RISK" if sweep else relation,
            "confirmed": False,
            "touched": touched,
            "sweep_seen": sweep,
        }

    local = recent.iloc[max(0, reclaim_idx - 6) : reclaim_idx + 1]
    reclaim = recent.iloc[reclaim_idx]
    local_atr = _f(reclaim.get("atr14")) or atr / (12.0 if zone["timeframe"] == "H1" else 48.0)
    local_atr = max(float(local_atr), 1e-9)
    rng = max(float(reclaim["high"]) - float(reclaim["low"]), 1e-9)
    body_fraction = abs(float(reclaim["close"]) - float(reclaim["open"])) / rng
    displacement = bool(rng >= 0.80 * local_atr and body_fraction >= 0.50)

    before = recent.iloc[max(0, reclaim_idx - 6) : reclaim_idx]
    if before.empty:
        mss = False
        mss_level = None
    elif direction == "LONG":
        mss_level = float(before["high"].max())
        mss = float(reclaim["close"]) > mss_level
    else:
        mss_level = float(before["low"].min())
        mss = float(reclaim["close"]) < mss_level

    confirmed = bool(touched and mss and displacement)
    if confirmed:
        # 38-62% retrace of the confirmation candle, clipped to the broad
        # structural zone/sweep envelope. This is guidance only.
        lo, hi = float(reclaim["low"]), float(reclaim["high"])
        if direction == "LONG":
            entry_low = lo + 0.38 * (hi - lo)
            entry_high = lo + 0.62 * (hi - lo)
            invalidation = min(zone_low, float(recent["low"].min())) - 0.10 * local_atr
        else:
            entry_low = hi - 0.62 * (hi - lo)
            entry_high = hi - 0.38 * (hi - lo)
            invalidation = max(zone_high, float(recent["high"].max())) + 0.10 * local_atr
        entry_reference = (entry_low + entry_high) / 2.0
        stage = "REVERSAL_CONFIRMED"
    else:
        entry_low = entry_high = entry_reference = invalidation = None
        stage = "RECLAIM_WAIT_MSS_DISPLACEMENT"

    return {
        "stage": stage,
        "confirmed": confirmed,
        "touched": touched,
        "sweep_seen": sweep,
        "reclaim_at": ensure_utc(reclaim["timestamp"].to_pydatetime()).isoformat(),
        "mss_confirmed": bool(mss),
        "mss_level": mss_level,
        "displacement_confirmed": displacement,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference": entry_reference,
        "invalidation": invalidation,
    }


def _targets(
    *,
    direction: str,
    entry: float | None,
    active_zones: Sequence[dict[str, Any]],
    fallback_atr: float,
) -> list[dict[str, Any]]:
    if entry is None:
        return []
    opposite = "SHORT" if direction == "LONG" else "LONG"
    candidates = []
    for zone in active_zones:
        if zone["direction"] != opposite:
            continue
        if direction == "LONG" and float(zone["low"]) <= entry:
            continue
        if direction == "SHORT" and float(zone["high"]) >= entry:
            continue
        target = float(zone["low"]) if direction == "LONG" else float(zone["high"])
        candidates.append(
            {
                "price": target,
                "source": f"{zone['timeframe']}_{'SUPPLY' if opposite == 'SHORT' else 'DEMAND'}",
                "zone_id": zone["zone_id"],
                "distance": abs(target - entry),
            }
        )
    candidates.sort(key=lambda x: float(x["distance"]))
    if candidates:
        return candidates[:3]
    sign = 1.0 if direction == "LONG" else -1.0
    return [
        {"price": entry + sign * 0.50 * fallback_atr, "source": "FALLBACK_0P50_ATR"},
        {"price": entry + sign * 1.00 * fallback_atr, "source": "FALLBACK_1P00_ATR"},
    ]


def evaluate_sd_liquidity(
    *,
    bars_h1: Iterable[Any],
    bars_h4: Iterable[Any],
    bars_m15: Iterable[Any],
    bars_m5: Iterable[Any],
    as_of: datetime,
    price_now: float | None = None,
) -> dict[str, Any]:
    now = ensure_utc(as_of)
    h1_frame = _bar_frame(bars_h1)
    h4_frame = _bar_frame(bars_h4)
    if h1_frame.empty or h4_frame.empty:
        return {
            "contract": CONTRACT,
            "state": "INSUFFICIENT_HTF_DATA",
            "execution_authority": False,
            "execution_influence": False,
        }
    current = _f(price_now)
    if current is None:
        m5_frame = _bar_frame(bars_m5)
        current = float(m5_frame.iloc[-1]["close"]) if not m5_frame.empty else float(h1_frame.iloc[-1]["close"])

    zone_objects = [
        *detect_zones(bars_h4, timeframe="H4", as_of=now),
        *detect_zones(bars_h1, timeframe="H1", as_of=now),
    ]
    payloads: list[dict[str, Any]] = []
    for zone in zone_objects:
        life = _lifecycle(
            zone,
            bars_h4 if zone.timeframe == "H4" else bars_h1,
            as_of=now,
        )
        if not life.get("active"):
            continue
        row = asdict(zone)
        row["origin_at"] = ensure_utc(zone.origin_at).isoformat()
        row["available_at"] = ensure_utc(zone.available_at).isoformat()
        mitigation = float(life.get("mitigation_depth") or 0.0)
        touch_penalty = min(18.0, int(life.get("touch_count") or 0) * 4.0)
        row["lifecycle"] = life
        row["distance_points"] = _distance(current, zone.low, zone.high)
        row["distance_atr"] = row["distance_points"] / max(zone.atr, 1e-9)
        row["score"] = round(
            float(zone.score_seed) - touch_penalty - 10.0 * min(1.0, mitigation),
            2,
        )
        payloads.append(row)

    active = _dedupe(payloads)
    demands = [x for x in active if x["direction"] == "LONG"]
    supplies = [x for x in active if x["direction"] == "SHORT"]
    demands.sort(key=lambda x: (float(x["distance_points"]), -float(x["score"])))
    supplies.sort(key=lambda x: (float(x["distance_points"]), -float(x["score"])))
    nearest_demand = dict(demands[0]) if demands else {}
    nearest_supply = dict(supplies[0]) if supplies else {}

    h1_atr_series = _atr(h1_frame)
    atr_ref = _f(h1_atr_series.iloc[-1]) or max(current * 0.002, 1.0)
    raw_levels = [
        *_pivot_levels(bars_h4, timeframe="H4", as_of=now),
        *_pivot_levels(bars_h1, timeframe="H1", as_of=now),
    ]
    liquidity = _cluster_liquidity(
        raw_levels,
        price_now=current,
        atr_reference=float(atr_ref),
    )

    candidates = [x for x in (nearest_demand, nearest_supply) if x]
    candidates.sort(
        key=lambda x: (
            float(x["distance_points"]) / max(float(x["atr"]), 1e-9),
            -float(x["score"]),
        )
    )
    decision_zone = dict(candidates[0]) if candidates else {}
    sweep_map = (
        _sweep_map(decision_zone, zones=active, liquidity=liquidity)
        if decision_zone
        else {}
    )
    micro = (
        _micro_confirmation(
            decision_zone,
            bars_m5=bars_m5,
            bars_m15=bars_m15,
            price_now=current,
            as_of=now,
        )
        if decision_zone
        else {"stage": "NO_DECISION_ZONE", "confirmed": False}
    )
    direction = str(decision_zone.get("direction") or "WAIT")
    entry = _f(micro.get("entry_reference"))
    targets = _targets(
        direction=direction,
        entry=entry,
        active_zones=active,
        fallback_atr=float(decision_zone.get("atr") or atr_ref),
    ) if direction in {"LONG", "SHORT"} else []

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "state": "MAP_AVAILABLE" if active else "NO_ACTIVE_HTF_ZONE",
        "as_of": now.isoformat(),
        "price_now": current,
        "market_structure": {
            "H4": _market_structure(bars_h4, timeframe="H4", as_of=now),
            "H1": _market_structure(bars_h1, timeframe="H1", as_of=now),
        },
        "nearest_demand": nearest_demand,
        "nearest_supply": nearest_supply,
        "decision_zone": decision_zone,
        "expected_reversal_direction": direction,
        "liquidity_map": sweep_map,
        "micro_confirmation": micro,
        "entry_guide": {
            "state": "CONFIRMED_GUIDANCE" if bool(micro.get("confirmed")) else "WAIT_CONFIRMATION",
            "direction": direction,
            "entry_low": micro.get("entry_low"),
            "entry_high": micro.get("entry_high"),
            "entry_reference": entry,
            "invalidation": micro.get("invalidation"),
            "targets": targets,
            "rule": (
                "HTF_ZONE -> LIQUIDITY_SWEEP_OPTIONAL -> RECLAIM -> MSS -> DISPLACEMENT -> RETEST"
            ),
        },
        "liquidity_candidates": liquidity,
        "active_zones": active[:16],
        "historical_depth_prior": HISTORICAL_DEPTH_PRIOR,
        "method": {
            "zone_formation": (
                "H1/H4 compact 1-3 candle base followed by ATR-normalized displacement; "
                "requires causal local BOS or >=1.25 ATR displacement."
            ),
            "zone_bounds": "FULL_BASE_WITH_BODY_AWARE_PROXIMAL_AND_WICK_DISTAL",
            "invalidation": "CLOSE_BEYOND_DISTAL_PLUS_0P05_PARENT_ATR",
            "liquidity": (
                "confirmed swing clusters + round-number candidates + overlapping H4 parent; "
                "liquidity levels are hypotheses, not proof of resting institutional orders."
            ),
            "reversal_confirmation": "TOUCH/SWEEP + RECLAIM + LOCAL_MSS + DISPLACEMENT",
            "rebuild_policy": "RECALCULATE_FROM_COMPLETED_H4_H1_M15_M5_ON_EACH_RUNTIME_CYCLE",
        },
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }
