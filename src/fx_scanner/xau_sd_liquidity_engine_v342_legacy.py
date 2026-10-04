from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from math import isfinite
from typing import Any, Iterable, Sequence

import pandas as pd

from .models import ensure_utc
from .xau_structural_sr_map_v363 import build_structural_sr_map

CONTRACT = "XAU_RIZAN_SD_LIQUIDITY_V342_12_INTRADAY_REROUTE_V369"
DISPLAY_NAME = "RIZAN SUPPLY DEMAND + LIQUIDITY"
EXECUTION_AUTHORITY = True
EXECUTION_INFLUENCE = True
EXECUTION_SCOPE = "DEMO_ONLY"
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


def _intraday_breach_status(
    zone: dict[str, Any],
    *,
    bars_m15: Iterable[Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Quarantine an HTF zone after a causal M15 breach before H4 close.

    The canonical H4 lifecycle remains unchanged. This guard only prevents an
    already-breached parent from continuing to publish a stale PREPARE band
    while waiting for the next H4 candle close.

    A zone is quarantined when the latest completed M15 close is:
    - >=0.25 parent ATR beyond the distal boundary, or
    - the second consecutive completed M15 close >=0.05 ATR beyond distal.

    A later completed M15 reclaim back inside the 0.05 ATR buffer releases the
    quarantine, so a transient sweep is not permanently classified as failure.
    """
    frame = _bar_frame(bars_m15)
    if frame.empty:
        return {
            "state": "NO_M15_DATA",
            "quarantined": False,
            "validation_timeframe": "M15",
        }

    known_delta = pd.Timedelta(minutes=TF_MINUTES["M15"])
    now = pd.Timestamp(ensure_utc(as_of))
    available_raw = zone.get("available_at")
    available_at = pd.Timestamp(available_raw) if available_raw else None
    if available_at is not None:
        if available_at.tzinfo is None:
            available_at = available_at.tz_localize("UTC")
        else:
            available_at = available_at.tz_convert("UTC")

    completed = frame[(frame["timestamp"] + known_delta) <= now].copy()
    if available_at is not None:
        completed = completed[(completed["timestamp"] + known_delta) > available_at].copy()
    completed = completed.tail(4).reset_index(drop=True)
    if completed.empty:
        return {
            "state": "WAIT_COMPLETED_M15_AFTER_ZONE_AVAILABLE",
            "quarantined": False,
            "validation_timeframe": "M15",
        }

    atr = max(float(zone.get("atr") or 0.0), 1e-9)
    distal = float(zone.get("distal"))
    direction = str(zone.get("direction") or "")
    soft = 0.05 * atr
    deep = 0.25 * atr
    closes = completed["close"].astype(float)

    if direction == "LONG":
        beyond = closes < (distal - soft)
        deep_beyond = closes < (distal - deep)
        depth_atr = max(0.0, distal - float(closes.iloc[-1])) / atr
    elif direction == "SHORT":
        beyond = closes > (distal + soft)
        deep_beyond = closes > (distal + deep)
        depth_atr = max(0.0, float(closes.iloc[-1]) - distal) / atr
    else:
        return {
            "state": "INVALID_DIRECTION",
            "quarantined": False,
            "validation_timeframe": "M15",
        }

    latest_beyond = bool(beyond.iloc[-1])
    deep_latest = bool(deep_beyond.iloc[-1])
    two_consecutive = bool(
        len(beyond) >= 2 and bool(beyond.iloc[-1]) and bool(beyond.iloc[-2])
    )
    quarantined = bool(latest_beyond and (deep_latest or two_consecutive))
    if quarantined:
        state = "INTRADAY_BREACH_QUARANTINED"
    elif latest_beyond:
        state = "INTRADAY_BREACH_WATCH"
    else:
        state = "NO_ACTIVE_INTRADAY_BREACH"

    last_row = completed.iloc[-1]
    completed_at = ensure_utc(
        (last_row["timestamp"] + known_delta).to_pydatetime()
    ).isoformat()
    return {
        "state": state,
        "quarantined": quarantined,
        "validation_timeframe": "M15",
        "latest_completed_at": completed_at,
        "latest_close": float(closes.iloc[-1]),
        "distal": distal,
        "soft_buffer_atr": 0.05,
        "deep_buffer_atr": 0.25,
        "breach_depth_atr": round(depth_atr, 4),
        "latest_beyond": latest_beyond,
        "deep_latest": deep_latest,
        "two_consecutive": two_consecutive,
        "completed_bars_beyond": int(beyond.sum()),
        "rule": (
            "M15_DEEP_CLOSE_GTE_0P25_PARENT_ATR_OR_TWO_CONSECUTIVE_CLOSES_"
            "BEYOND_DISTAL_PLUS_0P05_ATR; RECLAIM_RELEASES_QUARANTINE"
        ),
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


def _h2_frame_from_h1(
    bars_h1: Iterable[Any],
    *,
    as_of: datetime,
) -> pd.DataFrame:
    """Build causal UTC H2 candles from two completed H1 candles."""
    frame = _bar_frame(bars_h1)
    if frame.empty:
        return frame
    now = pd.Timestamp(ensure_utc(as_of))
    frame = frame[(frame["timestamp"] + pd.Timedelta(hours=1)) <= now].copy()
    if frame.empty:
        return frame
    frame["bucket"] = frame["timestamp"].dt.floor("2h")
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby("bucket", sort=True):
        g = group.sort_values("timestamp")
        expected = [bucket, bucket + pd.Timedelta(hours=1)]
        actual = list(g["timestamp"].iloc[:2])
        if len(g) < 2 or actual != expected:
            continue
        if bucket + pd.Timedelta(hours=2) > now:
            continue
        rows.append(
            {
                "timestamp": bucket,
                "open": float(g.iloc[0]["open"]),
                "high": float(g.iloc[:2]["high"].max()),
                "low": float(g.iloc[:2]["low"].min()),
                "close": float(g.iloc[1]["close"]),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def _h2_support_resistance(
    bars_h1: Iterable[Any],
    *,
    as_of: datetime,
    price_now: float,
    atr_reference: float,
) -> list[dict[str, Any]]:
    """Map H2 pivots plus prior-day/week S/R as context, never as a direction signal."""
    now = pd.Timestamp(ensure_utc(as_of))
    h2 = _h2_frame_from_h1(bars_h1, as_of=as_of)
    raw: list[dict[str, Any]] = []

    if len(h2) >= 7:
        for i in range(2, len(h2) - 2):
            row = h2.iloc[i]
            around = h2.iloc[i - 2 : i + 3]
            known_at = h2.iloc[i + 2]["timestamp"] + pd.Timedelta(hours=2)
            if known_at > now:
                continue
            if float(row["high"]) >= float(around["high"].max()):
                raw.append(
                    {
                        "kind": "RESISTANCE",
                        "price": float(row["high"]),
                        "source": "H2_SWING_HIGH",
                        "available_at": known_at.isoformat(),
                        "weight": 1.0,
                    }
                )
            if float(row["low"]) <= float(around["low"].min()):
                raw.append(
                    {
                        "kind": "SUPPORT",
                        "price": float(row["low"]),
                        "source": "H2_SWING_LOW",
                        "available_at": known_at.isoformat(),
                        "weight": 1.0,
                    }
                )

    h1 = _bar_frame(bars_h1)
    if not h1.empty:
        h1 = h1[(h1["timestamp"] + pd.Timedelta(hours=1)) <= now].copy()
    if not h1.empty:
        h1["day"] = h1["timestamp"].dt.floor("D")
        current_day = now.floor("D")
        previous_days = h1[h1["day"] < current_day]
        if not previous_days.empty:
            prior_day = previous_days["day"].max()
            day_frame = previous_days[previous_days["day"] == prior_day]
            raw.extend(
                [
                    {
                        "kind": "RESISTANCE",
                        "price": float(day_frame["high"].max()),
                        "source": "PRIOR_DAY_HIGH",
                        "available_at": current_day.isoformat(),
                        "weight": 1.5,
                    },
                    {
                        "kind": "SUPPORT",
                        "price": float(day_frame["low"].min()),
                        "source": "PRIOR_DAY_LOW",
                        "available_at": current_day.isoformat(),
                        "weight": 1.5,
                    },
                ]
            )

        h1["week_start"] = (
            h1["timestamp"].dt.floor("D")
            - pd.to_timedelta(h1["timestamp"].dt.weekday, unit="D")
        )
        current_week = now.floor("D") - pd.Timedelta(days=now.weekday())
        previous_weeks = h1[h1["week_start"] < current_week]
        if not previous_weeks.empty:
            prior_week = previous_weeks["week_start"].max()
            week_frame = previous_weeks[previous_weeks["week_start"] == prior_week]
            raw.extend(
                [
                    {
                        "kind": "RESISTANCE",
                        "price": float(week_frame["high"].max()),
                        "source": "PRIOR_WEEK_HIGH",
                        "available_at": current_week.isoformat(),
                        "weight": 2.0,
                    },
                    {
                        "kind": "SUPPORT",
                        "price": float(week_frame["low"].min()),
                        "source": "PRIOR_WEEK_LOW",
                        "available_at": current_week.isoformat(),
                        "weight": 2.0,
                    },
                ]
            )

    if not raw:
        return []

    tolerance = max(0.10 * max(float(atr_reference), 1e-9), 1.0)
    raw.sort(key=lambda x: float(x["price"]))
    groups: list[list[dict[str, Any]]] = []
    for level in raw:
        if not groups:
            groups.append([level])
            continue
        center = sum(float(x["price"]) * float(x["weight"]) for x in groups[-1]) / sum(
            float(x["weight"]) for x in groups[-1]
        )
        if abs(float(level["price"]) - center) <= tolerance:
            groups[-1].append(level)
        else:
            groups.append([level])

    output: list[dict[str, Any]] = []
    for group in groups:
        total_weight = sum(float(x["weight"]) for x in group)
        center = sum(float(x["price"]) * float(x["weight"]) for x in group) / total_weight
        supports = sum(float(x["weight"]) for x in group if x["kind"] == "SUPPORT")
        resistances = sum(float(x["weight"]) for x in group if x["kind"] == "RESISTANCE")
        if supports > 0 and resistances > 0:
            kind = "FLIP"
        elif supports >= resistances:
            kind = "SUPPORT"
        else:
            kind = "RESISTANCE"
        output.append(
            {
                "kind": kind,
                "price": center,
                "strength": round(total_weight, 2),
                "sources": sorted({str(x["source"]) for x in group}),
                "available_at": max(
                    str(x.get("available_at") or "") for x in group
                ),
                "distance_points": abs(center - price_now),
                "distance_atr": abs(center - price_now) / max(float(atr_reference), 1e-9),
                "role": "CONTEXT_ONLY_NO_DIRECTION_SIGNAL",
            }
        )
    output.sort(key=lambda x: (float(x["distance_points"]), -float(x["strength"])))
    return output[:18]


def _zone_condition(zone: dict[str, Any]) -> str:
    life = dict(zone.get("lifecycle") or {})
    touch = int(life.get("touch_count") or 0)
    mitigation = float(life.get("mitigation_depth") or 0.0)
    if mitigation >= 0.95 or touch >= 4:
        return "NEAR_EXHAUSTED"
    if mitigation >= 0.75 or touch >= 2:
        return "DEGRADED"
    if touch >= 1 or mitigation >= 0.35:
        return "TESTED"
    if touch == 0 and mitigation < 0.10:
        return "FRESH"
    return "ACTIVE"


def _main_reversal_profile(
    zone: dict[str, Any],
    *,
    price_now: float,
) -> dict[str, Any]:
    """Classify whether a zone can lead the next HTF reversal plan.

    Proximity alone is deliberately insufficient. Main reversal candidates must
    retain usable freshness and causal departure quality. Degraded zones remain
    visible as reaction/roadblock context but do not lead the entry plan.
    """
    life = dict(zone.get("lifecycle") or {})
    condition = str(zone.get("condition") or _zone_condition(zone))
    freshness = str(life.get("freshness") or "")
    touch_count = int(life.get("touch_count") or 0)
    mitigation = float(life.get("mitigation_depth") or 0.0)
    raw_score = float(zone.get("score") or zone.get("score_seed") or 80.0)
    atr = max(float(zone.get("atr") or 1.0), 1e-9)
    distance_atr = _distance(
        price_now, float(zone["low"]), float(zone["high"])
    ) / atr

    structural_raw = zone.get("structural_bos")
    structural_bos = True if structural_raw is None else bool(structural_raw)
    departure = float(zone.get("departure_range_atr") or 1.0)
    body_fraction = float(zone.get("departure_body_fraction") or 0.55)
    base_range = float(zone.get("base_range_atr") or 0.8)

    hard_reasons: list[str] = []
    if bool(zone.get("intraday_quarantined")):
        hard_reasons.append("INTRADAY_BREACH_QUARANTINED")
    if freshness in {"BROKEN", "EXPIRED"}:
        hard_reasons.append(freshness)
    if condition in {"DEGRADED", "NEAR_EXHAUSTED"}:
        hard_reasons.append(condition)
    if mitigation >= 0.80:
        hard_reasons.append("MITIGATION_GTE_80PCT")
    if touch_count >= 3:
        hard_reasons.append("TOUCH_COUNT_GTE_3")
    if raw_score < 70.0:
        hard_reasons.append("ZONE_SCORE_LT_70")
    if not structural_bos and not (
        departure >= 1.50 and body_fraction >= 0.55 and raw_score >= 80.0
    ):
        hard_reasons.append("NO_CAUSAL_BOS_OR_EXCEPTIONAL_DISPLACEMENT")

    condition_bonus = {
        "FRESH": 18.0,
        "TESTED": 10.0,
        "ACTIVE": 6.0,
    }.get(condition, -10.0)
    quality = (
        0.45 * raw_score
        + condition_bonus
        + (14.0 if structural_bos else 4.0)
        + min(12.0, max(0.0, departure - 0.75) * 8.0)
        + min(6.0, max(0.0, body_fraction - 0.40) * 20.0)
        - min(10.0, max(0.0, base_range - 0.80) * 8.0)
        - 18.0 * mitigation
        - 3.0 * max(0, touch_count - 1)
    )
    return {
        "eligible": not hard_reasons,
        "quality_score": round(quality, 2),
        "condition": condition,
        "freshness": freshness or condition,
        "distance_atr": distance_atr,
        "reasons": hard_reasons,
        "selection_rule": (
            "H4/H1_CAUSAL_QUALITY_FIRST: fresh/tested causal zone, "
            "structural BOS or exceptional displacement; degraded/exhausted "
            "zones remain context-only."
        ),
    }


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



def _prepared_entry_band(zone: dict[str, Any]) -> dict[str, Any]:
    """Forecast a preparation band before micro confirmation.

    The band uses the existing V225 historical turning-depth distribution. It is
    informational only: DEMO execution still requires fresh price confirmation.
    """
    if not zone:
        return {}
    timeframe = str(zone.get("timeframe") or "")
    prior = dict(HISTORICAL_DEPTH_PRIOR.get(timeframe) or {})
    median = _f(prior.get("turning_depth_median"))
    p75 = _f(prior.get("turning_depth_p75"))
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = str(zone.get("direction") or "")
    if (
        median is None
        or p75 is None
        or low is None
        or high is None
        or high <= low
        or direction not in {"LONG", "SHORT"}
    ):
        return {}
    shallow = min(median, p75)
    deep = max(median, p75)
    width = high - low
    if direction == "LONG":
        entry_low = high - deep * width
        entry_high = high - shallow * width
    else:
        entry_low = low + shallow * width
        entry_high = low + deep * width
    return {
        "state": "PREPARE_FORECAST",
        "direction": direction,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference": (entry_low + entry_high) / 2.0,
        "source": str(HISTORICAL_DEPTH_PRIOR.get("source") or "V225"),
        "depth_median": median,
        "depth_p75": p75,
        "execution_authority": False,
    }


def _micro_confirmation(
    zone: dict[str, Any],
    *,
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    price_now: float,
    as_of: datetime,
) -> dict[str, Any]:
    """Causal two-stage reversal confirmation.

    EARLY confirmation is intentionally Afiq-style: HTF touch/sweep plus a
    proximal reclaim and directional rejection/displacement. FULL confirmation
    additionally requires a local internal break after the reclaim. The local
    MSS level is anchored to the reclaim candle rather than an old six-bar
    extreme, preventing a news spike from moving the trigger far away.
    """
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
        return {
            "stage": "NO_MICRO_DATA",
            "confirmed": False,
            "early_confirmed": False,
        }

    frame = frame.tail(96).copy()
    frame["atr14"] = _atr(frame)
    recent = frame.tail(30).reset_index(drop=True)
    zone_low, zone_high = float(zone["low"]), float(zone["high"])
    proximal = _f(zone.get("proximal"))
    if proximal is None:
        proximal = zone_high if direction == "LONG" else zone_low
    atr = max(float(zone["atr"]), 1e-9)

    touch_mask = (recent["high"] >= zone_low) & (recent["low"] <= zone_high)
    touched = bool(touch_mask.any())
    if direction == "LONG":
        sweep_mask = recent["low"] < zone_low
    else:
        sweep_mask = recent["high"] > zone_high
    sweep = bool(sweep_mask.any())

    interaction_indices = [int(i) for i, flag in enumerate(touch_mask.tolist()) if flag]
    sweep_indices = [int(i) for i, flag in enumerate(sweep_mask.tolist()) if flag]
    trigger_idx = (
        sweep_indices[-1]
        if sweep_indices
        else interaction_indices[-1]
        if interaction_indices
        else None
    )

    reclaim_idx: int | None = None
    if trigger_idx is not None:
        for i in range(trigger_idx, len(recent)):
            row = recent.iloc[i]
            if direction == "LONG" and float(row["close"]) > float(proximal):
                reclaim_idx = i
                break
            if direction == "SHORT" and float(row["close"]) < float(proximal):
                reclaim_idx = i
                break

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
            "early_confirmed": False,
            "touched": touched,
            "sweep_seen": sweep,
        }

    reclaim = recent.iloc[reclaim_idx]
    local_atr = _f(reclaim.get("atr14")) or atr / (
        12.0 if zone["timeframe"] == "H1" else 48.0
    )
    local_atr = max(float(local_atr), 1e-9)

    def _directional_displacement(row: Any) -> bool:
        rng = max(float(row["high"]) - float(row["low"]), 1e-9)
        body = float(row["close"]) - float(row["open"])
        body_fraction = abs(body) / rng
        direction_ok = body > 0 if direction == "LONG" else body < 0
        return bool(direction_ok and rng >= 0.70 * local_atr and body_fraction >= 0.45)

    reclaim_displacement = _directional_displacement(reclaim)
    post = recent.iloc[reclaim_idx + 1 : min(len(recent), reclaim_idx + 4)]
    post_displacement = any(_directional_displacement(row) for _, row in post.iterrows())
    displacement = bool(reclaim_displacement or post_displacement)

    # Local internal MSS: break the reclaim candle's directional extreme.
    # This is causal and cannot inherit a distant pre-news six-bar extreme.
    mss_level = (
        float(reclaim["high"]) if direction == "LONG" else float(reclaim["low"])
    )
    if direction == "LONG":
        mss = bool((post["close"].astype(float) > mss_level).any()) if not post.empty else False
    else:
        mss = bool((post["close"].astype(float) < mss_level).any()) if not post.empty else False

    reclaimed = True
    rejection = bool(
        (direction == "LONG" and float(reclaim["close"]) >= float(proximal))
        or (direction == "SHORT" and float(reclaim["close"]) <= float(proximal))
    )
    early_confirmed = bool(
        touched
        and reclaimed
        and rejection
        and (sweep or displacement)
    )
    confirmed = bool(early_confirmed and mss and displacement)

    if early_confirmed:
        lo, hi = float(reclaim["low"]), float(reclaim["high"])
        if direction == "LONG":
            entry_low = lo + 0.38 * (hi - lo)
            entry_high = lo + 0.62 * (hi - lo)
            invalidation = min(zone_low, float(recent.iloc[trigger_idx:]["low"].min())) - 0.10 * local_atr
        else:
            entry_low = hi - 0.62 * (hi - lo)
            entry_high = hi - 0.38 * (hi - lo)
            invalidation = max(zone_high, float(recent.iloc[trigger_idx:]["high"].max())) + 0.10 * local_atr
        entry_reference = (entry_low + entry_high) / 2.0
    else:
        entry_low = entry_high = entry_reference = invalidation = None

    stage = (
        "REVERSAL_CONFIRMED"
        if confirmed
        else "EARLY_REVERSAL_CONFIRMED"
        if early_confirmed
        else "RECLAIM_WAIT_LOCAL_MSS"
    )
    return {
        "stage": stage,
        "confirmation_tier": "FULL" if confirmed else "EARLY" if early_confirmed else "WAIT",
        "confirmed": confirmed,
        "early_confirmed": early_confirmed,
        "touched": touched,
        "sweep_seen": sweep,
        "reclaim_at": ensure_utc(
            (reclaim["timestamp"] + known_delta).to_pydatetime()
        ).isoformat(),
        "micro_timeframe": micro_tf,
        "confirmation_close": float(reclaim["close"]),
        "confirmation_low": float(reclaim["low"]),
        "confirmation_high": float(reclaim["high"]),
        "local_atr": local_atr,
        "mss_confirmed": bool(mss),
        "mss_level": mss_level,
        "mss_definition": "LOCAL_RECLAIM_EXTREME_BREAK",
        "displacement_confirmed": displacement,
        "reclaim_displacement": reclaim_displacement,
        "post_reclaim_displacement": post_displacement,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference": entry_reference,
        "invalidation": invalidation,
    }

def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    overlap = max(
        0.0,
        min(float(a["high"]), float(b["high"]))
        - max(float(a["low"]), float(b["low"])),
    )
    minimum = max(
        min(
            float(a["high"]) - float(a["low"]),
            float(b["high"]) - float(b["low"]),
        ),
        1e-9,
    )
    return overlap / minimum


def _classify_hierarchy(
    active_zones: Sequence[dict[str, Any]],
    *,
    price_now: float,
) -> list[dict[str, Any]]:
    """Attach HTF hierarchy without allowing H1 proximity to override H4 context."""
    h4 = [dict(z) for z in active_zones if z.get("timeframe") == "H4"]
    output: list[dict[str, Any]] = []
    for raw in active_zones:
        row = dict(raw)
        if row.get("timeframe") == "H4":
            row["hierarchy_role"] = "MAIN_REVERSAL_ZONE"
            row["parent_zone_id"] = None
            row["parent_overlap_ratio"] = None
            output.append(row)
            continue

        same = [z for z in h4 if z.get("direction") == row.get("direction")]
        opposite = [z for z in h4 if z.get("direction") != row.get("direction")]
        same_ranked = sorted(
            same,
            key=lambda z: (
                _overlap_ratio(row, z),
                -_distance(
                    (float(row["low"]) + float(row["high"])) / 2.0,
                    float(z["low"]),
                    float(z["high"]),
                ),
            ),
            reverse=True,
        )
        parent = same_ranked[0] if same_ranked else None
        overlap = _overlap_ratio(row, parent) if parent else 0.0
        center = (float(row["low"]) + float(row["high"])) / 2.0
        center_inside_parent = bool(
            parent
            and float(parent["low"]) <= center <= float(parent["high"])
        )
        near_parent = False
        if parent:
            gap = _distance(center, float(parent["low"]), float(parent["high"]))
            near_parent = gap <= 0.35 * max(float(parent["atr"]), float(row["atr"]))

        opposing_overlap = max((_overlap_ratio(row, z) for z in opposite), default=0.0)
        if opposing_overlap >= 0.25:
            role = "H1_INTERNAL_OPPOSING_ROADBLOCK"
        elif parent and (overlap >= 0.50 or center_inside_parent):
            role = "H1_REFINEMENT"
        elif parent and (overlap > 0.0 or near_parent):
            role = "H1_SECONDARY_REACTION"
        else:
            role = "H1_STANDALONE_REACTION"

        row["hierarchy_role"] = role
        row["parent_zone_id"] = parent.get("zone_id") if parent else None
        row["parent_overlap_ratio"] = round(overlap, 4) if parent else None
        row["distance_from_price"] = _distance(
            price_now, float(row["low"]), float(row["high"])
        )
        output.append(row)
    return output


def _select_parent_and_refinement(
    active_zones: Sequence[dict[str, Any]],
    *,
    price_now: float,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Choose the next main reversal zone by causal quality, not proximity alone."""
    profiled: list[dict[str, Any]] = []
    for raw in active_zones:
        row = dict(raw)
        profile = _main_reversal_profile(row, price_now=price_now)
        row["main_reversal_eligible"] = bool(profile["eligible"])
        row["main_reversal_score"] = profile["quality_score"]
        row["main_reversal_reasons"] = list(profile["reasons"])
        row["main_reversal_distance_atr"] = profile["distance_atr"]
        profiled.append(row)

    eligible_h4 = [
        z for z in profiled
        if z.get("timeframe") == "H4" and z.get("main_reversal_eligible")
    ]
    eligible_h1 = [
        z for z in profiled
        if z.get("timeframe") == "H1" and z.get("main_reversal_eligible")
    ]
    source = eligible_h4 if eligible_h4 else eligible_h1
    if not source:
        return {}, {}, "NO_MAIN_REVERSAL_ELIGIBLE"

    # The next actionable zone is the nearest high-quality eligible zone.
    # Inside/near zones are prioritized; quality breaks ties so a degraded
    # nearby zone can never override a fresh causal parent.
    candidates = sorted(
        source,
        key=lambda z: (
            float(z.get("main_reversal_distance_atr") or 0.0),
            -float(z.get("main_reversal_score") or 0.0),
            -float(z.get("score") or 0.0),
        ),
    )
    parent = dict(candidates[0])

    refinement: dict[str, Any] = {}
    if parent.get("timeframe") == "H4":
        children = []
        for z in profiled:
            if (
                z.get("timeframe") != "H1"
                or z.get("direction") != parent.get("direction")
                or not z.get("main_reversal_eligible")
            ):
                continue
            overlap = _overlap_ratio(z, parent)
            center = (float(z["low"]) + float(z["high"])) / 2.0
            if overlap >= 0.25 or float(parent["low"]) <= center <= float(parent["high"]):
                children.append(
                    (
                        overlap,
                        float(z.get("main_reversal_score") or 0.0),
                        float(z.get("score") or 0.0),
                        -_distance(price_now, float(z["low"]), float(z["high"])),
                        z,
                    )
                )
        if children:
            children.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
            refinement = dict(children[0][4])

    selection = (
        "H4_PARENT"
        if parent.get("timeframe") == "H4"
        else "H1_FALLBACK_NO_H4"
    )
    return parent, refinement, selection

def _structural_destination(
    *,
    direction: str,
    start_price: float,
    active_zones: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    opposite = "SHORT" if direction == "LONG" else "LONG"
    h4_targets = []
    quality_profile_available = any(
        "main_reversal_eligible" in z for z in active_zones
    )
    for z in active_zones:
        if z.get("timeframe") != "H4" or z.get("direction") != opposite:
            continue
        if quality_profile_available and not bool(z.get("main_reversal_eligible")):
            continue
        edge = float(z["low"]) if direction == "LONG" else float(z["high"])
        if direction == "LONG" and edge <= start_price:
            continue
        if direction == "SHORT" and edge >= start_price:
            continue
        h4_targets.append((abs(edge - start_price), edge, z))
    h4_targets.sort(key=lambda x: x[0])
    if not h4_targets:
        return {}
    distance, edge, zone = h4_targets[0]
    return {
        "zone_id": zone["zone_id"],
        "timeframe": zone["timeframe"],
        "direction": zone["direction"],
        "low": zone["low"],
        "high": zone["high"],
        "price": edge,
        "distance_points": distance,
        "role": "OPPOSING_H4_MAIN_REVERSAL_DESTINATION",
        "main_reversal_score": zone.get("main_reversal_score"),
        "condition": zone.get("condition"),
    }


def _destination_ladder(
    *,
    direction: str,
    start_price: float,
    active_zones: Sequence[dict[str, Any]],
    max_stages: int = 4,
) -> dict[str, Any]:
    """Map staged HTF delivery targets without turning distant targets into active TP.

    Stage 1 is the active opposing main-reversal destination. Every deeper stage
    is conditional on a causal invalidation of the preceding HTF zone. This is
    intentionally different from stacking all zones as simultaneous targets.
    """
    if direction not in {"LONG", "SHORT"}:
        return {
            "state": "NO_DIRECTION",
            "direction": "WAIT",
            "stages": [],
            "primary": {},
            "terminal_scenario": {},
        }

    opposite = "SHORT" if direction == "LONG" else "LONG"
    quality_profile_available = any(
        "main_reversal_eligible" in row for row in active_zones
    )

    def _ahead(zone: dict[str, Any]) -> tuple[bool, float]:
        edge = float(zone["low"]) if direction == "LONG" else float(zone["high"])
        ok = edge > start_price if direction == "LONG" else edge < start_price
        return ok, edge

    h4: list[tuple[float, float, dict[str, Any]]] = []
    h1: list[tuple[float, float, dict[str, Any]]] = []
    for raw in active_zones:
        zone = dict(raw)
        if str(zone.get("direction")) != opposite:
            continue
        if quality_profile_available and not bool(zone.get("main_reversal_eligible")):
            continue
        ahead, edge = _ahead(zone)
        if not ahead:
            continue
        item = (abs(edge - start_price), edge, zone)
        if str(zone.get("timeframe")) == "H4":
            h4.append(item)
        elif str(zone.get("timeframe")) == "H1":
            h1.append(item)

    source = h4 if h4 else h1
    source.sort(key=lambda item: (float(item[0]), -float(item[2].get("main_reversal_score") or item[2].get("score") or 0.0)))
    selected = source[: max(1, int(max_stages))]

    stages: list[dict[str, Any]] = []
    for idx, (distance, edge, zone) in enumerate(selected):
        is_primary = idx == 0
        is_terminal = idx == len(selected) - 1 and idx > 0
        role = (
            "PRIMARY_HTF_DESTINATION"
            if is_primary
            else "TERMINAL_SCENARIO"
            if is_terminal
            else "CONTINUATION_HTF_DESTINATION"
        )
        stages.append(
            {
                "order": idx + 1,
                "role": role,
                "status": (
                    "ACTIVE_AFTER_REVERSAL_CONFIRMATION"
                    if is_primary
                    else "CONDITIONAL_IF_PREVIOUS_HTF_ZONE_FAILS"
                ),
                "activation_rule": (
                    "ACTIVE_AFTER_REVERSAL_CONFIRMATION"
                    if is_primary
                    else "ONLY_AFTER_PREVIOUS_HTF_ZONE_CAUSAL_INVALIDATION"
                ),
                "travel_direction": direction,
                "zone_id": zone.get("zone_id"),
                "timeframe": zone.get("timeframe"),
                "direction": zone.get("direction"),
                "low": zone.get("low"),
                "high": zone.get("high"),
                "price": edge,
                "distance_points": distance,
                "break_level": _zone_break_level(zone),
                "condition": zone.get("condition"),
                "main_reversal_score": zone.get("main_reversal_score"),
                "freshness": dict(zone.get("lifecycle") or {}).get("freshness"),
            }
        )

    return {
        "state": "LADDER_AVAILABLE" if stages else "NO_HTF_DESTINATION",
        "direction": direction,
        "start_price": start_price,
        "source_timeframe": (
            str(stages[0].get("timeframe")) if stages else None
        ),
        "stages": stages,
        "primary": dict(stages[0]) if stages else {},
        "continuation": [dict(row) for row in stages[1:]],
        "terminal_scenario": (
            dict(stages[-1]) if len(stages) > 1 else {}
        ),
        "rule": (
            "PRIMARY destination is active only after reversal confirmation. "
            "Deeper destinations are conditional scenarios and become active only "
            "after the preceding HTF zone is causally invalidated."
        ),
    }


def _roadblocks(
    *,
    direction: str,
    start_price: float,
    active_zones: Sequence[dict[str, Any]],
    destination: dict[str, Any] | None,
    parent_zone_id: str | None = None,
    parent_atr: float | None = None,
    entry: float | None = None,
    invalidation: float | None = None,
) -> list[dict[str, Any]]:
    """Find opposing zones on path and quantify whether they compress usable room."""
    if direction not in {"LONG", "SHORT"}:
        return []
    opposite = "SHORT" if direction == "LONG" else "LONG"
    terminal = _f((destination or {}).get("price"))
    parent_atr_ref = (
        max(float(parent_atr), 1e-9) if parent_atr is not None else None
    )
    risk = None
    if entry is not None and invalidation is not None:
        raw_risk = abs(float(entry) - float(invalidation))
        if raw_risk > 1e-9:
            risk = raw_risk
    rows: list[dict[str, Any]] = []
    for z in active_zones:
        if z.get("zone_id") == parent_zone_id or z.get("direction") != opposite:
            continue
        near_edge = float(z["low"]) if direction == "LONG" else float(z["high"])
        far_edge = float(z["high"]) if direction == "LONG" else float(z["low"])
        ahead = near_edge > start_price if direction == "LONG" else near_edge < start_price
        if not ahead:
            continue
        if terminal is not None:
            before_terminal = near_edge < terminal if direction == "LONG" else near_edge > terminal
            if not before_terminal:
                continue
        distance = abs(near_edge - start_price)
        severity = "MAJOR" if z.get("timeframe") == "H4" else "INTERNAL"
        distance_parent_atr = (
            distance / parent_atr_ref if parent_atr_ref is not None else None
        )
        planned_rr_to_roadblock = (
            abs(near_edge - float(entry)) / risk
            if entry is not None and risk is not None
            else None
        )
        main_reversal_eligible = bool(z.get("main_reversal_eligible"))
        # A degraded/exhausted opposing zone can still react and remains a TP
        # checkpoint, but it must not hard-block a valid parent solely because
        # it is close. Only a genuine main-reversal roadblock uses the 0.50 ATR
        # proximity veto. Every roadblock still respects the >=1.50R rule when
        # entry geometry exists.
        reduces_room = bool(
            (
                main_reversal_eligible
                and distance_parent_atr is not None
                and distance_parent_atr < 0.50
            )
            or (
                planned_rr_to_roadblock is not None
                and planned_rr_to_roadblock < 1.50
            )
        )
        rows.append(
            {
                "zone_id": z["zone_id"],
                "timeframe": z["timeframe"],
                "type": "SUPPLY" if opposite == "SHORT" else "DEMAND",
                "low": z["low"],
                "high": z["high"],
                "near_edge": near_edge,
                "far_edge": far_edge,
                "distance_points": distance,
                "distance_atr": distance / max(float(z.get("atr") or 1.0), 1e-9),
                "distance_parent_atr": distance_parent_atr,
                "planned_rr_to_roadblock": planned_rr_to_roadblock,
                "reduces_room": reduces_room,
                "status": "BLOCKS_ENTRY_ROOM" if reduces_room else "PATH_OBSTACLE",
                "score": z.get("score"),
                "freshness": dict(z.get("lifecycle") or {}).get("freshness"),
                "hierarchy_role": z.get("hierarchy_role"),
                "main_reversal_eligible": main_reversal_eligible,
                "reversal_class": (
                    "MAIN_REVERSAL"
                    if main_reversal_eligible
                    else "REACTION_ONLY"
                ),
                "severity": severity,
            }
        )
    rows.sort(key=lambda r: (float(r["distance_points"]), -float(r.get("score") or 0.0)))
    return rows[:6]


def _sr_roadblocks(
    *,
    direction: str,
    start_price: float,
    support_resistance_map: dict[str, Any],
    destination: dict[str, Any] | None,
    parent_atr: float,
    entry: float | None = None,
    invalidation: float | None = None,
) -> list[dict[str, Any]]:
    """Map validated structural S/R barriers on the already-selected H4 path.

    S/R can cap usable room or veto poor-RR execution, but it can never create
    LONG/SHORT direction or standalone execution authority.
    """
    if direction not in {"LONG", "SHORT"}:
        return []

    terminal = _f((destination or {}).get("price"))
    parent_atr_ref = max(float(parent_atr), 1e-9)
    risk = None
    if entry is not None and invalidation is not None:
        raw_risk = abs(float(entry) - float(invalidation))
        if raw_risk > 1e-9:
            risk = raw_risk

    rows: list[dict[str, Any]] = []
    for raw in list(dict(support_resistance_map or {}).get("levels") or []):
        level = dict(raw or {})
        px = _f(level.get("price"))
        if px is None:
            continue

        state = str(level.get("lifecycle_state") or "").upper()
        role = str(level.get("current_role") or level.get("kind") or "").upper()

        if direction == "LONG":
            acts_as_opposition = role == "RESISTANCE" or state in {
                "FAILED_BULL_BREAKOUT_RECLAIM_REQUIRED",
                "UPSIDE_SWEEP_LIKE_REJECTION",
            }
            if not acts_as_opposition:
                continue
            near_edge = _f(level.get("band_low")) or px
            far_edge = _f(level.get("band_high")) or px
            if near_edge <= start_price:
                continue
            if terminal is not None and near_edge >= terminal:
                continue
            obstacle_type = "RESISTANCE"
        else:
            acts_as_opposition = role == "SUPPORT" or state in {
                "FAILED_BEAR_BREAKDOWN_RECLAIM_REQUIRED",
                "DOWNSIDE_SWEEP_LIKE_REJECTION",
            }
            if not acts_as_opposition:
                continue
            near_edge = _f(level.get("band_high")) or px
            far_edge = _f(level.get("band_low")) or px
            if near_edge >= start_price:
                continue
            if terminal is not None and near_edge <= terminal:
                continue
            obstacle_type = "SUPPORT"

        distance = abs(float(near_edge) - start_price)
        distance_parent_atr = distance / parent_atr_ref
        planned_rr_to_roadblock = (
            abs(float(near_edge) - float(entry)) / risk
            if entry is not None and risk is not None
            else None
        )
        # V366 principle: S/R is weaker than a main-reversal HTF zone.
        # It may cap TP immediately, but it does not veto solely because it is
        # <0.50 parent ATR away. Hard admission veto starts only when actual
        # entry/invalidation geometry shows <1.50R to the S/R barrier.
        reduces_room = bool(
            planned_rr_to_roadblock is not None
            and planned_rr_to_roadblock < 1.50
        )

        rows.append(
            {
                "zone_id": f"SR::{str(level.get('price'))}",
                "timeframe": "H2/SR",
                "type": obstacle_type,
                "low": min(float(near_edge), float(far_edge)),
                "high": max(float(near_edge), float(far_edge)),
                "near_edge": float(near_edge),
                "far_edge": float(far_edge),
                "distance_points": distance,
                "distance_atr": distance_parent_atr,
                "distance_parent_atr": distance_parent_atr,
                "planned_rr_to_roadblock": planned_rr_to_roadblock,
                "reduces_room": reduces_room,
                "status": "BLOCKS_ENTRY_ROOM" if reduces_room else "PATH_OBSTACLE",
                "score": float(level.get("strength") or 0.0),
                "freshness": state,
                "hierarchy_role": "STRUCTURAL_SR_ROADBLOCK",
                "main_reversal_eligible": False,
                "reversal_class": "STRUCTURAL_SR_BARRIER",
                "severity": "STRUCTURAL_SR",
                "source": "RIZAN_STRUCTURAL_SR_MAP_V363",
                "sr_price": px,
                "lifecycle_state": state,
                "current_role": role,
                "sources": list(level.get("sources") or []),
                "direction_signal": False,
            }
        )

    rows.sort(
        key=lambda row: (
            float(row.get("distance_points") or 0.0),
            -float(row.get("score") or 0.0),
        )
    )
    return rows[:6]


def _roadblock_room_gate(
    roadblocks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not roadblocks:
        return {
            "state": "NO_ROADBLOCK_BEFORE_DESTINATION",
            "blocked": False,
            "nearest": {},
        }
    nearest = dict(roadblocks[0])
    blocked = bool(nearest.get("reduces_room"))
    return {
        "state": "ROADBLOCK_ROOM_TOO_SMALL" if blocked else "ROADBLOCK_AHEAD",
        "blocked": blocked,
        "nearest": nearest,
        "threshold_parent_atr": 0.50,
        "threshold_rr": 1.50,
        "rule": (
            "Roadblock is an opposing active HTF zone or validated structural S/R barrier "
            "before the terminal H4 destination. WAIT when the nearest roadblock compresses "
            "usable room or offers <1.50R after entry/invalidation geometry exists."
        ),
    }


def _structural_room_gate(
    *,
    parent_zone: dict[str, Any],
    direction: str,
    path_start: float,
    destination: dict[str, Any] | None,
    entry: float | None,
    invalidation: float | None,
) -> dict[str, Any]:
    parent_atr = max(float(parent_zone.get("atr") or 0.0), 1e-9)
    terminal = _f((destination or {}).get("price"))
    if direction not in {"LONG", "SHORT"} or terminal is None:
        return {
            "state": "NO_TERMINAL_HTF_DESTINATION",
            "blocked": False,
            "distance_points": None,
            "distance_parent_atr": None,
            "planned_rr": None,
            "threshold_parent_atr": 0.50,
            "threshold_rr": 1.50,
        }

    distance = abs(float(terminal) - float(path_start))
    distance_atr = distance / parent_atr
    planned_rr = None
    if entry is not None and invalidation is not None:
        risk = abs(float(entry) - float(invalidation))
        if risk > 1e-9:
            planned_rr = abs(float(terminal) - float(entry)) / risk

    compressed = distance_atr < 0.50
    rr_blocked = planned_rr is not None and planned_rr < 1.50
    blocked = bool(compressed or rr_blocked)
    if compressed:
        state = "COMPRESSED_HTF_CORRIDOR"
    elif rr_blocked:
        state = "STRUCTURAL_RR_TOO_SMALL"
    else:
        state = "STRUCTURAL_ROOM_OK"

    return {
        "state": state,
        "blocked": blocked,
        "distance_points": distance,
        "distance_parent_atr": distance_atr,
        "planned_rr": planned_rr,
        "threshold_parent_atr": 0.50,
        "threshold_rr": 1.50,
        "rule": (
            "WAIT when opposing HTF destination is <0.50 parent ATR away; "
            "after entry geometry exists also require >=1.50R to terminal HTF destination."
        ),
    }


def _zone_break_level(zone: dict[str, Any]) -> float:
    atr = max(float(zone.get("atr") or 0.0), 1e-9)
    if str(zone.get("direction")) == "LONG":
        return float(zone["low"]) - 0.05 * atr
    return float(zone["high"]) + 0.05 * atr


def _structural_path(
    *,
    direction: str,
    start_price: float,
    active_zones: Sequence[dict[str, Any]],
    support_resistance: Sequence[dict[str, Any]],
    liquidity: Sequence[dict[str, Any]],
    parent_atr: float,
) -> dict[str, Any]:
    """Produce one conditional path; S/R is context and can never change the direction."""
    if direction not in {"LONG", "SHORT"}:
        return {
            "state": "NO_DIRECTION",
            "direction": "WAIT",
            "checkpoints": [],
            "support_resistance_context": [],
        }

    opposite = "SHORT" if direction == "LONG" else "LONG"
    zone_candidates: list[dict[str, Any]] = []
    for z in active_zones:
        if str(z.get("direction")) != opposite:
            continue
        near_edge = float(z["low"]) if direction == "LONG" else float(z["high"])
        ahead = near_edge > start_price if direction == "LONG" else near_edge < start_price
        if not ahead:
            continue
        zone_candidates.append(
            {
                "zone": z,
                "near_edge": near_edge,
                "distance": abs(near_edge - start_price),
            }
        )
    zone_candidates.sort(
        key=lambda x: (
            float(x["distance"]),
            0 if str(x["zone"].get("timeframe")) == "H4" else 1,
            -float(x["zone"].get("score") or 0.0),
        )
    )

    # Collapse only genuinely overlapping nested H4/H1 zones to avoid duplicate cards.
    clusters: list[list[dict[str, Any]]] = []
    for candidate in zone_candidates:
        z = candidate["zone"]
        placed = False
        for cluster in clusters:
            low = min(float(x["zone"]["low"]) for x in cluster)
            high = max(float(x["zone"]["high"]) for x in cluster)
            overlap = max(
                0.0,
                min(high, float(z["high"])) - max(low, float(z["low"])),
            )
            smaller = max(
                min(high - low, float(z["high"]) - float(z["low"])),
                1e-9,
            )
            if overlap / smaller >= 0.50:
                cluster.append(candidate)
                placed = True
                break
        if not placed:
            clusters.append([candidate])

    checkpoints: list[dict[str, Any]] = []
    last_zone_boundary: float | None = None
    for index, cluster in enumerate(clusters[:3], start=1):
        zones = [x["zone"] for x in cluster]
        primary = sorted(
            zones,
            key=lambda z: (
                0 if str(z.get("timeframe")) == "H4" else 1,
                -float(z.get("score") or 0.0),
            ),
        )[0]
        low = min(float(z["low"]) for z in zones)
        high = max(float(z["high"]) for z in zones)
        near_edge = low if direction == "LONG" else high
        condition = str(primary.get("condition") or _zone_condition(primary))
        checkpoints.append(
            {
                "order": index,
                "type": "ZONE",
                "role": "PRIMARY_REACTION" if index == 1 else "IF_BREAK_NEXT_REACTION",
                "zone_type": "SUPPLY" if opposite == "SHORT" else "DEMAND",
                "timeframes": sorted({str(z.get("timeframe")) for z in zones}, reverse=True),
                "low": low,
                "high": high,
                "near_edge": near_edge,
                "distance_points": abs(near_edge - start_price),
                "condition": condition,
                "score": primary.get("score"),
                "zone_id": primary.get("zone_id"),
                "break_level": _zone_break_level(primary),
                "continuation_rule": (
                    "CONTINUE_ONLY_AFTER_CAUSAL_CLOSE_THROUGH_ZONE"
                    if index > 1 or condition in {"DEGRADED", "NEAR_EXHAUSTED"}
                    else "EXPECT_REACTION_CONFIRM_REVERSAL_OR_BREAK"
                ),
                "nested_zone_ids": [z.get("zone_id") for z in zones if z.get("zone_id") != primary.get("zone_id")],
            }
        )
        last_zone_boundary = low if direction == "SHORT" else high

    # One S/R checkpoint beyond the last mapped zone keeps the main display simple.
    sr_candidates: list[dict[str, Any]] = []
    for level in support_resistance:
        px = float(level["price"])
        if direction == "SHORT":
            threshold = last_zone_boundary if last_zone_boundary is not None else start_price
            if px >= threshold:
                continue
            compatible = str(level.get("kind")) in {"SUPPORT", "FLIP"}
        else:
            threshold = last_zone_boundary if last_zone_boundary is not None else start_price
            if px <= threshold:
                continue
            compatible = str(level.get("kind")) in {"RESISTANCE", "FLIP"}
        if not compatible:
            continue
        if abs(px - start_price) > 4.0 * max(parent_atr, 1e-9):
            continue
        sr_candidates.append(level)

    if sr_candidates:
        sr_candidates.sort(
            key=lambda x: (
                abs(float(x["price"]) - (last_zone_boundary if last_zone_boundary is not None else start_price)),
                -float(x.get("strength") or 0.0),
            )
        )
        sr = dict(sr_candidates[0])
        px = float(sr["price"])
        nearby_liquidity = [
            x for x in liquidity
            if abs(float(x.get("price") or 0.0) - px) <= max(0.15 * parent_atr, 1.0)
        ]
        checkpoints.append(
            {
                "order": len(checkpoints) + 1,
                "type": "SUPPORT_RESISTANCE",
                "role": "IF_ZONE_BREAKS_LIQUIDITY_SR_WATCH",
                "zone_type": sr.get("kind"),
                "price": px,
                "strength": sr.get("strength"),
                "sources": sr.get("sources"),
                "distance_points": abs(px - start_price),
                "liquidity_sources": sorted(
                    {
                        source
                        for item in nearby_liquidity[:6]
                        for source in list(item.get("sources") or [])
                    }
                ),
                "continuation_rule": "CONTEXT_ONLY_WAIT_FOR_SWEEP_RECLAIM_OR_CLEAN_BREAK",
            }
        )

    return {
        "state": "PATH_AVAILABLE" if checkpoints else "NO_PATH_CHECKPOINT",
        "direction": direction,
        "start_price": start_price,
        "checkpoints": checkpoints,
        "primary_checkpoint": dict(checkpoints[0]) if checkpoints else {},
        "terminal_checkpoint": dict(checkpoints[-1]) if checkpoints else {},
        "support_resistance_context": list(support_resistance[:8]),
        "rule": (
            "ONE_DIRECTION_ONLY: parent H4 defines direction; checkpoints are conditional. "
            "S/R never generates LONG/SHORT. At every opposing zone, reversal confirmation stops continuation; "
            "continuation requires a causal close through the zone."
        ),
    }


def _conditional_failure_path(
    *,
    parent_zone: dict[str, Any],
    direction: str,
    active_zones: Sequence[dict[str, Any]],
    support_resistance: Sequence[dict[str, Any]],
    liquidity: Sequence[dict[str, Any]],
    parent_atr: float,
) -> dict[str, Any]:
    """Map what lies beyond parent invalidation; this is not a second direction signal."""
    if direction not in {"LONG", "SHORT"} or not parent_zone:
        return {"state": "NO_PARENT", "checkpoints": []}

    trigger = _zone_break_level(parent_zone)
    failure_direction = "SHORT" if direction == "LONG" else "LONG"
    base = _structural_path(
        direction=failure_direction,
        start_price=trigger,
        active_zones=active_zones,
        support_resistance=[],
        liquidity=liquidity,
        parent_atr=parent_atr,
    )
    zone_steps = [
        dict(cp)
        for cp in list(base.get("checkpoints") or [])
        if cp.get("type") == "ZONE"
    ][:2]

    checkpoints: list[dict[str, Any]] = []
    if zone_steps:
        first = dict(zone_steps[0])
        first["order"] = 1
        first["role"] = "AFTER_PARENT_FAILURE_FIRST_REACTION"
        checkpoints.append(first)

        first_boundary = (
            float(first["low"])
            if failure_direction == "SHORT"
            else float(first["high"])
        )
        second_boundary = None
        if len(zone_steps) > 1:
            second_boundary = (
                float(zone_steps[1]["high"])
                if failure_direction == "SHORT"
                else float(zone_steps[1]["low"])
            )

        compatible: list[dict[str, Any]] = []
        for level in support_resistance:
            px = float(level["price"])
            kind = str(level.get("kind") or "")
            if failure_direction == "SHORT":
                if px >= first_boundary:
                    continue
                if second_boundary is not None and px <= second_boundary:
                    continue
                if kind not in {"SUPPORT", "FLIP"}:
                    continue
            else:
                if px <= first_boundary:
                    continue
                if second_boundary is not None and px >= second_boundary:
                    continue
                if kind not in {"RESISTANCE", "FLIP"}:
                    continue
            if abs(px - first_boundary) > 1.25 * max(parent_atr, 1e-9):
                continue
            compatible.append(level)

        if compatible:
            compatible.sort(
                key=lambda x: (
                    -float(x.get("strength") or 0.0),
                    abs(float(x["price"]) - first_boundary),
                )
            )
            anchor_level = compatible[0]
            anchor_px = float(anchor_level["price"])
            cluster = [
                x
                for x in compatible
                if abs(float(x["price"]) - anchor_px)
                <= max(0.25 * parent_atr, 1.0)
            ]
            low = min(float(x["price"]) for x in cluster)
            high = max(float(x["price"]) for x in cluster)
            checkpoints.append(
                {
                    "order": 2,
                    "type": "SUPPORT_RESISTANCE",
                    "role": "AFTER_ZONE_BREAK_H2_SR_CLUSTER",
                    "zone_type": "SUPPORT_CLUSTER" if failure_direction == "SHORT" else "RESISTANCE_CLUSTER",
                    "low": low,
                    "high": high,
                    "price": anchor_px,
                    "strength": max(float(x.get("strength") or 0.0) for x in cluster),
                    "sources": sorted(
                        {
                            source
                            for x in cluster
                            for source in list(x.get("sources") or [])
                        }
                    ),
                    "continuation_rule": "CONTEXT_ONLY_WAIT_FOR_SWEEP_RECLAIM_OR_CLEAN_BREAK",
                }
            )

        if len(zone_steps) > 1:
            second = dict(zone_steps[1])
            second["order"] = len(checkpoints) + 1
            second["role"] = "AFTER_SR_NEXT_REACTION"
            checkpoints.append(second)

    return {
        "state": "CONDITIONAL_ONLY" if checkpoints else "NO_FAILURE_CHECKPOINT",
        "trigger": trigger,
        "trigger_rule": (
            "PARENT_INVALIDATED_BY_CAUSAL_CLOSE_BEYOND_DISTAL_PLUS_0P05_ATR"
        ),
        "parent_direction": direction,
        "failure_direction": failure_direction,
        "checkpoints": checkpoints,
        "rule": (
            "NOT_A_SECOND_SIGNAL. This path is visible only as contingency: "
            "use it only after the parent zone is causally invalidated."
        ),
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
        row["condition"] = _zone_condition(row)
        row["distance_points"] = _distance(current, zone.low, zone.high)
        row["distance_atr"] = row["distance_points"] / max(zone.atr, 1e-9)
        row["score"] = round(
            float(zone.score_seed) - touch_penalty - 10.0 * min(1.0, mitigation),
            2,
        )
        payloads.append(row)

    active = _classify_hierarchy(_dedupe(payloads), price_now=current)
    for row in active:
        intraday = _intraday_breach_status(
            row,
            bars_m15=bars_m15,
            as_of=now,
        )
        row["intraday_breach"] = intraday
        row["intraday_quarantined"] = bool(intraday.get("quarantined"))
        profile = _main_reversal_profile(row, price_now=current)
        row["main_reversal_eligible"] = bool(profile["eligible"])
        row["main_reversal_score"] = profile["quality_score"]
        row["main_reversal_reasons"] = list(profile["reasons"])
        row["main_reversal_distance_atr"] = profile["distance_atr"]

    quarantined_zones = sorted(
        [dict(row) for row in active if row.get("intraday_quarantined")],
        key=lambda row: (
            float(row.get("distance_points") or 0.0),
            -float(row.get("score") or 0.0),
        ),
    )

    demands = [x for x in active if x["direction"] == "LONG"]
    supplies = [x for x in active if x["direction"] == "SHORT"]
    demands.sort(key=lambda x: (float(x["distance_points"]), -float(x["score"])))
    supplies.sort(key=lambda x: (float(x["distance_points"]), -float(x["score"])))
    main_demands = [x for x in demands if x.get("main_reversal_eligible")]
    main_supplies = [x for x in supplies if x.get("main_reversal_eligible")]
    usable_demands = [x for x in demands if not x.get("intraday_quarantined")]
    usable_supplies = [x for x in supplies if not x.get("intraday_quarantined")]
    nearest_demand = (
        dict((main_demands or usable_demands or demands)[0]) if demands else {}
    )
    nearest_supply = (
        dict((main_supplies or usable_supplies or supplies)[0]) if supplies else {}
    )

    decision_zone, refinement_zone, hierarchy_selection = _select_parent_and_refinement(
        active,
        price_now=current,
    )
    confirmation_zone = dict(refinement_zone or decision_zone)

    h1_atr_series = _atr(h1_frame)
    atr_ref = _f(h1_atr_series.iloc[-1]) or max(current * 0.002, 1.0)
    support_resistance = _h2_support_resistance(
        bars_h1,
        as_of=now,
        price_now=current,
        atr_reference=float(atr_ref),
    )
    support_resistance_map = build_structural_sr_map(
        levels=support_resistance,
        bars_m15=bars_m15,
        bars_m5=bars_m5,
        as_of=now,
        price_now=current,
        atr_reference=float(atr_ref),
    )
    raw_levels = [
        *_pivot_levels(bars_h4, timeframe="H4", as_of=now),
        *_pivot_levels(bars_h1, timeframe="H1", as_of=now),
    ]
    liquidity = _cluster_liquidity(
        raw_levels,
        price_now=current,
        atr_reference=float(atr_ref),
    )

    sweep_map = (
        _sweep_map(decision_zone, zones=active, liquidity=liquidity)
        if decision_zone
        else {}
    )
    prepared_entry = _prepared_entry_band(confirmation_zone or decision_zone)
    micro = (
        _micro_confirmation(
            confirmation_zone,
            bars_m5=bars_m5,
            bars_m15=bars_m15,
            price_now=current,
            as_of=now,
        )
        if confirmation_zone
        else {"stage": "NO_DECISION_ZONE", "confirmed": False}
    )
    direction = str(decision_zone.get("direction") or "WAIT")
    entry = _f(micro.get("entry_reference"))
    path_start = entry if entry is not None else current
    destination = (
        _structural_destination(
            direction=direction,
            start_price=path_start,
            active_zones=active,
        )
        if direction in {"LONG", "SHORT"}
        else {}
    )
    destination_ladder = (
        _destination_ladder(
            direction=direction,
            start_price=path_start,
            active_zones=active,
        )
        if direction in {"LONG", "SHORT"}
        else {
            "state": "NO_DIRECTION",
            "direction": "WAIT",
            "stages": [],
            "primary": {},
            "terminal_scenario": {},
        }
    )
    invalidation = _f(micro.get("invalidation"))
    htf_roadblocks = (
        _roadblocks(
            direction=direction,
            start_price=path_start,
            active_zones=active,
            destination=destination,
            parent_zone_id=str(decision_zone.get("zone_id") or "") or None,
            parent_atr=float(decision_zone.get("atr") or atr_ref),
            entry=entry,
            invalidation=invalidation,
        )
        if direction in {"LONG", "SHORT"}
        else []
    )
    sr_roadblocks = (
        _sr_roadblocks(
            direction=direction,
            start_price=path_start,
            support_resistance_map=support_resistance_map,
            destination=destination,
            parent_atr=float(decision_zone.get("atr") or atr_ref),
            entry=entry,
            invalidation=invalidation,
        )
        if direction in {"LONG", "SHORT"}
        else []
    )
    roadblocks = sorted(
        [*htf_roadblocks, *sr_roadblocks],
        key=lambda row: (
            float(row.get("distance_points") or 0.0),
            -float(row.get("score") or 0.0),
        ),
    )[:8]
    nearest_roadblock = dict(roadblocks[0]) if roadblocks else {}
    roadblock_room = _roadblock_room_gate(roadblocks)
    structural_room = _structural_room_gate(
        parent_zone=decision_zone,
        direction=direction,
        path_start=path_start,
        destination=destination,
        entry=entry,
        invalidation=invalidation,
    ) if decision_zone else {
        "state": "NO_DECISION_ZONE",
        "blocked": False,
    }
    structural_path = _structural_path(
        direction=direction,
        start_price=path_start,
        active_zones=active,
        support_resistance=support_resistance,
        liquidity=liquidity,
        parent_atr=float(decision_zone.get("atr") or atr_ref),
    ) if decision_zone else {
        "state": "NO_DECISION_ZONE",
        "direction": "WAIT",
        "checkpoints": [],
        "support_resistance_context": support_resistance,
    }
    failure_path = _conditional_failure_path(
        parent_zone=decision_zone,
        direction=direction,
        active_zones=active,
        support_resistance=support_resistance,
        liquidity=liquidity,
        parent_atr=float(decision_zone.get("atr") or atr_ref),
    ) if decision_zone else {
        "state": "NO_DECISION_ZONE",
        "checkpoints": [],
    }
    failure_direction = str(failure_path.get("failure_direction") or "WAIT")
    failure_start = _f(failure_path.get("trigger"))
    failure_destination_ladder = (
        _destination_ladder(
            direction=failure_direction,
            start_price=float(failure_start),
            active_zones=active,
        )
        if failure_direction in {"LONG", "SHORT"} and failure_start is not None
        else {
            "state": "NO_FAILURE_PATH",
            "direction": "WAIT",
            "stages": [],
            "primary": {},
            "terminal_scenario": {},
        }
    )
    next_after_failure = dict(failure_destination_ladder.get("primary") or {})
    zone_chain = {
        "state": "ACTIVE_PRIMARY" if decision_zone else "NO_ACTIVE_PRIMARY",
        "active_zone_id": decision_zone.get("zone_id"),
        "active_timeframe": decision_zone.get("timeframe"),
        "active_direction": direction,
        "promotion_trigger": failure_path.get("trigger"),
        "promotion_rule": (
            "ON_CAUSAL_INVALIDATION_REBUILD_AND_PROMOTE_NEXT_ELIGIBLE_MAIN_REVERSAL_ZONE"
        ),
        "next_after_failure": next_after_failure,
        "terminal_after_failure": dict(
            failure_destination_ladder.get("terminal_scenario") or {}
        ),
    }
    targets = _targets(
        direction=direction,
        entry=entry,
        active_zones=active,
        fallback_atr=float(decision_zone.get("atr") or atr_ref),
    ) if direction in {"LONG", "SHORT"} else []
    if entry is not None and nearest_roadblock:
        roadblock_target = _f(nearest_roadblock.get("near_edge"))
        if roadblock_target is not None:
            target_row = {
                "price": roadblock_target,
                "source": (
                    "STRUCTURAL_SR_ROADBLOCK"
                    if str(nearest_roadblock.get("source") or "")
                    == "RIZAN_STRUCTURAL_SR_MAP_V363"
                    else "HTF_ROADBLOCK"
                ),
                "zone_id": nearest_roadblock.get("zone_id"),
                "distance": abs(roadblock_target - entry),
            }
            targets = [
                target_row,
                *[
                    row
                    for row in targets
                    if abs(float(row.get("price") or 0.0) - roadblock_target) > 1e-9
                ],
            ][:3]
    guide_state = (
        "WAIT_ROADBLOCK"
        if bool(roadblock_room.get("blocked"))
        else "WAIT_STRUCTURAL_ROOM"
        if bool(structural_room.get("blocked"))
        else "WAIT_NO_TERMINAL_HTF_DESTINATION"
        if not destination
        else "CONFIRMED_GUIDANCE"
        if bool(micro.get("confirmed"))
        else "EARLY_CONFIRMED_GUIDANCE"
        if bool(micro.get("early_confirmed"))
        else "WAIT_CONFIRMATION"
    )

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
        "main_reversal_candidates": [
            dict(row)
            for row in sorted(
                [x for x in active if x.get("main_reversal_eligible")],
                key=lambda x: (
                    float(x.get("main_reversal_distance_atr") or 0.0),
                    -float(x.get("main_reversal_score") or 0.0),
                ),
            )[:6]
        ],
        "reaction_zones": [
            dict(row)
            for row in active
            if not row.get("main_reversal_eligible")
        ],
        "intraday_quarantined_zones": quarantined_zones[:6],
        "decision_zone": decision_zone,
        "main_reversal_zone": decision_zone,
        "refinement_zone": refinement_zone,
        "confirmation_zone": confirmation_zone,
        "hierarchy_selection": hierarchy_selection,
        "expected_reversal_direction": direction,
        "structural_destination": destination,
        "destination_ladder": destination_ladder,
        "failure_destination_ladder": failure_destination_ladder,
        "zone_chain": zone_chain,
        "structural_room": structural_room,
        "structural_path": structural_path,
        "failure_path": failure_path,
        "support_resistance": support_resistance,
        "support_resistance_map": support_resistance_map,
        "roadblocks": roadblocks,
        "htf_roadblocks": htf_roadblocks,
        "sr_roadblocks": sr_roadblocks,
        "nearest_roadblock": nearest_roadblock,
        "roadblock_room": roadblock_room,
        "liquidity_map": sweep_map,
        "micro_confirmation": micro,
        "entry_guide": {
            "state": guide_state,
            "direction": direction,
            "prepared_entry_low": prepared_entry.get("entry_low"),
            "prepared_entry_high": prepared_entry.get("entry_high"),
            "prepared_entry_reference": prepared_entry.get("entry_reference"),
            "prepared_entry_source": prepared_entry.get("source"),
            "entry_low": micro.get("entry_low"),
            "entry_high": micro.get("entry_high"),
            "entry_reference": entry,
            "confirmation_entry_reference": micro.get("confirmation_close"),
            "confirmation_at": micro.get("reclaim_at"),
            "invalidation": invalidation,
            "targets": targets,
            "execution_modes": [
                "EARLY_CONFIRMATION_DEMO_PROBE",
                "FRESH_CONFIRMATION_ENTRY",
                "RETEST_ENTRY",
            ],
            "rule": (
                "HTF_PREPARE -> LIQUIDITY_SWEEP_OPTIONAL -> RECLAIM -> MSS -> "
                "DISPLACEMENT -> HTF_AND_SR_ROADBLOCK_ROOM -> "
                "FRESH_CONFIRMATION_OR_RETEST"
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
            "hierarchy": (
                "H4 defines MAIN_REVERSAL_ZONE; same-direction H1 may refine it. "
                "Opposing zones on the projected path are ROADBLOCKS and do not override H4 solely by proximity."
            ),
            "roadblock": (
                "OPPOSING_ACTIVE_HTF_ZONE_OR_VALIDATED_STRUCTURAL_SR_BARRIER_BETWEEN_PATH_START_"
                "AND_OPPOSING_H4_DESTINATION; S/R MAY_CAP_TARGET_BUT_NEVER_CREATE_DIRECTION; "
                "S/R_HARD_VETO_ONLY_IF_ENTRY_GEOMETRY_GIVES_LT_1P50R; "
                "HTF_MAIN_REVERSAL_KEEPS_0P50_PARENT_ATR_PROXIMITY_RULE"
            ),
            "structural_room_gate": (
                "WAIT_IF_TERMINAL_OPPOSING_HTF_DESTINATION_LT_0P50_PARENT_ATR; "
                "WHEN_ENTRY_GEOMETRY_EXISTS_REQUIRE_TERMINAL_RR_GTE_1P50"
            ),
            "structural_path": (
                "ONE_PARENT_DIRECTION -> OPPOSING_ZONE_CHECKPOINTS -> CONDITIONAL_BREAK -> "
                "OPTIONAL_H2_SUPPORT_RESISTANCE_LIQUIDITY_CONTEXT"
            ),
            "support_resistance": (
                "CAUSAL_H2_SWING_PIVOTS_PLUS_PRIOR_DAY_WEEK_LEVELS; V363 adds completed-bar "
                "BREAKOUT -> ACCEPTANCE -> RETEST -> HOLD role-flip lifecycle. "
                "CONTEXT_ONLY_NO_DIRECTION_SIGNAL"
            ),
            "failure_path": (
                "CONDITIONAL_ONLY_AFTER_PARENT_CAUSAL_INVALIDATION; NEVER_A_SECOND_DIRECTION_SIGNAL"
            ),
            "destination_ladder": (
                "PRIMARY_ACTIVE_AFTER_REVERSAL_CONFIRMATION -> "
                "CONTINUATION_ONLY_IF_PREVIOUS_HTF_ZONE_FAILS -> "
                "TERMINAL_SCENARIO_NOT_DIRECT_TP"
            ),
            "zone_promotion": (
                "WHEN_ACTIVE_MAIN_ZONE_IS_CAUSALLY_INVALIDATED, REBUILD_FROM_COMPLETED_BARS "
                "AND_PROMOTE_NEXT_ELIGIBLE_MAIN_REVERSAL_ZONE"
            ),
            "reversal_confirmation": "TOUCH/SWEEP + RECLAIM + LOCAL_MSS + DISPLACEMENT",
            "intraday_parent_reroute": (
                "V369: completed M15 deep breach >=0.25 parent ATR or two consecutive closes "
                "beyond distal+0.05 ATR temporarily quarantines the HTF parent and reroutes "
                "PREPARE to the next eligible main-reversal zone; M15 reclaim releases quarantine."
            ),
            "rebuild_policy": "RECALCULATE_FROM_COMPLETED_H4_H1_M15_M5_ON_EACH_RUNTIME_CYCLE",
        },
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_scope": EXECUTION_SCOPE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }
