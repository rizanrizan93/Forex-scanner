from __future__ import annotations

import json
import os
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .demo_xau_supply_demand_atlas_v182 import SDZone
from .models import Bar, ensure_utc
from .research_xau_supply_demand_reaction_v183 import (
    _all_zones,
    build_reaction_dataset,
)
from .research_xau_zone_reversal_depth_v225 import (
    _bars_from_frame,
    _load_price_frame,
    _resample_ohlc,
)

RESEARCH_VERSION = "XAU_H1_NESTED_AGGRESSIVE_REVERSAL_V235_1"
YEAR_ARTIFACT_CONTRACT = "XAU_H1_NESTED_AGGRESSIVE_REVERSAL_V235_YEAR_1"

SYMBOL = "XAUUSD"
LEVERAGE = 100.0
LOT = 0.01
OUNCES_PER_001_LOT = 1.0
STOP_BUFFER_ATR = 0.15
MAX_HOLD_HOURS = 4.0
ENTRY_WINDOW_MINUTES = 15
TARGET_ATR_RUNGS = (0.50, 0.75, 1.00)
ENTRY_SLOTS = ("PROXIMAL", "MID")


def _dt(value: Any) -> datetime:
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _m15_bars(price_m1: pd.DataFrame) -> tuple[Bar, ...]:
    frame = _resample_ohlc(price_m1, "15min")
    return _bars_from_frame(frame, "M15")


def _eligible_episode(row: Any, *, year: int) -> bool:
    return bool(
        str(row.timeframe).upper() == "H1"
        and str(row.direction).upper() == "LONG"
        and str(row.nesting_bucket) == "MULTI_HTF_NESTING"
        and str(row.approach_state) == "AGGRESSIVE_APPROACH"
        and ensure_utc(row.touch_at).year == int(year)
    )


def _entry_level(zone: SDZone, slot: str) -> float:
    if slot == "PROXIMAL":
        return float(zone.proximal)
    if slot == "MID":
        return (float(zone.low) + float(zone.high)) / 2.0
    raise ValueError(f"V235_UNKNOWN_ENTRY_SLOT:{slot}")


def _m1_bounds(
    timestamps: Sequence[pd.Timestamp],
    *,
    start: datetime,
    end: datetime,
) -> tuple[int, int]:
    left = bisect_left(timestamps, pd.Timestamp(start))
    right = bisect_left(timestamps, pd.Timestamp(end))
    return left, right


def _first_fill(
    price_m1: pd.DataFrame,
    timestamps: Sequence[pd.Timestamp],
    *,
    start: datetime,
    end: datetime,
    entry: float,
) -> tuple[int, pd.Series] | None:
    left, right = _m1_bounds(timestamps, start=start, end=end)
    if right <= left:
        return None
    window = price_m1.iloc[left:right]
    mask = (
        (window["low"].to_numpy(dtype=float, copy=False) <= float(entry))
        & (window["high"].to_numpy(dtype=float, copy=False) >= float(entry))
    )
    indexes = mask.nonzero()[0]
    if len(indexes) == 0:
        return None
    absolute = left + int(indexes[0])
    return absolute, price_m1.iloc[absolute]


