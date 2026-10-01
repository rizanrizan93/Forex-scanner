from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .xau_sd_liquidity_engine_v342 import (
    SDZone,
    TF_MINUTES,
    TF_PARAMS,
    detect_zones,
)

RESEARCH_VERSION = "XAU_RIZAN_SD_LIQUIDITY_HISTORICAL_V345_1"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
TARGET_ATR = 0.50
BREAK_BUFFER_ATR = 0.05
REACTION_HORIZON_HOURS = {"H1": 12.0, "H4": 32.0}
SUPERSESSION_GAP_HOURS = {"H1": 2.1, "H4": 8.1}


def load_price_frame(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V345_MISSING_PRICE_COLUMNS:{sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required))
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise RuntimeError("V345_PRICE_FRAME_EMPTY")
    return frame.reset_index(drop=True)


def resample_ohlc(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    work = frame.set_index("timestamp")
    out = work.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    return out.reset_index()


def bars_from_frame(frame: pd.DataFrame, timeframe: str) -> tuple[Bar, ...]:
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


def build_htf_zones(price_m1: pd.DataFrame) -> tuple[SDZone, ...]:
    if price_m1.empty:
        return ()
    as_of = ensure_utc(pd.Timestamp(price_m1.iloc[-1]["timestamp"]).to_pydatetime()) + timedelta(minutes=1)
    output: list[SDZone] = []
    for timeframe, rule in (("H1", "1h"), ("H4", "4h")):
        tf_frame = resample_ohlc(price_m1, rule)
        bars = bars_from_frame(tf_frame, timeframe)
        output.extend(detect_zones(bars, timeframe=timeframe, as_of=as_of))
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
    result = {zone.zone_id: None for zone in zones}
    recent: dict[tuple[str, str], list[SDZone]] = {}
    for zone in zones:
        key = (zone.timeframe, zone.direction)
        now = ensure_utc(zone.available_at)
        limit = SUPERSESSION_GAP_HOURS[zone.timeframe]
        bucket = recent.setdefault(key, [])
        bucket[:] = [
            old
            for old in bucket
            if (now - ensure_utc(old.available_at)).total_seconds() / 3600.0 <= limit
        ]
        for old in bucket:
            if result[old.zone_id] is None and _overlap_ratio(old, zone) >= 0.75:
                result[old.zone_id] = now
        bucket.append(zone)
    return result


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = p + z * z / (2.0 * total)
    margin = z * sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (center - margin) / denominator)


def _q(values: Sequence[float], q: float) -> float | None:
    clean = [float(v) for v in values if isfinite(float(v))]
    return None if not clean else float(np.quantile(np.asarray(clean, dtype=float), q))


def _price_arrays(price_m1: pd.DataFrame) -> dict[str, Any]:
    return {
        "timestamps": list(price_m1["timestamp"]),
        "high": price_m1["high"].to_numpy(dtype=float, copy=False),
        "low": price_m1["low"].to_numpy(dtype=float, copy=False),
        "close": price_m1["close"].to_numpy(dtype=float, copy=False),
    }


