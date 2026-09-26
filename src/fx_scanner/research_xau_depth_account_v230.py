from __future__ import annotations

import json
import os
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .demo_xau_supply_demand_atlas_v182 import evaluate_supply_demand_atlas
from .demo_xau_v226_rizan_depth_map import build_depth_map
from .demo_xau_v229_depth_execution import build_execution_plan
from .models import Bar, ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    _bars_from_frame,
    _load_price_frame,
    _resample_ohlc,
)
from .storage.supabase_operational import SupabaseOperationalStore

RESEARCH_VERSION = "XAU_DEPTH_ACCOUNT_REPLAY_V230_1"
YEAR_ARTIFACT_CONTRACT = "XAU_DEPTH_ACCOUNT_REPLAY_V230_YEAR_1"
PRIOR_WORKER = "research_xau_zone_reversal_depth_v225"

SYMBOL = "XAUUSD"
LOT = 0.01
OUNCES_PER_001_LOT = 1.0
LEVERAGE = 100.0
MAX_HOLD_HOURS = 16.0
MIN_RR = 1.0
ATLAS_LOOKBACK_DAYS = 75
MAX_ORDERS_PER_CANDIDATE = 2


def _dt(value: Any) -> datetime:
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _latest_v225_prior(store: SupabaseOperationalStore) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", PRIOR_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        raise RuntimeError("V230_V225_PRIOR_MISSING")
    row = dict(rows[0])
    if not bool(row.get("healthy")):
        raise RuntimeError("V230_V225_PRIOR_UNHEALTHY")
    details = dict(row.get("details") or {})
    if str(details.get("research_version") or "") != "XAU_ZONE_REVERSAL_DEPTH_V225_2":
        raise RuntimeError("V230_V225_PRIOR_VERSION_MISMATCH")
    if int(details.get("year_count") or 0) < 15:
        raise RuntimeError("V230_V225_PRIOR_INCOMPLETE")
    return details


def _load_year_h4_episodes(path: str, year: int) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text())
    if int(payload.get("year") or 0) != int(year):
        raise RuntimeError("V230_YEAR_SHARD_MISMATCH")
    if str(payload.get("research_version") or "") != "XAU_ZONE_REVERSAL_DEPTH_V225_2":
        raise RuntimeError("V230_YEAR_SHARD_VERSION_MISMATCH")
    rows = [
        dict(row)
        for row in list(payload.get("episodes") or [])
        if str(row.get("timeframe") or "").upper() == "H4"
        and _dt(row.get("touch_at")).year == int(year)
    ]
    rows.sort(key=lambda row: (_dt(row.get("touch_at")), str(row.get("zone_id") or "")))
    return rows


def _m15_bars(price_m1: pd.DataFrame) -> tuple[Bar, ...]:
    frame = _resample_ohlc(price_m1, "15min")
    return _bars_from_frame(frame, "M15")


def _bar_window(
    bars: Sequence[Bar],
    timestamps: Sequence[datetime],
    *,
    as_of: datetime,
) -> tuple[Bar, ...]:
    start_at = as_of - timedelta(days=ATLAS_LOOKBACK_DAYS)
    left = bisect_left(timestamps, start_at)
    right = bisect_right(timestamps, as_of)
    return tuple(bars[left:right])


def _m1_window(
    frame: pd.DataFrame,
    timestamps: Sequence[pd.Timestamp],
    *,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    left = bisect_left(timestamps, pd.Timestamp(start))
    right = bisect_right(timestamps, pd.Timestamp(end))
    return frame.iloc[left:right]


def _entry_levels(candidate: dict[str, Any], direction: str) -> list[tuple[str, float]]:
    low = float(candidate["entry_low"])
    high = float(candidate["entry_high"])
    reference = float(candidate["entry_reference"])
    near = high if direction == "LONG" else low
    levels: list[tuple[str, float]] = [("NEAR_EDGE", near)]
    if abs(reference - near) > 1e-9:
        levels.append(("REFERENCE", reference))
    return levels[:MAX_ORDERS_PER_CANDIDATE]


def _first_fill_index(
    window: pd.DataFrame,
    entry: float,
) -> int | None:
    if window.empty:
        return None
    low = window["low"].to_numpy(dtype=float, copy=False)
    high = window["high"].to_numpy(dtype=float, copy=False)
    mask = (low <= float(entry)) & (high >= float(entry))
    indexes = mask.nonzero()[0]
    return None if len(indexes) == 0 else int(indexes[0])


def _simulate_order(
    price_m1: pd.DataFrame,
    timestamps: Sequence[pd.Timestamp],
    *,
    map_at: datetime,
    horizon_at: datetime,
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> dict[str, Any] | None:
    window = _m1_window(
        price_m1,
        timestamps,
        start=map_at,
        end=horizon_at,
    )
    fill_rel = _first_fill_index(window, entry)
    if fill_rel is None:
        return None

    fill_row = window.iloc[fill_rel]
    fill_at = ensure_utc(pd.Timestamp(fill_row["timestamp"]).to_pydatetime())

    # Entry-bar ambiguity is handled conservatively: an adverse SL hit can
    # count immediately, while a TP on the same entry bar is not credited.
    if direction == "LONG":
        entry_bar_stop = float(fill_row["low"]) <= float(stop)
    else:
        entry_bar_stop = float(fill_row["high"]) >= float(stop)
    if entry_bar_stop:
        pnl_points = (
            float(stop) - float(entry)
            if direction == "LONG"
            else float(entry) - float(stop)
        )
        return {
            "fill_at": fill_at.isoformat(),
            "exit_at": fill_at.isoformat(),
            "exit_reason": "SL_ENTRY_BAR_CONSERVATIVE",
            "exit_price": float(stop),
            "gross_points": pnl_points,
        }

    future = window.iloc[fill_rel + 1 :]
    for _, row in future.iterrows():
        ts = ensure_utc(pd.Timestamp(row["timestamp"]).to_pydatetime())
        high = float(row["high"])
        low = float(row["low"])
        if direction == "LONG":
            sl_hit = low <= float(stop)
            tp_hit = high >= float(target)
        else:
            sl_hit = high >= float(stop)
            tp_hit = low <= float(target)

        # Conservative same-M1 precedence: SL wins when both were touched.
        if sl_hit:
            pnl_points = (
                float(stop) - float(entry)
                if direction == "LONG"
                else float(entry) - float(stop)
            )
            return {
                "fill_at": fill_at.isoformat(),
                "exit_at": ts.isoformat(),
                "exit_reason": "SL",
                "exit_price": float(stop),
                "gross_points": pnl_points,
            }
        if tp_hit:
            pnl_points = (
                float(target) - float(entry)
                if direction == "LONG"
                else float(entry) - float(target)
            )
            return {
                "fill_at": fill_at.isoformat(),
                "exit_at": ts.isoformat(),
                "exit_reason": "TP",
                "exit_price": float(target),
                "gross_points": pnl_points,
            }

    if window.empty:
        return None
    last = window.iloc[-1]
    exit_price = float(last["close"])
    exit_at = ensure_utc(pd.Timestamp(last["timestamp"]).to_pydatetime())
    pnl_points = (
        exit_price - float(entry)
        if direction == "LONG"
        else float(entry) - exit_price
    )
    return {
        "fill_at": fill_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "exit_reason": "TIME_EXIT_16H",
        "exit_price": exit_price,
        "gross_points": pnl_points,
    }


def replay_year(
    *,
    year: int,
    price_csv: str,
    v225_year_json: str,
    prior: dict[str, Any],
) -> dict[str, Any]:
    price_m1 = _load_price_frame(price_csv)
    m15 = _m15_bars(price_m1)
    m15_ts = tuple(ensure_utc(row.timestamp) for row in m15)
    m1_ts = tuple(pd.Timestamp(value) for value in price_m1["timestamp"])
    episodes = _load_year_h4_episodes(v225_year_json, year)

    candidates_seen: set[str] = set()
    orders: list[dict[str, Any]] = []
    diagnostics = {
        "h4_episodes": len(episodes),
        "atlas_unavailable": 0,
        "focus_mismatch": 0,
        "parent_mismatch": 0,
        "no_fresh_candidate": 0,
        "duplicate_candidate": 0,
        "no_valid_rr_plan": 0,
        "not_filled": 0,
    }

    for episode in episodes:
        map_at = _dt(episode["touch_at"])
        bars = _bar_window(m15, m15_ts, as_of=map_at)
        atlas = evaluate_supply_demand_atlas(
            bars,
            as_of=map_at,
            strategic_bias="NEUTRAL",
        )
        if str(atlas.get("state") or "") != "ATLAS_AVAILABLE":
            diagnostics["atlas_unavailable"] += 1
            continue

        depth_map = build_depth_map(
            atlas_evaluation=atlas,
            history_details=prior,
        )
        direction = str(episode.get("direction") or "").upper()
        if str(depth_map.get("focus_direction") or "").upper() != direction:
            diagnostics["focus_mismatch"] += 1
            continue

        side_map = dict(depth_map.get(direction.lower()) or {})
        parent = dict(dict(side_map.get("h4") or {}).get("zone") or {})
        if str(parent.get("zone_id") or "") != str(episode.get("zone_id") or ""):
            diagnostics["parent_mismatch"] += 1
            continue

        candidate = dict(depth_map.get("depth_entry_candidate") or {})
        if not bool(candidate.get("calibrated_fresh_first_touch")):
            diagnostics["no_fresh_candidate"] += 1
            continue

        key = "|".join(
            (
                direction,
                str(parent.get("zone_id") or ""),
                str(candidate.get("source_layer") or ""),
                f"{float(candidate.get('entry_low')):.5f}",
                f"{float(candidate.get('entry_high')):.5f}",
            )
        )
        if key in candidates_seen:
            diagnostics["duplicate_candidate"] += 1
            continue
        candidates_seen.add(key)

        horizon_at = map_at + timedelta(hours=MAX_HOLD_HOURS)
        for slot, entry in _entry_levels(candidate, direction):
            plan = build_execution_plan(
                v226_evaluation=depth_map,
                atlas_evaluation=atlas,
                live_price=float(entry),
                min_rr=MIN_RR,
            )
            if plan is None:
                diagnostics["no_valid_rr_plan"] += 1
                continue

            outcome = _simulate_order(
                price_m1,
                m1_ts,
                map_at=map_at,
                horizon_at=horizon_at,
                direction=direction,
                entry=float(entry),
                stop=float(plan["sl"]),
                target=float(plan["tp2"]),
            )
            if outcome is None:
                diagnostics["not_filled"] += 1
                continue

            risk_points = abs(float(entry) - float(plan["sl"]))
            reward_points = abs(float(plan["tp2"]) - float(entry))
            orders.append(
                {
                    "candidate_key": key,
                    "year": int(year),
                    "map_at": map_at.isoformat(),
                    "direction": direction,
                    "slot": slot,
                    "source_layer": str(candidate.get("source_layer") or ""),
                    "parent_h4_zone_id": str(parent.get("zone_id") or ""),
                    "candidate_low": float(candidate["entry_low"]),
                    "candidate_high": float(candidate["entry_high"]),
                    "entry_reference": float(candidate["entry_reference"]),
                    "entry": float(entry),
                    "sl": float(plan["sl"]),
                    "tp": float(plan["tp2"]),
                    "target_source": str(plan.get("target_source") or ""),
                    "rr": reward_points / max(risk_points, 1e-12),
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

    orders.sort(key=lambda row: (_dt(row["fill_at"]), row["candidate_key"], row["slot"]))
    return {
        "artifact_contract": YEAR_ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "year": int(year),
        "price_rows": int(len(price_m1)),
        "price_start": price_m1["timestamp"].iloc[0].isoformat(),
        "price_end": price_m1["timestamp"].iloc[-1].isoformat(),
        "lot_per_order": LOT,
        "ounces_per_order": OUNCES_PER_001_LOT,
        "leverage": LEVERAGE,
        "risk_percent_filter": None,
        "max_orders_per_candidate": MAX_ORDERS_PER_CANDIDATE,
        "min_rr_gate": MIN_RR,
        "max_hold_hours": MAX_HOLD_HOURS,
        "orders": orders,
        "order_count": len(orders),
        "diagnostics": diagnostics,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "Historical research replay only. Risk-percent sizing/filter is removed. "
            "Each eligible order is fixed at 0.01 lot (1 oz assumption), with up to "
            "two entries per fresh candidate. Margin is applied later in the account "
            "aggregator; SL/TP geometry follows V229 and the path target is frozen at "
            "the causal H4 first-touch mapping time."
        ),
    }


def run() -> int:
    year = int(os.environ["XAU_V230_YEAR"])
    price_csv = os.environ["XAU_V230_PRICE_CSV"]
    v225_year_json = os.environ["XAU_V230_V225_YEAR_JSON"]
    output = os.environ.get(
        "XAU_V230_OUTPUT",
        f"artifacts/xau-depth-account-v230-{year}.json",
    )

    store = SupabaseOperationalStore.from_env()
    prior = _latest_v225_prior(store)
    result = replay_year(
        year=year,
        price_csv=price_csv,
        v225_year_json=v225_year_json,
        prior=prior,
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(
        "XAU_V230_YEAR "
        f"year={year} h4={result['diagnostics']['h4_episodes']} "
        f"orders={result['order_count']} output={path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