def _simulate_order(
    price_m1: pd.DataFrame,
    timestamps: Sequence[pd.Timestamp],
    *,
    touch_at: datetime,
    entry: float,
    stop: float,
    target: float,
) -> dict[str, Any] | None:
    fill = _first_fill(
        price_m1,
        timestamps,
        start=touch_at,
        end=touch_at + timedelta(minutes=ENTRY_WINDOW_MINUTES),
        entry=entry,
    )
    if fill is None:
        return None
    fill_index, fill_row = fill
    fill_at = ensure_utc(pd.Timestamp(fill_row["timestamp"]).to_pydatetime())
    horizon_at = touch_at + timedelta(hours=MAX_HOLD_HOURS)

    # Conservative entry-M1 semantics: SL can count immediately; TP cannot.
    if float(fill_row["low"]) <= float(stop):
        return {
            "fill_at": fill_at.isoformat(),
            "fill_m5_bucket": pd.Timestamp(fill_at).floor("5min").isoformat(),
            "exit_at": fill_at.isoformat(),
            "exit_reason": "SL_ENTRY_BAR_CONSERVATIVE",
            "exit_price": float(stop),
            "gross_points": float(stop) - float(entry),
        }

    end = bisect_right(timestamps, pd.Timestamp(horizon_at))
    future = price_m1.iloc[fill_index + 1 : end]
    for _, row in future.iterrows():
        ts = ensure_utc(pd.Timestamp(row["timestamp"]).to_pydatetime())
        sl_hit = float(row["low"]) <= float(stop)
        tp_hit = float(row["high"]) >= float(target)
        # SL wins same-M1 ambiguity.
        if sl_hit:
            return {
                "fill_at": fill_at.isoformat(),
                "fill_m5_bucket": pd.Timestamp(fill_at).floor("5min").isoformat(),
                "exit_at": ts.isoformat(),
                "exit_reason": "SL",
                "exit_price": float(stop),
                "gross_points": float(stop) - float(entry),
            }
        if tp_hit:
            return {
                "fill_at": fill_at.isoformat(),
                "fill_m5_bucket": pd.Timestamp(fill_at).floor("5min").isoformat(),
                "exit_at": ts.isoformat(),
                "exit_reason": "TP",
                "exit_price": float(target),
                "gross_points": float(target) - float(entry),
            }

    if future.empty:
        return None
    last = future.iloc[-1]
    exit_price = float(last["close"])
    exit_at = ensure_utc(pd.Timestamp(last["timestamp"]).to_pydatetime())
    return {
        "fill_at": fill_at.isoformat(),
        "fill_m5_bucket": pd.Timestamp(fill_at).floor("5min").isoformat(),
        "exit_at": exit_at.isoformat(),
        "exit_reason": "TIME_EXIT_4H",
        "exit_price": exit_price,
        "gross_points": exit_price - float(entry),
    }