def evaluate_first_touch(
    price_m1: pd.DataFrame,
    *,
    zone: SDZone,
    arrays: dict[str, Any] | None = None,
    valid_until: datetime | None = None,
) -> dict[str, Any] | None:
    px = arrays or _price_arrays(price_m1)
    timestamps = px["timestamps"]
    if not timestamps:
        return None
    available = ensure_utc(zone.available_at)
    start = bisect_left(timestamps, pd.Timestamp(available))
    if start >= len(timestamps):
        return None

    expiry = available + timedelta(hours=float(TF_PARAMS[zone.timeframe]["lifecycle_hours"]))
    if valid_until is not None:
        expiry = min(expiry, ensure_utc(valid_until))
    end = bisect_left(timestamps, pd.Timestamp(expiry))
    end = min(end, len(timestamps))
    if end <= start:
        return None

    highs = px["high"][start:end]
    lows = px["low"][start:end]
    closes = px["close"][start:end]
    touch_mask = (lows <= float(zone.high)) & (highs >= float(zone.low))
    if zone.direction == "LONG":
        pre_invalid = closes < float(zone.distal) - BREAK_BUFFER_ATR * float(zone.atr)
    else:
        pre_invalid = closes > float(zone.distal) + BREAK_BUFFER_ATR * float(zone.atr)

    first_events = np.flatnonzero(touch_mask | pre_invalid)
    if len(first_events) == 0:
        return None
    rel = int(first_events[0])
    touched = bool(touch_mask[rel])
    invalid_same = bool(pre_invalid[rel])
    if not touched:
        return None

    touch_index = start + rel
    touch_open_at = ensure_utc(timestamps[touch_index].to_pydatetime())
    touch_at = touch_open_at + timedelta(minutes=1)
    width = max(float(zone.high) - float(zone.low), 1e-12)
    target = (
        float(zone.proximal) + TARGET_ATR * float(zone.atr)
        if zone.direction == "LONG"
        else float(zone.proximal) - TARGET_ATR * float(zone.atr)
    )

    if invalid_same:
        adverse = float(px["low"][touch_index]) if zone.direction == "LONG" else float(px["high"][touch_index])
        sweep_extension = (
            max(0.0, float(zone.distal) - adverse)
            if zone.direction == "LONG"
            else max(0.0, adverse - float(zone.distal))
        )
        return {
            **_zone_record(zone),
            "touch_at": touch_at.isoformat(),
            "outcome_at": touch_at.isoformat(),
            "outcome": "BREAK_TOUCH",
            "reaction_hit": False,
            "break_hit": True,
            "reversal_direction": zone.direction,
            "target_price": target,
            "adverse_extreme": adverse,
            "turning_depth": (
                (float(zone.high) - adverse) / width
                if zone.direction == "LONG"
                else (adverse - float(zone.low)) / width
            ),
            "sweep_extension_points": sweep_extension,
            "sweep_extension_atr": sweep_extension / max(float(zone.atr), 1e-12),
            "sweep_extension_zone_width": sweep_extension / width,
            "reversal_after_sweep": False,
            "same_m1_ambiguity": True,
            "minutes_to_outcome": 0.0,
        }

    horizon = touch_at + timedelta(hours=REACTION_HORIZON_HOURS[zone.timeframe])
    future_end = bisect_right(timestamps, pd.Timestamp(horizon))
    future_end = min(future_end, len(timestamps))
    if future_end <= touch_index:
        return None
    # Require full forward horizon when no target/break resolves earlier.
    horizon_fully_observed = ensure_utc(timestamps[-1].to_pydatetime()) + timedelta(minutes=1) >= horizon

    segment_high = px["high"][touch_index:future_end]
    segment_low = px["low"][touch_index:future_end]
    segment_close = px["close"][touch_index:future_end]
    if zone.direction == "LONG":
        target_mask = segment_high >= target
        invalid_mask = segment_close < float(zone.distal) - BREAK_BUFFER_ATR * float(zone.atr)
    else:
        target_mask = segment_low <= target
        invalid_mask = segment_close > float(zone.distal) + BREAK_BUFFER_ATR * float(zone.atr)

    event_positions = np.flatnonzero(target_mask | invalid_mask)
    if len(event_positions):
        event_rel = int(event_positions[0])
        absolute = touch_index + event_rel
        break_hit = bool(invalid_mask[event_rel])
        target_hit = bool(target_mask[event_rel]) and not break_hit
        outcome = "BREAK" if break_hit else "HOLD_050"
        outcome_at = ensure_utc(timestamps[absolute].to_pydatetime()) + timedelta(minutes=1)
        # For a successful target bar, exclude that bar from sweep classification:
        # intrabar target-vs-sweep ordering is unknowable from OHLC.
        adverse_end = absolute + 1 if break_hit else max(touch_index + 1, absolute)
        same_bar_ambiguity = bool(target_mask[event_rel] and invalid_mask[event_rel])
    else:
        if not horizon_fully_observed:
            return None
        absolute = future_end - 1
        break_hit = False
        target_hit = False
        outcome = "STALL"
        outcome_at = horizon
        adverse_end = future_end
        same_bar_ambiguity = False

    if zone.direction == "LONG":
        adverse = float(np.min(px["low"][touch_index:adverse_end]))
        turning_depth = (float(zone.high) - adverse) / width
        sweep_extension = max(0.0, float(zone.distal) - adverse)
    else:
        adverse = float(np.max(px["high"][touch_index:adverse_end]))
        turning_depth = (adverse - float(zone.low)) / width
        sweep_extension = max(0.0, adverse - float(zone.distal))

    after_sweep = bool(target_hit and sweep_extension > 1e-12)
    if target_hit:
        outcome = "HOLD_050_AFTER_SWEEP" if after_sweep else "HOLD_050_DIRECT"

    return {
        **_zone_record(zone),
        "touch_at": touch_at.isoformat(),
        "outcome_at": outcome_at.isoformat(),
        "outcome": outcome,
        "reaction_hit": target_hit,
        "break_hit": break_hit,
        "reversal_direction": zone.direction,
        "target_price": target,
        "adverse_extreme": adverse,
        "turning_depth": turning_depth,
        "sweep_extension_points": sweep_extension,
        "sweep_extension_atr": sweep_extension / max(float(zone.atr), 1e-12),
        "sweep_extension_zone_width": sweep_extension / width,
        "reversal_after_sweep": after_sweep,
        "same_m1_ambiguity": same_bar_ambiguity,
        "minutes_to_outcome": max(0.0, (outcome_at - touch_at).total_seconds() / 60.0),
    }


