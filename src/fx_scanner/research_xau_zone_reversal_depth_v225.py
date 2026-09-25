from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite, sqrt
from statistics import median
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .demo_xau_afic_path_shadow_observer import _atr
from .demo_xau_supply_demand_atlas_v182 import (
    SDZone,
    _all_zones,
    _classify_pattern,
    _stable_sd_zone_id,
)
from .models import Bar, ensure_utc
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_ZONE_REVERSAL_DEPTH_V225"
ARTIFACT_CONTRACT = "XAU_ZONE_REVERSAL_DEPTH_V225_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

REACTION_ATR_MULTIPLE = 0.50
DEPTH_BIN_WIDTH = 0.10
MIN_HAZARD_AT_RISK = 30

OBSERVATION_HOURS = {
    "M15": 24 * 3,
    "H1": 24 * 10,
    "H4": 24 * 30,
}
REACTION_HORIZON_MINUTES = {
    "M15": 4 * 60,
    "H1": 8 * 60,
    "H4": 16 * 60,
}

M15_MIN_DEPARTURE_RANGE_ATR = 1.00
M15_MIN_DEPARTURE_BODY_FRACTION = 0.50
M15_MAX_BASE_RANGE_ATR = 1.25


@dataclass(frozen=True, slots=True)
class DepthEpisode:
    zone_id: str
    timeframe: str
    zone_class: str
    pattern: str
    direction: str
    available_at: datetime
    touch_at: datetime
    outcome_at: datetime
    zone_low: float
    zone_high: float
    proximal: float
    distal: float
    atr_points: float
    zone_width: float
    outcome: str
    reaction_hit: bool
    break_hit: bool
    max_depth_reached: float
    turning_depth: float | None
    turning_price: float | None
    minutes_to_outcome: float
    departure_range_atr: float
    departure_body_fraction: float
    base_range_atr: float
    structural_bos: bool
    h1_child_zone_id: str | None = None
    h1_child_depth: float | None = None
    m15_child_zone_id: str | None = None
    m15_child_depth: float | None = None


def _load_price_frame(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V225_MISSING_PRICE_COLUMNS:{sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required))
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise RuntimeError("V225_PRICE_FRAME_EMPTY")
    return frame.reset_index(drop=True)