def replay_year(*, year: int, price_csv: str) -> dict[str, Any]:
    price_m1 = _load_price_frame(price_csv)
    m15 = _m15_bars(price_m1)
    if not m15:
        raise RuntimeError("V235_M15_EMPTY")

    _, episodes = build_reaction_dataset(m15)
    as_of = ensure_utc(m15[-1].timestamp) + timedelta(minutes=15)
    zones = _all_zones(m15, as_of=as_of)
    zones_by_id = {zone.zone_id: zone for zone in zones}
    m1_ts = tuple(pd.Timestamp(value) for value in price_m1["timestamp"])

    selected = [row for row in episodes if _eligible_episode(row, year=year)]
    orders: list[dict[str, Any]] = []
    diagnostics = {
        "all_reaction_episodes": len(episodes),
        "eligible_h1_long_multi_htf_aggressive": len(selected),
        "zone_missing": 0,
        "not_filled": 0,
        "invalid_geometry": 0,
    }

    for episode in selected:
        zone = zones_by_id.get(str(episode.zone_id))
        if zone is None:
            diagnostics["zone_missing"] += 1
            continue
        touch_at = ensure_utc(episode.touch_at)
        stop = float(zone.distal) - STOP_BUFFER_ATR * float(zone.atr_points)
        if stop <= 0:
            diagnostics["invalid_geometry"] += 1
            continue

        episode_key = "|".join(
            (
                str(zone.zone_id),
                touch_at.isoformat(),
                str(int(episode.touch_ordinal)),
            )
        )
        for slot in ENTRY_SLOTS:
            entry = _entry_level(zone, slot)
            if entry <= stop:
                diagnostics["invalid_geometry"] += 1
                continue
            risk_points = entry - stop
            for target_atr in TARGET_ATR_RUNGS:
                # V183/V185 HOLD is measured beyond the demand proximal edge.
                target = float(zone.proximal) + float(target_atr) * float(zone.atr_points)
                if target <= entry:
                    diagnostics["invalid_geometry"] += 1
                    continue
                outcome = _simulate_order(
                    price_m1,
                    m1_ts,
                    touch_at=touch_at,
                    entry=entry,
                    stop=stop,
                    target=target,
                )
                if outcome is None:
                    diagnostics["not_filled"] += 1
                    continue
                reward_points = target - entry
                variant_id = (
                    f"V235_{slot}_T{int(round(target_atr * 100)):03d}"
                )
                orders.append(
                    {
                        "episode_key": episode_key,
                        "year": int(year),
                        "variant_id": variant_id,
                        "slot": slot,
                        "target_atr": float(target_atr),
                        "direction": "LONG",
                        "zone_id": str(zone.zone_id),
                        "zone_timeframe": str(zone.timeframe),
                        "zone_class": str(zone.zone_class),
                        "zone_pattern": str(zone.pattern),
                        "touch_ordinal": int(episode.touch_ordinal),
                        "touch_at": touch_at.isoformat(),
                        "approach_state": str(episode.approach_state),
                        "nesting_bucket": str(episode.nesting_bucket),
                        "htf_nesting_count": int(episode.htf_nesting_count),
                        "entry": float(entry),
                        "sl": float(stop),
                        "tp": float(target),
                        "risk_points": float(risk_points),
                        "reward_points": float(reward_points),
                        "rr": float(reward_points / risk_points),
                        "atr_points": float(zone.atr_points),
                        "margin_usd_1_to_100": (
                            float(entry) * OUNCES_PER_001_LOT / LEVERAGE
                        ),
                        "lot": LOT,
                        "ounces": OUNCES_PER_001_LOT,
                        **outcome,
                        "gross_pnl_usd": (
                            float(outcome["gross_points"]) * OUNCES_PER_001_LOT
                        ),
                    }
                )

    orders.sort(
        key=lambda row: (
            _dt(row["fill_at"]),
            row["episode_key"],
            row["variant_id"],
        )
    )
    return {
        "artifact_contract": YEAR_ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "year": int(year),
        "price_rows": int(len(price_m1)),
        "price_start": price_m1["timestamp"].iloc[0].isoformat(),
        "price_end": price_m1["timestamp"].iloc[-1].isoformat(),
        "hypothesis": {
            "source": "V185_HOLDOUT_DISCOVERED_SUBGROUP",
            "timeframe": "H1",
            "direction": "LONG",
            "nesting_bucket": "MULTI_HTF_NESTING",
            "approach_state": "AGGRESSIVE_APPROACH",
            "historical_v185_holdout_n": 30,
            "historical_v185_holdout_hold_precision": 0.8333333333333334,
            "historical_v185_wilson_lower_95": 0.6643564949358397,
            "warning": (
                "The subgroup was discovered on later 2022-2026 cTrader history. "
                "This 2012-2026 replay is retrospective stability/falsification, "
                "not pristine unseen OOS evidence."
            ),
        },
        "execution_contract": {
            "H4_D1": "AT_LEAST_TWO_ACTIVE_SAME_DIRECTION_PARENT_ZONES",
            "H1": "LONG_DEMAND_SOURCE",
            "M15": "V182_V185_AGGRESSIVE_APPROACH_FROM_PRIOR_12_COMPLETED_M15",
            "M5": "RESTING_LIMIT_EXECUTION_BUCKET_NO_MSS_RECLAIM_GATE",
            "entry_slots": list(ENTRY_SLOTS),
            "entry_window_minutes": ENTRY_WINDOW_MINUTES,
            "stop": "H1_DISTAL_MINUS_0_15_ATR",
            "target_atr_rungs": list(TARGET_ATR_RUNGS),
            "max_hold_hours": MAX_HOLD_HOURS,
            "risk_percent_filter": None,
            "fixed_lot_reference": LOT,
            "leverage": LEVERAGE,
        },
        "orders": orders,
        "order_count": len(orders),
        "diagnostics": diagnostics,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    year = int(os.environ["XAU_V235_YEAR"])
    result = replay_year(
        year=year,
        price_csv=os.environ["XAU_V235_PRICE_CSV"],
    )
    output = Path(
        os.environ.get(
            "XAU_V235_OUTPUT",
            f"artifacts/xau-h1-nested-aggressive-reversal-v235-{year}.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_V235_YEAR "
        f"year={year} eligible={result['diagnostics']['eligible_h1_long_multi_htf_aggressive']} "
        f"orders={result['order_count']} authority=SHADOW_ONLY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