def _zone_record(zone: SDZone) -> dict[str, Any]:
    row = asdict(zone)
    row["origin_at"] = ensure_utc(zone.origin_at).isoformat()
    row["available_at"] = ensure_utc(zone.available_at).isoformat()
    return row


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    reactions = [r for r in rows if bool(r.get("reaction_hit"))]
    sweep_reactions = [r for r in reactions if bool(r.get("reversal_after_sweep"))]
    direct = [r for r in reactions if not bool(r.get("reversal_after_sweep"))]
    breaks = [r for r in rows if bool(r.get("break_hit"))]
    stalls = [r for r in rows if str(r.get("outcome") or "") == "STALL"]
    sweep_atr = [float(r["sweep_extension_atr"]) for r in sweep_reactions]
    depths = [float(r["turning_depth"]) for r in reactions]
    return {
        "touches": total,
        "reactions_050_atr": len(reactions),
        "reaction_rate": None if total == 0 else len(reactions) / total,
        "reaction_wilson_lower_95": _wilson_lower(len(reactions), total),
        "direct_reversals": len(direct),
        "sweep_reversals": len(sweep_reactions),
        "sweep_share_of_reversals": None if not reactions else len(sweep_reactions) / len(reactions),
        "breaks": len(breaks),
        "stalls": len(stalls),
        "turning_depth_p50": _q(depths, 0.50),
        "turning_depth_p75": _q(depths, 0.75),
        "sweep_extension_atr_p50": _q(sweep_atr, 0.50),
        "sweep_extension_atr_p75": _q(sweep_atr, 0.75),
        "sweep_extension_atr_p90": _q(sweep_atr, 0.90),
        "sweep_extension_atr_p95": _q(sweep_atr, 0.95),
    }


def grouped_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {"ALL": _summary(rows)}
    for tf in ("H4", "H1"):
        tf_rows = [r for r in rows if r.get("timeframe") == tf]
        output[tf] = {
            "ALL": _summary(tf_rows),
            "LONG": _summary([r for r in tf_rows if r.get("direction") == "LONG"]),
            "SHORT": _summary([r for r in tf_rows if r.get("direction") == "SHORT"]),
        }
    return output


def factor_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def group(field: str) -> dict[str, Any]:
        keys = sorted({str(r.get(field)) for r in rows})
        return {key: _summary([r for r in rows if str(r.get(field)) == key]) for key in keys}

    departure_buckets: dict[str, list[dict[str, Any]]] = {
        "<1.0ATR": [],
        "1.0-1.5ATR": [],
        "1.5-2.0ATR": [],
        ">=2.0ATR": [],
    }
    for row in rows:
        value = float(row.get("departure_range_atr") or 0.0)
        if value < 1.0:
            departure_buckets["<1.0ATR"].append(row)
        elif value < 1.5:
            departure_buckets["1.0-1.5ATR"].append(row)
        elif value < 2.0:
            departure_buckets["1.5-2.0ATR"].append(row)
        else:
            departure_buckets[">=2.0ATR"].append(row)
    return {
        "pattern": group("pattern"),
        "zone_class": group("zone_class"),
        "structural_bos": group("structural_bos"),
        "departure_strength": {
            key: _summary(value) for key, value in departure_buckets.items()
        },
    }


