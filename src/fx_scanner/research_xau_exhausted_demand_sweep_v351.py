from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict
from datetime import datetime, timedelta
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_xau_sd_liquidity_v345 import (
    bars_from_frame,
    build_htf_zones,
    load_price_frame,
    resample_ohlc,
)
from .xau_sd_liquidity_engine_v342 import SDZone, TF_MINUTES, TF_PARAMS

RESEARCH_VERSION = "XAU_RIZAN_EXHAUSTED_DEMAND_SWEEP_PATH_V351_1"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False

PARENT_EXHAUST_MITIGATION = 0.95
PARENT_EXHAUST_TOUCHES = 4
FRESH_H1_MAX_GAP_PARENT_ATR = 1.50
H2_LOOKBELOW_H1_ATR = 1.25
H2_TOLERANCE_H1_ATR = 0.15
CHAIN_HORIZON_HOURS = 72.0
H1_TOUCH_HORIZON_HOURS = 48.0
H2_AFTER_H1_HOURS = 18.0
CONFIRM_AFTER_H2_HOURS = 8.0
SUPPLY_TARGET_HORIZON_HOURS = 72.0


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(pd.Timestamp(value).to_pydatetime())


def _q(values: Sequence[float], quantile: float) -> float | None:
    clean = [float(v) for v in values if isfinite(float(v))]
    if not clean:
        return None
    return float(np.quantile(np.asarray(clean, dtype=float), quantile))


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    den = 1.0 + z * z / total
    center = p + z * z / (2.0 * total)
    margin = z * sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (center - margin) / den)


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev).abs(),
            (frame["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=max(6, period // 2)).mean()


def _zone_record(zone: SDZone) -> dict[str, Any]:
    row = asdict(zone)
    row["origin_at"] = ensure_utc(zone.origin_at).isoformat()
    row["available_at"] = ensure_utc(zone.available_at).isoformat()
    return row


def _zone_timeline(
    zone: SDZone,
    frame: pd.DataFrame,
    *,
    until: datetime | None = None,
) -> dict[str, Any]:
    if frame.empty:
        return {
            "touch_count": 0,
            "mitigation_depth": 0.0,
            "near_exhausted_at": None,
            "invalidated_at": None,
            "active": True,
        }

    tf_delta = pd.Timedelta(minutes=TF_MINUTES[zone.timeframe])
    work = frame.copy()
    work["known_at"] = work["timestamp"] + tf_delta
    expiry = ensure_utc(zone.available_at) + timedelta(
        hours=float(TF_PARAMS[zone.timeframe]["lifecycle_hours"])
    )
    limit = expiry if until is None else min(expiry, ensure_utc(until))
    future = work[
        (work["known_at"] > pd.Timestamp(zone.available_at))
        & (work["known_at"] <= pd.Timestamp(limit))
    ]

    width = max(float(zone.high) - float(zone.low), 1e-12)
    touch_count = 0
    was_inside = False
    mitigation = 0.0
    near_exhausted_at: datetime | None = None
    degraded_at: datetime | None = None
    invalidated_at: datetime | None = None

    for _, row in future.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        known_at = _dt(row["known_at"])
        inside = high >= float(zone.low) and low <= float(zone.high)
        if inside and not was_inside:
            touch_count += 1
        if inside:
            if zone.direction == "LONG":
                adverse = max(float(zone.low), low)
                depth = (float(zone.high) - adverse) / width
            else:
                adverse = min(float(zone.high), high)
                depth = (adverse - float(zone.low)) / width
            mitigation = max(mitigation, min(1.5, max(0.0, depth)))

        if degraded_at is None and (mitigation >= 0.75 or touch_count >= 2):
            degraded_at = known_at
        if near_exhausted_at is None and (
            mitigation >= PARENT_EXHAUST_MITIGATION
            or touch_count >= PARENT_EXHAUST_TOUCHES
        ):
            near_exhausted_at = known_at

        invalid = (
            close < float(zone.distal) - 0.05 * float(zone.atr)
            if zone.direction == "LONG"
            else close > float(zone.distal) + 0.05 * float(zone.atr)
        )
        if invalid:
            invalidated_at = known_at
            break
        was_inside = inside

    active = invalidated_at is None and limit < expiry if until is not None else invalidated_at is None
    if until is not None and ensure_utc(until) >= expiry:
        active = False
    return {
        "touch_count": touch_count,
        "mitigation_depth": mitigation,
        "degraded_at": None if degraded_at is None else degraded_at.isoformat(),
        "near_exhausted_at": (
            None if near_exhausted_at is None else near_exhausted_at.isoformat()
        ),
        "invalidated_at": None if invalidated_at is None else invalidated_at.isoformat(),
        "active": bool(active),
        "expiry_at": expiry.isoformat(),
    }


def _h2_pivots(price_m1: pd.DataFrame) -> list[dict[str, Any]]:
    h2 = resample_ohlc(price_m1, "2h")
    if len(h2) < 7:
        return []
    output: list[dict[str, Any]] = []
    for i in range(2, len(h2) - 2):
        row = h2.iloc[i]
        around = h2.iloc[i - 2 : i + 3]
        available_at = _dt(h2.iloc[i + 2]["timestamp"]) + timedelta(hours=2)
        if float(row["low"]) <= float(around["low"].min()):
            output.append(
                {
                    "kind": "SUPPORT",
                    "price": float(row["low"]),
                    "available_at": available_at,
                    "source": "H2_SWING_LOW",
                }
            )
        if float(row["high"]) >= float(around["high"].max()):
            output.append(
                {
                    "kind": "RESISTANCE",
                    "price": float(row["high"]),
                    "available_at": available_at,
                    "source": "H2_SWING_HIGH",
                }
            )
    return output


def _h2_cluster_below(
    pivots: Sequence[dict[str, Any]],
    *,
    as_of: datetime,
    h1_zone: SDZone,
) -> dict[str, Any]:
    lower = float(h1_zone.low) - H2_LOOKBELOW_H1_ATR * float(h1_zone.atr)
    upper = float(h1_zone.low) + 0.15 * float(h1_zone.atr)
    candidates = [
        p
        for p in pivots
        if ensure_utc(p["available_at"]) <= ensure_utc(as_of)
        and lower <= float(p["price"]) <= upper
    ]
    if not candidates:
        return {}

    tolerance = max(H2_TOLERANCE_H1_ATR * float(h1_zone.atr), 1.0)
    candidates = sorted(candidates, key=lambda p: float(p["price"]))
    groups: list[list[dict[str, Any]]] = []
    for item in candidates:
        if not groups:
            groups.append([item])
            continue
        center = sum(float(x["price"]) for x in groups[-1]) / len(groups[-1])
        if abs(float(item["price"]) - center) <= tolerance:
            groups[-1].append(item)
        else:
            groups.append([item])

    clusters: list[dict[str, Any]] = []
    for group in groups:
        prices = [float(x["price"]) for x in group]
        support_n = sum(1 for x in group if x["kind"] == "SUPPORT")
        resistance_n = sum(1 for x in group if x["kind"] == "RESISTANCE")
        strength = len(group)
        if support_n == 0:
            continue
        clusters.append(
            {
                "low": min(prices),
                "high": max(prices),
                "center": float(np.mean(prices)),
                "strength": strength,
                "support_count": support_n,
                "resistance_count": resistance_n,
                "kind": "FLIP" if resistance_n else "SUPPORT",
                "sources": sorted({str(x["source"]) for x in group}),
                "distance_below_h1_atr": (
                    max(0.0, float(h1_zone.low) - max(prices))
                    / max(float(h1_zone.atr), 1e-12)
                ),
            }
        )
    if not clusters:
        return {}
    clusters.sort(
        key=lambda c: (
            0 if int(c["strength"]) >= 2 else 1,
            max(0.0, float(h1_zone.low) - float(c["high"])),
            -int(c["strength"]),
        )
    )
    return clusters[0]


def _first_touch(
    price_m1: pd.DataFrame,
    *,
    low: float,
    high: float,
    start_at: datetime,
    end_at: datetime,
) -> dict[str, Any] | None:
    ts = list(price_m1["timestamp"])
    start = bisect_left(ts, pd.Timestamp(ensure_utc(start_at)))
    end = bisect_right(ts, pd.Timestamp(ensure_utc(end_at)))
    if end <= start:
        return None
    seg = price_m1.iloc[start:end]
    mask = (seg["low"] <= float(high)) & (seg["high"] >= float(low))
    pos = np.flatnonzero(mask.to_numpy())
    if len(pos) == 0:
        return None
    idx = start + int(pos[0])
    row = price_m1.iloc[idx]
    return {
        "index": idx,
        "at": (_dt(row["timestamp"]) + timedelta(minutes=1)),
        "low": float(row["low"]),
        "high": float(row["high"]),
        "close": float(row["close"]),
    }


def _first_level_reach(
    price_m1: pd.DataFrame,
    *,
    level: float,
    start_at: datetime,
    end_at: datetime,
    side: str,
) -> datetime | None:
    ts = list(price_m1["timestamp"])
    start = bisect_left(ts, pd.Timestamp(ensure_utc(start_at)))
    end = bisect_right(ts, pd.Timestamp(ensure_utc(end_at)))
    if end <= start:
        return None
    seg = price_m1.iloc[start:end]
    mask = seg["high"] >= level if side == "UP" else seg["low"] <= level
    pos = np.flatnonzero(mask.to_numpy())
    if len(pos) == 0:
        return None
    row = seg.iloc[int(pos[0])]
    return _dt(row["timestamp"]) + timedelta(minutes=1)


def _confirm_bullish_reversal(
    price_m1: pd.DataFrame,
    *,
    h1_zone: SDZone,
    h2_touch_at: datetime,
) -> dict[str, Any]:
    m5 = resample_ohlc(price_m1, "5min")
    if m5.empty:
        return {"confirmed": False}
    m5["known_at"] = m5["timestamp"] + pd.Timedelta(minutes=5)
    m5["atr14"] = _atr(m5)
    end_at = ensure_utc(h2_touch_at) + timedelta(hours=CONFIRM_AFTER_H2_HOURS)
    segment = m5[
        (m5["known_at"] >= pd.Timestamp(ensure_utc(h2_touch_at)))
        & (m5["known_at"] <= pd.Timestamp(end_at))
    ]
    if segment.empty:
        return {"confirmed": False}

    reclaim_at: datetime | None = None
    reclaim_proximal = False
    for idx, row in segment.iterrows():
        known_at = _dt(row["known_at"])
        close = float(row["close"])
        if reclaim_at is None and close > float(h1_zone.low):
            reclaim_at = known_at
        if reclaim_at is not None and close > float(h1_zone.proximal):
            reclaim_proximal = True
        if reclaim_at is None:
            continue
        prior = m5.loc[max(0, idx - 6) : idx - 1]
        if prior.empty:
            continue
        atr = float(row["atr14"]) if pd.notna(row["atr14"]) else 0.0
        rng = max(float(row["high"]) - float(row["low"]), 1e-12)
        body = abs(float(row["close"]) - float(row["open"])) / rng
        mss_level = float(prior["high"].max())
        mss = close > mss_level
        displacement = atr > 0 and rng >= 0.80 * atr and body >= 0.50
        if mss and displacement:
            return {
                "confirmed": True,
                "reclaim_at": reclaim_at.isoformat(),
                "confirmed_at": known_at.isoformat(),
                "mss_level": mss_level,
                "reclaim_proximal": reclaim_proximal,
                "confirmation_close": close,
                "confirmation_atr_m5": atr,
            }
    return {
        "confirmed": False,
        "reclaim_at": None if reclaim_at is None else reclaim_at.isoformat(),
        "reclaim_proximal": reclaim_proximal,
    }


def _active_at(
    zone: SDZone,
    *,
    frame: pd.DataFrame,
    as_of: datetime,
) -> bool:
    if ensure_utc(zone.available_at) > ensure_utc(as_of):
        return False
    state = _zone_timeline(zone, frame, until=as_of)
    return bool(state["active"] and state["invalidated_at"] is None)


def _nearest_supply(
    zones: Sequence[SDZone],
    *,
    h1_frame: pd.DataFrame,
    h4_frame: pd.DataFrame,
    as_of: datetime,
    price: float,
) -> SDZone | None:
    candidates: list[tuple[float, int, float, SDZone]] = []
    for zone in zones:
        if zone.direction != "SHORT" or ensure_utc(zone.available_at) > ensure_utc(as_of):
            continue
        if float(zone.low) <= price:
            continue
        frame = h4_frame if zone.timeframe == "H4" else h1_frame
        if not _active_at(zone, frame=frame, as_of=as_of):
            continue
        candidates.append(
            (
                float(zone.low) - price,
                0 if zone.timeframe == "H4" else 1,
                -float(zone.score_seed),
                zone,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return candidates[0][3]


def _supply_outcome(
    price_m1: pd.DataFrame,
    *,
    supply: SDZone,
    confirm_at: datetime,
    invalidation_level: float,
) -> dict[str, Any]:
    end_at = ensure_utc(confirm_at) + timedelta(hours=SUPPLY_TARGET_HORIZON_HOURS)
    ts = list(price_m1["timestamp"])
    start = bisect_left(ts, pd.Timestamp(ensure_utc(confirm_at)))
    end = bisect_right(ts, pd.Timestamp(end_at))
    for idx in range(start, min(end, len(price_m1))):
        row = price_m1.iloc[idx]
        at = _dt(row["timestamp"]) + timedelta(minutes=1)
        invalid = float(row["close"]) < invalidation_level
        target = float(row["high"]) >= float(supply.low)
        if invalid:
            return {
                "supply_hit": False,
                "clean_supply_hit": False,
                "outcome": "INVALIDATED_BEFORE_SUPPLY",
                "outcome_at": at.isoformat(),
            }
        if target:
            return {
                "supply_hit": True,
                "clean_supply_hit": True,
                "outcome": "OPPOSING_SUPPLY_HIT",
                "outcome_at": at.isoformat(),
                "minutes_to_supply": max(
                    0.0, (at - ensure_utc(confirm_at)).total_seconds() / 60.0
                ),
            }
    return {
        "supply_hit": False,
        "clean_supply_hit": False,
        "outcome": "SUPPLY_NOT_HIT_IN_HORIZON",
        "outcome_at": end_at.isoformat(),
    }


def _fresh_h1_below(
    zones: Sequence[SDZone],
    *,
    h1_frame: pd.DataFrame,
    parent: SDZone,
    as_of: datetime,
) -> SDZone | None:
    candidates: list[tuple[float, float, SDZone]] = []
    for zone in zones:
        if zone.timeframe != "H1" or zone.direction != "LONG":
            continue
        if ensure_utc(zone.available_at) > ensure_utc(as_of):
            continue
        if float(zone.high) > float(parent.low) + 0.05 * float(parent.atr):
            continue
        gap = max(0.0, float(parent.low) - float(zone.high))
        if gap > FRESH_H1_MAX_GAP_PARENT_ATR * float(parent.atr):
            continue
        state = _zone_timeline(zone, h1_frame, until=as_of)
        if not bool(state["active"]) or int(state["touch_count"]) != 0:
            continue
        candidates.append((gap, -float(zone.score_seed), zone))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def evaluate_year(price_m1: pd.DataFrame, *, target_year: int) -> dict[str, Any]:
    price_m1 = price_m1.copy()
    price_m1["timestamp"] = pd.to_datetime(price_m1["timestamp"], utc=True)
    h1_frame = resample_ohlc(price_m1, "1h")
    h4_frame = resample_ohlc(price_m1, "4h")
    zones = build_htf_zones(price_m1)
    h2_pivots = _h2_pivots(price_m1)

    events: list[dict[str, Any]] = []
    h4_demands = [z for z in zones if z.timeframe == "H4" and z.direction == "LONG"]

    for parent in h4_demands:
        parent_state = _zone_timeline(parent, h4_frame)
        exhausted_raw = parent_state.get("near_exhausted_at")
        if not exhausted_raw:
            continue
        exhausted_at = _dt(exhausted_raw)
        if exhausted_at.year != int(target_year):
            continue

        child = _fresh_h1_below(
            zones,
            h1_frame=h1_frame,
            parent=parent,
            as_of=exhausted_at,
        )
        cluster = (
            _h2_cluster_below(h2_pivots, as_of=exhausted_at, h1_zone=child)
            if child is not None
            else {}
        )

        event: dict[str, Any] = {
            "year": int(target_year),
            "parent_zone": _zone_record(parent),
            "parent_touch_count": int(parent_state["touch_count"]),
            "parent_mitigation_depth": float(parent_state["mitigation_depth"]),
            "parent_exhausted_at": exhausted_at.isoformat(),
            "parent_invalidated_at": parent_state.get("invalidated_at"),
            "fresh_h1_available": child is not None,
            "h2_cluster_available": bool(cluster),
            "h1_zone": None if child is None else _zone_record(child),
            "h2_cluster": cluster,
            "h1_touched": False,
            "h2_reached": False,
            "h2_before_parent_rebound": False,
            "confirmed": False,
            "opposing_supply_available": False,
            "supply_hit": False,
            "clean_supply_hit": False,
        }

        if child is None:
            events.append(event)
            continue

        chain_end = exhausted_at + timedelta(hours=CHAIN_HORIZON_HOURS)
        h1_touch = _first_touch(
            price_m1,
            low=float(child.low),
            high=float(child.high),
            start_at=exhausted_at,
            end_at=min(
                chain_end,
                exhausted_at + timedelta(hours=H1_TOUCH_HORIZON_HOURS),
            ),
        )
        parent_rebound_level = float(parent.proximal) + 0.50 * float(parent.atr)
        parent_rebound_at = _first_level_reach(
            price_m1,
            level=parent_rebound_level,
            start_at=exhausted_at,
            end_at=chain_end,
            side="UP",
        )
        event["parent_rebound_level"] = parent_rebound_level
        event["parent_rebound_at"] = (
            None if parent_rebound_at is None else parent_rebound_at.isoformat()
        )

        if h1_touch is None:
            events.append(event)
            continue
        event["h1_touched"] = True
        event["h1_touch_at"] = h1_touch["at"].isoformat()
        event["minutes_exhausted_to_h1"] = (
            h1_touch["at"] - exhausted_at
        ).total_seconds() / 60.0

        if not cluster:
            events.append(event)
            continue

        # Strict sweep definition: price must reach the pre-known H2 cluster
        # at or below the H1 distal. A level slightly overlapping the H1 zone
        # cannot qualify merely because the H1 zone itself was touched.
        h2_sweep_high = min(float(cluster["high"]), float(child.low))
        h2_touch = _first_touch(
            price_m1,
            low=float(cluster["low"]),
            high=h2_sweep_high,
            start_at=h1_touch["at"],
            end_at=min(
                chain_end,
                h1_touch["at"] + timedelta(hours=H2_AFTER_H1_HOURS),
            ),
        )
        if h2_touch is None:
            events.append(event)
            continue

        event["h2_reached"] = True
        event["h2_sweep_below_h1_distal"] = bool(float(h2_touch["low"]) < float(child.low))
        event["h2_touch_at"] = h2_touch["at"].isoformat()
        event["minutes_h1_to_h2"] = (
            h2_touch["at"] - h1_touch["at"]
        ).total_seconds() / 60.0
        event["h2_before_parent_rebound"] = bool(
            parent_rebound_at is None or h2_touch["at"] < parent_rebound_at
        )
        event["sweep_extension_below_h1_atr"] = max(
            0.0, float(child.low) - float(h2_touch["low"])
        ) / max(float(child.atr), 1e-12)

        confirmation = _confirm_bullish_reversal(
            price_m1,
            h1_zone=child,
            h2_touch_at=h2_touch["at"],
        )
        event["confirmation"] = confirmation
        event["confirmed"] = bool(confirmation.get("confirmed"))
        if not event["confirmed"]:
            events.append(event)
            continue

        confirm_at = _dt(confirmation["confirmed_at"])
        confirm_close = float(confirmation["confirmation_close"])
        supply = _nearest_supply(
            zones,
            h1_frame=h1_frame,
            h4_frame=h4_frame,
            as_of=confirm_at,
            price=confirm_close,
        )
        if supply is None:
            events.append(event)
            continue

        event["opposing_supply_available"] = True
        event["opposing_supply"] = _zone_record(supply)
        invalidation_level = min(
            float(child.low),
            float(cluster["low"]),
            float(h2_touch["low"]),
        ) - 0.10 * float(child.atr)
        event["post_confirm_invalidation"] = invalidation_level
        outcome = _supply_outcome(
            price_m1,
            supply=supply,
            confirm_at=confirm_at,
            invalidation_level=invalidation_level,
        )
        event.update(outcome)
        events.append(event)

    return {
        "research_version": RESEARCH_VERSION,
        "year": int(target_year),
        "event_count": len(events),
        "events": events,
        "summary": summarize(events),
        "contract": {
            "hypothesis": (
                "NEAR_EXHAUSTED_H4_DEMAND -> PREKNOWN_FRESH_H1_DEMAND_BELOW -> "
                "PREKNOWN_H2_SUPPORT_FLIP_CLUSTER -> H2_REACH -> BULLISH_RECLAIM_MSS_DISPLACEMENT -> "
                "OPPOSING_ACTIVE_SUPPLY"
            ),
            "parent_exhaustion": (
                "H4 demand mitigation>=0.95 zone width OR touch_count>=4, known only at H4 close"
            ),
            "fresh_h1": (
                "H1 demand available before parent exhaustion, untouched and active, within "
                "1.50 parent ATR below H4 demand"
            ),
            "h2_context": (
                "causally confirmed H2 swing-low/support or flip cluster already known at parent exhaustion; "
                "no Afiq price is hard-coded"
            ),
            "confirmation": (
                "after H2 reach: M5 reclaim above H1 distal then bullish local MSS plus "
                "range>=0.80 M5 ATR and body>=0.50 within 8h"
            ),
            "target": "nearest active H1/H4 supply above confirmation, 72h horizon",
            "development_period": "2012-2024",
            "oos_period": "2025-2026",
            "execution_authority": False,
            "execution_influence": False,
        },
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
    }


def summarize(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(events)
    fresh = [e for e in events if e.get("fresh_h1_available")]
    h2_map = [e for e in fresh if e.get("h2_cluster_available")]
    h1_touch = [e for e in h2_map if e.get("h1_touched")]
    h2_reach = [e for e in h1_touch if e.get("h2_reached")]
    h2_before_rebound = [e for e in h2_reach if e.get("h2_before_parent_rebound")]
    confirmed = [e for e in h2_reach if e.get("confirmed")]
    supply_ready = [e for e in confirmed if e.get("opposing_supply_available")]
    clean = [e for e in supply_ready if e.get("clean_supply_hit")]
    return {
        "parent_exhausted_events": total,
        "with_fresh_h1_below": len(fresh),
        "with_preknown_h2_cluster": len(h2_map),
        "h1_touched": len(h1_touch),
        "h2_reached": len(h2_reach),
        "h2_reached_before_parent_050_atr_rebound": len(h2_before_rebound),
        "h2_before_rebound_rate": (
            None if not h2_map else len(h2_before_rebound) / len(h2_map)
        ),
        "confirmation_after_h2": len(confirmed),
        "confirmation_rate_after_h2": (
            None if not h2_reach else len(confirmed) / len(h2_reach)
        ),
        "opposing_supply_available_after_confirmation": len(supply_ready),
        "clean_opposing_supply_hits": len(clean),
        "clean_supply_rate_after_confirmation": (
            None if not supply_ready else len(clean) / len(supply_ready)
        ),
        "clean_supply_wilson_lower_95": _wilson_lower(len(clean), len(supply_ready)),
        "minutes_exhausted_to_h1_p50": _q(
            [e["minutes_exhausted_to_h1"] for e in h1_touch],
            0.50,
        ),
        "minutes_h1_to_h2_p50": _q(
            [e["minutes_h1_to_h2"] for e in h2_reach],
            0.50,
        ),
        "sweep_extension_h1_atr_p50": _q(
            [e["sweep_extension_below_h1_atr"] for e in h2_reach],
            0.50,
        ),
        "sweep_extension_h1_atr_p75": _q(
            [e["sweep_extension_below_h1_atr"] for e in h2_reach],
            0.75,
        ),
        "sweep_extension_h1_atr_p90": _q(
            [e["sweep_extension_below_h1_atr"] for e in h2_reach],
            0.90,
        ),
        "h2_strength_p50": _q(
            [float((e.get("h2_cluster") or {}).get("strength") or 0.0) for e in h2_map],
            0.50,
        ),
    }


def aggregate_years(shards: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(shards, key=lambda x: int(x["year"]))
    all_events = [dict(e) for shard in ordered for e in list(shard.get("events") or [])]

    def select(start: int, end: int) -> list[dict[str, Any]]:
        return [e for e in all_events if start <= int(e.get("year") or 0) <= end]

    development = select(2012, 2024)
    oos = select(2025, 2026)
    full = select(2012, 2026)
    return {
        "research_version": RESEARCH_VERSION,
        "years": [int(x["year"]) for x in ordered],
        "year_count": len(ordered),
        "event_count": len(full),
        "periods": {
            "development_2012_2024": {
                "summary": summarize(development),
                "events": development,
            },
            "oos_2025_2026": {
                "summary": summarize(oos),
                "events": oos,
            },
            "full_2012_2026": {
                "summary": summarize(full),
                "events": full,
            },
        },
        "promotion_policy": {
            "automatic_runtime_promotion": False,
            "forward_shadow_required": True,
            "reason": (
                "This is conditional path evidence, not execution authority. "
                "Thresholds must survive OOS and prospective replay before any runtime influence."
            ),
        },
        "execution_authority": False,
        "execution_influence": False,
    }