def _resample_ohlc(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    work = frame.set_index("timestamp")
    out = work.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    out = out.reset_index().rename(columns={"timestamp": "time"})
    return out


def _bars_from_frame(frame: pd.DataFrame, timeframe: str) -> tuple[Bar, ...]:
    output: list[Bar] = []
    for _, row in frame.iterrows():
        output.append(
            Bar(
                symbol="XAUUSD",
                timeframe=timeframe,
                timestamp=ensure_utc(pd.Timestamp(row["time"]).to_pydatetime()),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_count=0,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(output)


def _base_geometry(base: pd.DataFrame, direction: str) -> tuple[float, float, float, float]:
    low = float(base["low"].min())
    high = float(base["high"].max())
    if direction == "LONG":
        proximal = float(base[["open", "close"]].min(axis=1).min())
        distal = low
        proximal = min(high, max(low, proximal))
        return distal, proximal, proximal, distal
    proximal = float(base[["open", "close"]].max(axis=1).max())
    distal = high
    proximal = min(high, max(low, proximal))
    return proximal, distal, proximal, distal


def _detect_m15_zones(frame: pd.DataFrame) -> tuple[SDZone, ...]:
    if frame.empty or len(frame) < 20:
        return ()
    work = frame.copy().reset_index(drop=True)
    work["atr14"] = _atr(work, 14)
    zones: list[SDZone] = []

    for i in range(16, len(work)):
        row = work.iloc[i]
        atr = float(row.get("atr14") or 0.0)
        if not isfinite(atr) or atr <= 0:
            continue
        o = float(row["open"])
        h = float(row["high"])
        low_row = float(row["low"])
        c = float(row["close"])
        rng = max(h - low_row, 1e-12)
        body_fraction = abs(c - o) / rng
        range_atr = rng / atr
        if range_atr < M15_MIN_DEPARTURE_RANGE_ATR:
            continue
        if body_fraction < M15_MIN_DEPARTURE_BODY_FRACTION:
            continue

        direction = "LONG" if c > o else "SHORT" if c < o else ""
        if not direction:
            continue

        best: tuple[float, int, pd.DataFrame] | None = None
        for base_len in (1, 2, 3):
            start = i - base_len
            if start < 2:
                continue
            base = work.iloc[start:i]
            base_range = float(base["high"].max() - base["low"].min())
            base_range_atr = base_range / atr
            body_fracs = (
                (base["close"].astype(float) - base["open"].astype(float)).abs()
                / (base["high"].astype(float) - base["low"].astype(float)).clip(lower=1e-12)
            )
            compactness = base_range_atr + float(body_fracs.mean()) * 0.35
            if base_range_atr > M15_MAX_BASE_RANGE_ATR:
                continue
            if best is None or compactness < best[0]:
                best = (compactness, base_len, base.copy())
        if best is None:
            continue

        _, base_len, base = best
        low, high, proximal, distal = _base_geometry(base, direction)
        width = high - low
        if width <= 0 or width / atr > M15_MAX_BASE_RANGE_ATR:
            continue

        pre_close = float(work.iloc[i - base_len - 1]["close"])
        base_mid = (low + high) / 2.0
        pattern = _classify_pattern(
            direction=direction,
            pre_base_close=pre_close,
            base_mid=base_mid,
        )
        available_at = ensure_utc(pd.Timestamp(row["time"]).to_pydatetime())
        origin_at = ensure_utc(pd.Timestamp(base.iloc[0]["time"]).to_pydatetime())
        zone_id = _stable_sd_zone_id(
            timeframe="M15",
            direction=direction,
            zone_class="IMBALANCE",
            origin_at=origin_at,
            available_at=available_at,
            low=low,
            high=high,
        )
        zones.append(
            SDZone(
                zone_id=zone_id,
                timeframe="M15",
                zone_class="IMBALANCE",
                pattern=pattern,
                direction=direction,
                low=low,
                high=high,
                proximal=proximal,
                distal=distal,
                available_at=available_at,
                origin_at=origin_at,
                departure_at=available_at,
                atr_points=atr,
                base_bars=base_len,
                base_range_atr=width / atr,
                departure_range_atr=range_atr,
                departure_body_fraction=body_fraction,
                structural_bos=False,
            )
        )
    return tuple(zones)


def build_zones(price_m1: pd.DataFrame) -> tuple[SDZone, ...]:
    m15 = _resample_ohlc(price_m1, "15min")
    bars_m15 = _bars_from_frame(m15, "M15")
    if not bars_m15:
        return ()
    as_of = ensure_utc(bars_m15[-1].timestamp) + timedelta(minutes=15)
    htf = [
        zone
        for zone in _all_zones(bars_m15, as_of=as_of)
        if zone.timeframe in {"H1", "H4"}
    ]
    m15_zones = list(_detect_m15_zones(m15))
    return tuple(sorted(
        htf + m15_zones,
        key=lambda zone: (ensure_utc(zone.available_at), zone.timeframe, zone.zone_id),
    ))


def normalized_depth(zone: SDZone, price: float) -> float:
    width = max(float(zone.high) - float(zone.low), 1e-12)
    if zone.direction == "LONG":
        return (float(zone.proximal) - float(price)) / width
    return (float(price) - float(zone.proximal)) / width


def _invalidated(close: float, zone: SDZone) -> bool:
    if zone.direction == "LONG":
        return close < float(zone.distal)
    return close > float(zone.distal)


def _touches(high: float, low: float, zone: SDZone) -> bool:
    return low <= float(zone.high) and high >= float(zone.low)


def _target(zone: SDZone) -> float:
    reaction = REACTION_ATR_MULTIPLE * float(zone.atr_points)
    if zone.direction == "LONG":
        return float(zone.proximal) + reaction
    return float(zone.proximal) - reaction


def evaluate_first_touch(
    price_m1: pd.DataFrame,
    *,
    zone: SDZone,
) -> DepthEpisode | None:
    timestamps = list(price_m1["timestamp"])
    available = ensure_utc(zone.available_at)
    start = bisect_left(timestamps, available)
    if start >= len(price_m1):
        return None
    expiry = available + timedelta(hours=OBSERVATION_HOURS[zone.timeframe])
    end = bisect_right(timestamps, expiry)
    target = _target(zone)

    touch_index: int | None = None
    for index in range(start, min(end, len(price_m1))):
        row = price_m1.iloc[index]
        if _invalidated(float(row["close"]), zone):
            return None
        if _touches(float(row["high"]), float(row["low"]), zone):
            touch_index = index
            break
    if touch_index is None:
        return None

    touch_row = price_m1.iloc[touch_index]
    touch_at = ensure_utc(pd.Timestamp(touch_row["timestamp"]).to_pydatetime())
    if _invalidated(float(touch_row["close"]), zone):
        return None

    if zone.direction == "LONG":
        adverse_extreme = min(float(zone.proximal), float(touch_row["low"]))
    else:
        adverse_extreme = max(float(zone.proximal), float(touch_row["high"]))
    max_depth = normalized_depth(zone, adverse_extreme)

    horizon_end = touch_at + timedelta(minutes=REACTION_HORIZON_MINUTES[zone.timeframe])
    reaction_end = bisect_right(timestamps, horizon_end)
    outcome = "STALL"
    outcome_at = horizon_end
    turning_price: float | None = None
    turning_depth: float | None = None
    reaction_hit = False
    break_hit = False

    # Target starts on the next M1 bar. On the target bar, do not incorporate a
    # fresh adverse extreme into the turning point because OHLC order is unknown.
    for index in range(touch_index + 1, min(reaction_end, len(price_m1))):
        row = price_m1.iloc[index]
        ts = ensure_utc(pd.Timestamp(row["timestamp"]).to_pydatetime())
        close = float(row["close"])
        if _invalidated(close, zone):
            break_hit = True
            outcome = "BREAK"
            outcome_at = ts
            if zone.direction == "LONG":
                adverse_extreme = min(adverse_extreme, float(row["low"]))
            else:
                adverse_extreme = max(adverse_extreme, float(row["high"]))
            max_depth = max(max_depth, normalized_depth(zone, adverse_extreme))
            break

        reached = (
            float(row["high"]) >= target
            if zone.direction == "LONG"
            else float(row["low"]) <= target
        )
        if reached:
            reaction_hit = True
            outcome = "HOLD_050"
            outcome_at = ts
            turning_price = adverse_extreme
            turning_depth = normalized_depth(zone, adverse_extreme)
            max_depth = max(max_depth, turning_depth)
            break

        if zone.direction == "LONG":
            adverse_extreme = min(adverse_extreme, float(row["low"]))
        else:
            adverse_extreme = max(adverse_extreme, float(row["high"]))
        max_depth = max(max_depth, normalized_depth(zone, adverse_extreme))

    if not reaction_hit and not break_hit:
        turning_price = None
        turning_depth = None

    return DepthEpisode(
        zone_id=zone.zone_id,
        timeframe=zone.timeframe,
        zone_class=zone.zone_class,
        pattern=zone.pattern,
        direction=zone.direction,
        available_at=available,
        touch_at=touch_at,
        outcome_at=outcome_at,
        zone_low=float(zone.low),
        zone_high=float(zone.high),
        proximal=float(zone.proximal),
        distal=float(zone.distal),
        atr_points=float(zone.atr_points),
        zone_width=float(zone.high) - float(zone.low),
        outcome=outcome,
        reaction_hit=reaction_hit,
        break_hit=break_hit,
        max_depth_reached=max_depth,
        turning_depth=turning_depth,
        turning_price=turning_price,
        minutes_to_outcome=max(0.0, (outcome_at - touch_at).total_seconds() / 60.0),
        departure_range_atr=float(zone.departure_range_atr),
        departure_body_fraction=float(zone.departure_body_fraction),
        base_range_atr=float(zone.base_range_atr),
        structural_bos=bool(zone.structural_bos),
    )


def _active_at(zone: SDZone, episode_by_zone: dict[str, DepthEpisode], at: datetime) -> bool:
    if ensure_utc(zone.available_at) > ensure_utc(at):
        return False
    episode = episode_by_zone.get(zone.zone_id)
    if episode is None:
        return True
    if episode.break_hit and episode.outcome_at <= ensure_utc(at):
        return False
    return True


def _contains_price(zone: SDZone, price: float) -> bool:
    return float(zone.low) <= float(price) <= float(zone.high)


def _overlaps(parent: SDZone, child: SDZone) -> bool:
    return max(float(parent.low), float(child.low)) <= min(float(parent.high), float(child.high))


def attach_hierarchy(
    episodes: Sequence[DepthEpisode],
    zones: Sequence[SDZone],
) -> tuple[DepthEpisode, ...]:
    by_zone = {row.zone_id: row for row in episodes}
    zone_by_id = {zone.zone_id: zone for zone in zones}
    h1 = [zone for zone in zones if zone.timeframe == "H1"]
    m15 = [zone for zone in zones if zone.timeframe == "M15"]
    output: list[DepthEpisode] = []

    for row in episodes:
        if row.timeframe != "H4" or not row.reaction_hit or row.turning_price is None:
            output.append(row)
            continue
        parent = zone_by_id.get(row.zone_id)
        if parent is None:
            output.append(row)
            continue

        h1_candidates = [
            zone
            for zone in h1
            if zone.direction == row.direction
            and _active_at(zone, by_zone, row.touch_at)
            and _overlaps(parent, zone)
            and _contains_price(zone, float(row.turning_price))
        ]
        h1_candidates.sort(
            key=lambda zone: (
                float(zone.high) - float(zone.low),
                -ensure_utc(zone.available_at).timestamp(),
            )
        )
        child_h1 = h1_candidates[0] if h1_candidates else None

        child_m15: SDZone | None = None
        if child_h1 is not None:
            m15_candidates = [
                zone
                for zone in m15
                if zone.direction == row.direction
                and _active_at(zone, by_zone, row.touch_at)
                and _overlaps(child_h1, zone)
                and _contains_price(zone, float(row.turning_price))
            ]
            m15_candidates.sort(
                key=lambda zone: (
                    float(zone.high) - float(zone.low),
                    -ensure_utc(zone.available_at).timestamp(),
                )
            )
            child_m15 = m15_candidates[0] if m15_candidates else None

        output.append(
            DepthEpisode(
                **{
                    **asdict(row),
                    "h1_child_zone_id": None if child_h1 is None else child_h1.zone_id,
                    "h1_child_depth": (
                        None
                        if child_h1 is None
                        else normalized_depth(child_h1, float(row.turning_price))
                    ),
                    "m15_child_zone_id": None if child_m15 is None else child_m15.zone_id,
                    "m15_child_depth": (
                        None
                        if child_m15 is None
                        else normalized_depth(child_m15, float(row.turning_price))
                    ),
                }
            )
        )
    return tuple(output)


def build_depth_dataset(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> tuple[tuple[SDZone, ...], tuple[DepthEpisode, ...]]:
    zones = build_zones(price_m1)
    episodes: list[DepthEpisode] = []
    for zone in zones:
        episode = evaluate_first_touch(price_m1, zone=zone)
        if episode is None or ensure_utc(episode.touch_at).year != int(target_year):
            continue
        episodes.append(episode)
    episodes.sort(key=lambda row: (row.touch_at, row.timeframe, row.zone_id))
    return zones, attach_hierarchy(episodes, zones)


def _depth_band(value: float | None) -> str:
    if value is None:
        return "NA"
    depth = float(value)
    if depth < 0:
        return "BEFORE_PROXIMAL"
    if depth >= 1.0:
        return "100%+"
    lower = int(depth / DEPTH_BIN_WIDTH) * 10
    upper = lower + 10
    return f"{lower:02d}-{upper:02d}%"


def _quantile(values: Sequence[float], q: float) -> float | None:
    return None if not values else float(np.quantile(np.array(values, dtype=float), q))


def depth_summary(rows: Sequence[DepthEpisode]) -> dict[str, Any]:
    episodes = list(rows)
    successes = [row for row in episodes if row.reaction_hit and row.turning_depth is not None]
    in_zone_success = [
        row for row in successes
        if 0.0 <= float(row.turning_depth) < 1.0
    ]
    depths = [float(row.turning_depth) for row in in_zone_success]

    hazard: list[dict[str, Any]] = []
    for index in range(10):
        lower = index / 10.0
        upper = (index + 1) / 10.0
        at_risk = sum(float(row.max_depth_reached) + 1e-12 >= lower for row in episodes)
        reversals = sum(
            row.reaction_hit
            and row.turning_depth is not None
            and lower <= float(row.turning_depth) < upper
            for row in episodes
        )
        hazard.append(
            {
                "band": f"{index * 10:02d}-{(index + 1) * 10:02d}%",
                "lower_depth": lower,
                "upper_depth": upper,
                "at_risk": int(at_risk),
                "reversals": int(reversals),
                "hazard": None if at_risk == 0 else reversals / at_risk,
                "wilson_lower_95": wilson_lower_bound(reversals, at_risk),
                "share_of_successes": (
                    None if not successes else reversals / len(successes)
                ),
            }
        )

    eligible_hazard = [
        item for item in hazard if int(item["at_risk"]) >= MIN_HAZARD_AT_RISK
    ]
    eligible_hazard.sort(
        key=lambda item: (
            -float(item.get("hazard") or 0.0),
            -float(item.get("wilson_lower_95") or 0.0),
            -int(item.get("at_risk") or 0),
        )
    )
    distribution: dict[str, int] = {}
    for row in successes:
        band = _depth_band(row.turning_depth)
        distribution[band] = distribution.get(band, 0) + 1

    return {
        "touches": len(episodes),
        "holds_050": len(successes),
        "hold_rate": None if not episodes else len(successes) / len(episodes),
        "hold_wilson_lower_95": wilson_lower_bound(len(successes), len(episodes)),
        "breaks": sum(row.break_hit for row in episodes),
        "stalls": sum(row.outcome == "STALL" for row in episodes),
        "successes_inside_zone": len(in_zone_success),
        "successes_100pct_plus": sum(
            row.turning_depth is not None and float(row.turning_depth) >= 1.0
            for row in successes
        ),
        "depth_p25": _quantile(depths, 0.25),
        "depth_median": _quantile(depths, 0.50),
        "depth_p75": _quantile(depths, 0.75),
        "turning_depth_distribution": distribution,
        "hazard_by_depth_band": hazard,
        "highest_hazard_bands_min_n": eligible_hazard[:3],
        "minimum_at_risk_for_ranking": MIN_HAZARD_AT_RISK,
    }


def grouped_report(rows: Sequence[DepthEpisode]) -> dict[str, Any]:
    output: dict[str, Any] = {"ALL": depth_summary(rows)}
    for timeframe in ("H4", "H1", "M15"):
        tf_rows = [row for row in rows if row.timeframe == timeframe]
        output[timeframe] = {
            "ALL": depth_summary(tf_rows),
            "LONG": depth_summary([row for row in tf_rows if row.direction == "LONG"]),
            "SHORT": depth_summary([row for row in tf_rows if row.direction == "SHORT"]),
        }
    return output


def hierarchy_report(rows: Sequence[DepthEpisode]) -> dict[str, Any]:
    h4_success = [
        row for row in rows
        if row.timeframe == "H4" and row.reaction_hit and row.turning_depth is not None
    ]
    h1_nested = [row for row in h4_success if row.h1_child_depth is not None]
    m15_nested = [row for row in h1_nested if row.m15_child_depth is not None]

    def nested_depth(values: Iterable[float | None]) -> dict[str, Any]:
        clean = [float(value) for value in values if value is not None and 0 <= float(value) < 1]
        distribution: dict[str, int] = {}
        for value in clean:
            band = _depth_band(value)
            distribution[band] = distribution.get(band, 0) + 1
        ranked = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
        return {
            "n": len(clean),
            "p25": _quantile(clean, 0.25),
            "median": _quantile(clean, 0.50),
            "p75": _quantile(clean, 0.75),
            "distribution": distribution,
            "modal_bands": [
                {"band": band, "count": count, "share": count / len(clean)}
                for band, count in ranked[:3]
            ] if clean else [],
        }

    combos: dict[tuple[str, str, str], int] = {}
    for row in m15_nested:
        key = (
            _depth_band(row.turning_depth),
            _depth_band(row.h1_child_depth),
            _depth_band(row.m15_child_depth),
        )
        combos[key] = combos.get(key, 0) + 1
    ranked_combos = sorted(combos.items(), key=lambda item: -item[1])

    return {
        "h4_successes": len(h4_success),
        "h1_child_coverage": None if not h4_success else len(h1_nested) / len(h4_success),
        "m15_child_coverage_given_h1": None if not h1_nested else len(m15_nested) / len(h1_nested),
        "h1_child_depth": nested_depth(row.h1_child_depth for row in h1_nested),
        "m15_child_depth": nested_depth(row.m15_child_depth for row in m15_nested),
        "top_nested_depth_combinations": [
            {
                "h4_band": key[0],
                "h1_band": key[1],
                "m15_band": key[2],
                "count": count,
                "share_of_m15_nested": None if not m15_nested else count / len(m15_nested),
            }
            for key, count in ranked_combos[:15]
        ],
        "interpretation": (
            "Hierarchy rows describe where successful H4 reversals landed inside pre-existing "
            "same-direction H1 and M15 child zones. Coverage is descriptive; it is not an "
            "execution probability."
        ),
    }


def serialize_episode(row: DepthEpisode) -> dict[str, Any]:
    payload = asdict(row)
    for key in ("available_at", "touch_at", "outcome_at"):
        payload[key] = ensure_utc(payload[key]).isoformat()
    return payload


def deserialize_episode(payload: dict[str, Any]) -> DepthEpisode:
    values = dict(payload)
    for key in ("available_at", "touch_at", "outcome_at"):
        values[key] = ensure_utc(datetime.fromisoformat(str(values[key]).replace("Z", "+00:00")))
    return DepthEpisode(**values)