def evaluate_year(price_m1: pd.DataFrame, *, target_year: int) -> dict[str, Any]:
    zones = build_htf_zones(price_m1)
    superseded = causal_superseded_at(zones)
    arrays = _price_arrays(price_m1)
    episodes: list[dict[str, Any]] = []
    for zone in zones:
        event = evaluate_first_touch(
            price_m1,
            zone=zone,
            arrays=arrays,
            valid_until=superseded.get(zone.zone_id),
        )
        if event is None:
            continue
        touch = datetime.fromisoformat(str(event["touch_at"]).replace("Z", "+00:00"))
        if touch.year == int(target_year):
            episodes.append(event)

    catalog = [
        {
            **_zone_record(zone),
            "superseded_at": (
                None
                if superseded.get(zone.zone_id) is None
                else ensure_utc(superseded[zone.zone_id]).isoformat()
            ),
        }
        for zone in zones
        if ensure_utc(zone.available_at).year == int(target_year)
    ]
    episodes.sort(key=lambda r: (r["touch_at"], r["timeframe"], r["zone_id"]))
    catalog.sort(key=lambda r: (r["available_at"], r["timeframe"], r["zone_id"]))

    return {
        "research_version": RESEARCH_VERSION,
        "year": int(target_year),
        "zone_catalog_count": len(catalog),
        "episode_count": len(episodes),
        "zone_catalog": catalog,
        "episodes": episodes,
        "summary": grouped_summary(episodes),
        "factors": factor_summary(episodes),
        "contract": {
            "zone_engine": "XAU_RIZAN_SD_LIQUIDITY_V342_1",
            "timeframes": ["H4", "H1"],
            "formation": "CAUSAL_COMPACT_BASE_TO_DISPLACEMENT_WITH_BOS_OR_STRONG_DEPARTURE",
            "availability": "ONLY_AFTER_DEPARTURE_CANDLE_CLOSE",
            "touch": "FIRST_CAUSAL_TOUCH_BEFORE_CLOSE_INVALIDATION",
            "target": "0.50_PARENT_ATR_FROM_PROXIMAL",
            "break": "M1_CLOSE_BEYOND_DISTAL_PLUS_0.05_PARENT_ATR",
            "sweep": "WICK_BEYOND_DISTAL_WITHOUT_PRIOR_BREAK_BEFORE_SUCCESSFUL_REVERSAL",
            "same_m1_precedence": "BREAK_FIRST_AND_SUCCESS_TARGET_BAR_EXCLUDED_FROM_SWEEP_CLASSIFICATION",
            "execution_authority": False,
            "execution_influence": False,
        },
    }


def aggregate_years(shards: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(shards, key=lambda x: int(x["year"]))
    all_episodes = [dict(r) for shard in ordered for r in list(shard.get("episodes") or [])]
    all_catalog = [dict(r) for shard in ordered for r in list(shard.get("zone_catalog") or [])]

    def select(start: int, end: int) -> list[dict[str, Any]]:
        out = []
        for row in all_episodes:
            year = datetime.fromisoformat(str(row["touch_at"]).replace("Z", "+00:00")).year
            if start <= year <= end:
                out.append(row)
        return out

    train = select(2012, 2024)
    oos = select(2025, 2026)
    full = select(2012, 2026)
    return {
        "research_version": RESEARCH_VERSION,
        "years": [int(x["year"]) for x in ordered],
        "year_count": len(ordered),
        "zone_catalog_count": len(all_catalog),
        "episode_count": len(full),
        "periods": {
            "development_2012_2024": {
                "summary": grouped_summary(train),
                "factors": factor_summary(train),
            },
            "oos_2025_2026": {
                "summary": grouped_summary(oos),
                "factors": factor_summary(oos),
            },
            "full_2012_2026": {
                "summary": grouped_summary(full),
                "factors": factor_summary(full),
            },
        },
        "zone_catalog": all_catalog,
        "episodes": full,
        "promotion_policy": {
            "automatic_runtime_promotion": False,
            "forward_demo_required": True,
            "reason": (
                "Historical sweep distributions are evidence for map calibration only; "
                "they cannot grant execution authority."
            ),
        },
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
    }
