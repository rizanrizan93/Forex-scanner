from __future__ import annotations

"""V387 research-only execution/PnL replay for the frozen adaptive C4 champion.

The adaptive path configuration is already frozen as M15_LB12_B020 from 2025.
This stage does not re-optimize C4. It consumes V386/V384 adaptive artifacts,
re-evaluates only TARGET_TOUCH episodes at the first *completed* M15 boundary
strictly after touch, and admits a trade only when the canonical engine still
recognizes the touched parent/refinement, has M5/M15 reversal guidance, valid
structural invalidation, an opposing HTF destination, and >=1.50R after the
fixed research cost model.

Execution is research-only. LIVE authority is always false.
"""

import argparse
import glob
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from fx_scanner.models import ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import load_price_frame
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity
from xau_v384_adaptive_c4_reforecast_cached import (
    _bar_cache,
    _completed_bars,
    _price_before,
)

SCHEMA = "XAU_V387_EXECUTION_PNL_REPLAY_V1"
ADAPTIVE_CONFIG = "M15_LB12_B020"
MIN_RR_AFTER_COST = 1.50
MAX_HOLD_HOURS = 24.0 * 30.0
MAX_OPEN_POSITIONS = 10
LOT = 0.01
CONTRACT_SIZE_OZ_PER_LOT = 100.0
# Fixed research assumptions, not a claim about current broker quotes.
SPREAD_USD = 0.30
SLIPPAGE_USD_PER_SIDE = 0.05
COMMISSION_USD_PER_LOT_ROUNDTRIP = 7.0
ALLOWED_GUIDE_STATES = {"CONFIRMED_GUIDANCE", "EARLY_CONFIRMED_GUIDANCE"}


def _dt(value: Any) -> datetime:
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _opposite(direction: str) -> str:
    return "SHORT" if direction == "LONG" else "LONG" if direction == "SHORT" else "WAIT"


def _load_adaptive(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in list(payload.get("configs") or []):
        if str(row.get("config")) == ADAPTIVE_CONFIG:
            episodes = [
                dict(x)
                for x in list(row.get("episodes") or [])
                if str(x.get("resolution")) == "TARGET_TOUCH"
            ]
            episodes.sort(key=lambda x: str(x.get("resolved_at") or ""))
            return payload, episodes
    raise RuntimeError(f"Adaptive config {ADAPTIVE_CONFIG} not found in {path}")


def _price_arrays(price: pd.DataFrame) -> dict[str, Any]:
    return {
        "timestamps": [ensure_utc(pd.Timestamp(x).to_pydatetime()) for x in price["timestamp"]],
        "open": price["open"].to_numpy(dtype=float, copy=False),
        "high": price["high"].to_numpy(dtype=float, copy=False),
        "low": price["low"].to_numpy(dtype=float, copy=False),
        "close": price["close"].to_numpy(dtype=float, copy=False),
    }


def _next_m15_completion(completed: list[datetime], touch_at: datetime) -> datetime | None:
    idx = bisect_right(completed, ensure_utc(touch_at))
    return None if idx >= len(completed) else ensure_utc(completed[idx])


def _find_entry_index(timestamps: list[datetime], at: datetime) -> int | None:
    idx = bisect_left(timestamps, ensure_utc(at))
    return None if idx >= len(timestamps) else idx


def _simulate_trade(
    *,
    arrays: dict[str, Any],
    entry_idx: int,
    direction: str,
    stop_mid: float,
    target_mid: float,
) -> dict[str, Any] | None:
    sign = 1.0 if direction == "LONG" else -1.0
    entry_at = arrays["timestamps"][entry_idx]
    entry_mid = float(arrays["open"][entry_idx])
    per_side = SPREAD_USD / 2.0 + SLIPPAGE_USD_PER_SIDE
    commission_points = COMMISSION_USD_PER_LOT_ROUNDTRIP / CONTRACT_SIZE_OZ_PER_LOT
    entry_fill = entry_mid + sign * per_side
    stop_fill = stop_mid - sign * per_side
    target_fill = target_mid - sign * per_side

    stop_pnl_before_commission = sign * (stop_fill - entry_fill)
    target_pnl_before_commission = sign * (target_fill - entry_fill)
    risk_net = -(stop_pnl_before_commission - commission_points)
    reward_net = target_pnl_before_commission - commission_points
    if risk_net <= 1e-9 or reward_net <= 0:
        return None
    rr_after_cost = reward_net / risk_net
    if rr_after_cost < MIN_RR_AFTER_COST:
        return {
            "rejected": True,
            "reject_reason": "RR_AFTER_COST_LT_1P50",
            "rr_after_cost": rr_after_cost,
            "entry_at": entry_at.isoformat(),
        }

    # Geometry must place the stop behind entry and target ahead.
    if direction == "LONG" and not (stop_mid < entry_mid < target_mid):
        return None
    if direction == "SHORT" and not (target_mid < entry_mid < stop_mid):
        return None

    end_at = entry_at + timedelta(hours=MAX_HOLD_HOURS)
    end_idx = bisect_right(arrays["timestamps"], end_at)
    end_idx = min(end_idx, len(arrays["timestamps"]))
    if end_idx <= entry_idx:
        return None

    min_low = float("inf")
    max_high = float("-inf")
    exit_idx = end_idx - 1
    exit_reason = "TIMEOUT"
    exit_mid = float(arrays["close"][exit_idx])

    for i in range(entry_idx, end_idx):
        lo = float(arrays["low"][i])
        hi = float(arrays["high"][i])
        min_low = min(min_low, lo)
        max_high = max(max_high, hi)
        if direction == "LONG":
            stop_hit = lo <= stop_mid
            target_hit = hi >= target_mid
        else:
            stop_hit = hi >= stop_mid
            target_hit = lo <= target_mid
        # STOP_FIRST is deliberately conservative when both occur in one M1 bar.
        if stop_hit:
            exit_idx = i
            exit_reason = "SL"
            exit_mid = stop_mid
            break
        if target_hit:
            exit_idx = i
            exit_reason = "TP_OPPOSING_HTF"
            exit_mid = target_mid
            break

    exit_fill = exit_mid - sign * per_side
    net_points = sign * (exit_fill - entry_fill) - commission_points
    r_multiple = net_points / risk_net

    if direction == "LONG":
        adverse_points = max(0.0, entry_fill - min_low)
        favorable_points = max(0.0, max_high - entry_fill)
    else:
        adverse_points = max(0.0, max_high - entry_fill)
        favorable_points = max(0.0, entry_fill - min_low)

    exit_at = arrays["timestamps"][exit_idx]
    ounces = LOT * CONTRACT_SIZE_OZ_PER_LOT
    return {
        "rejected": False,
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "direction": direction,
        "entry_mid": entry_mid,
        "entry_fill": entry_fill,
        "stop_mid": stop_mid,
        "target_mid": target_mid,
        "exit_mid": exit_mid,
        "exit_fill": exit_fill,
        "exit_reason": exit_reason,
        "risk_net_points": risk_net,
        "reward_net_points": reward_net,
        "rr_after_cost": rr_after_cost,
        "net_points": net_points,
        "r_multiple": r_multiple,
        "mae_r": adverse_points / risk_net,
        "mfe_r": favorable_points / risk_net,
        "duration_hours": max(0.0, (exit_at - entry_at).total_seconds() / 3600.0),
        "pnl_usd_0p01_lot_assumption": net_points * ounces,
    }


def run_shard(
    *,
    year: int,
    adaptive_json: Path,
    csv_path: Path,
    shard_index: int,
    shard_count: int,
    output: Path,
) -> dict[str, Any]:
    adaptive_payload, touches = _load_adaptive(adaptive_json)
    price = load_price_frame(csv_path)
    arrays = _price_arrays(price)
    bars, completed, _frames = _bar_cache(price)

    selected = [row for i, row in enumerate(touches) if i % shard_count == shard_index]
    skips: Counter[str] = Counter()
    trades: list[dict[str, Any]] = []
    rejected_rr: list[dict[str, Any]] = []

    for pos, episode in enumerate(selected, start=1):
        touch_at = _dt(episode["resolved_at"])
        confirm_at = _next_m15_completion(completed["M15"], touch_at)
        if confirm_at is None:
            skips["NO_NEXT_M15_COMPLETION"] += 1
            continue

        px = _price_before(arrays, confirm_at)
        if px is None:
            skips["NO_CAUSAL_PRICE"] += 1
            continue
        h1 = _completed_bars(bars, completed, "H1", confirm_at)
        h4 = _completed_bars(bars, completed, "H4", confirm_at)
        m15 = _completed_bars(bars, completed, "M15", confirm_at)
        m5 = _completed_bars(bars, completed, "M5", confirm_at)
        if len(h1) < 80 or len(h4) < 40 or len(m15) < 32 or len(m5) < 32:
            skips["INSUFFICIENT_BARS"] += 1
            continue

        result = evaluate_sd_liquidity(
            bars_h1=h1,
            bars_h4=h4,
            bars_m15=m15,
            bars_m5=m5,
            as_of=confirm_at,
            price_now=float(px),
        )
        original_zone = str(
            episode.get("final_target_zone_id") or episode.get("target_zone_id") or ""
        )
        recognized_ids = {
            str(dict(result.get(key) or {}).get("zone_id") or "")
            for key in ("main_reversal_zone", "decision_zone", "refinement_zone", "confirmation_zone")
        }
        if not original_zone or original_zone not in recognized_ids:
            skips["TOUCHED_ZONE_NO_LONGER_RECOGNIZED"] += 1
            continue

        guide = dict(result.get("entry_guide") or {})
        guide_state = str(guide.get("state") or "")
        if guide_state not in ALLOWED_GUIDE_STATES:
            skips[f"GUIDE_{guide_state or 'EMPTY'}"] += 1
            continue

        leg_direction = str(episode.get("final_direction") or episode.get("direction") or "").upper()
        expected_reversal = _opposite(leg_direction)
        direction = str(guide.get("direction") or "").upper()
        if direction != expected_reversal:
            skips["REVERSAL_DIRECTION_MISMATCH"] += 1
            continue

        stop_mid = _f(guide.get("invalidation"))
        destination = dict(result.get("structural_destination") or {})
        target_mid = _f(destination.get("price"))
        if stop_mid is None:
            skips["NO_STRUCTURAL_SL"] += 1
            continue
        if target_mid is None:
            skips["NO_OPPOSING_HTF_DESTINATION"] += 1
            continue

        entry_idx = _find_entry_index(arrays["timestamps"], confirm_at)
        if entry_idx is None:
            skips["NO_ENTRY_BAR"] += 1
            continue
        simulated = _simulate_trade(
            arrays=arrays,
            entry_idx=entry_idx,
            direction=direction,
            stop_mid=float(stop_mid),
            target_mid=float(target_mid),
        )
        if simulated is None:
            skips["INVALID_EXECUTION_GEOMETRY"] += 1
            continue
        if simulated.get("rejected"):
            skips[str(simulated.get("reject_reason") or "REJECTED")] += 1
            rejected_rr.append(
                {
                    "episode_index": episode.get("index"),
                    "touch_at": touch_at.isoformat(),
                    "confirmation_at": confirm_at.isoformat(),
                    "rr_after_cost": simulated.get("rr_after_cost"),
                }
            )
            continue

        simulated.update(
            {
                "episode_index": episode.get("index"),
                "touch_at": touch_at.isoformat(),
                "confirmation_at": confirm_at.isoformat(),
                "original_target_zone_id": original_zone,
                "execution_zone_id": str(dict(result.get("decision_zone") or {}).get("zone_id") or ""),
                "guide_state": guide_state,
                "target_timeframe": destination.get("timeframe"),
                "target_zone_id": destination.get("zone_id"),
                "tp1": (list(guide.get("targets") or [{}])[0] or {}).get("price"),
            }
        )
        trades.append(simulated)

        if pos % 25 == 0 or pos == len(selected):
            pct = 100.0 * pos / max(1, len(selected))
            print(
                f"V387_PROGRESS year={year} shard={shard_index+1}/{shard_count} "
                f"processed={pos}/{len(selected)} pct={pct:.1f} candidates={len(trades)} "
                f"skips={sum(skips.values())}",
                flush=True,
            )

    payload = {
        "schema": SCHEMA,
        "mode": "SHARD",
        "year": year,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "adaptive_config": ADAPTIVE_CONFIG,
        "adaptive_schema": adaptive_payload.get("schema"),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "total_target_touches": len(touches),
        "shard_target_touches": len(selected),
        "candidate_trades": trades,
        "candidate_count": len(trades),
        "rejected_rr": rejected_rr,
        "skip_counts": dict(skips),
        "research_cost_model": {
            "spread_usd": SPREAD_USD,
            "slippage_usd_per_side": SLIPPAGE_USD_PER_SIDE,
            "commission_usd_per_lot_roundtrip": COMMISSION_USD_PER_LOT_ROUNDTRIP,
            "lot": LOT,
            "contract_size_oz_per_lot_assumption": CONTRACT_SIZE_OZ_PER_LOT,
            "min_rr_after_cost": MIN_RR_AFTER_COST,
        },
        "execution_authority": False,
        "live_execution_enabled": False,
        "news_gate": "NOT_APPLIED_NO_CAUSAL_HISTORICAL_CALENDAR_IN_V387",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V387_SHARD_SUMMARY=" + json.dumps({
        "year": year,
        "shard": f"{shard_index+1}/{shard_count}",
        "touches": len(selected),
        "candidates": len(trades),
        "skips": dict(skips),
    }, sort_keys=True), flush=True)
    return payload


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def run_aggregate(*, year: int, inputs: str, output: Path) -> dict[str, Any]:
    files = sorted(Path(p) for p in glob.glob(inputs))
    if not files:
        raise RuntimeError(f"No shard files matched {inputs}")
    candidates: list[dict[str, Any]] = []
    skips: Counter[str] = Counter()
    touch_total = 0
    shard_count = None
    for path in files:
        p = json.loads(path.read_text(encoding="utf-8"))
        if int(p.get("year")) != year or p.get("mode") != "SHARD":
            continue
        candidates.extend(dict(x) for x in list(p.get("candidate_trades") or []))
        skips.update(dict(p.get("skip_counts") or {}))
        touch_total = max(touch_total, int(p.get("total_target_touches") or 0))
        shard_count = p.get("shard_count")

    candidates.sort(key=lambda x: str(x.get("entry_at") or ""))
    accepted: list[dict[str, Any]] = []
    active_exits: list[datetime] = []
    overlap_rejects = 0
    for trade in candidates:
        entry_at = _dt(trade["entry_at"])
        active_exits = [x for x in active_exits if x > entry_at]
        if len(active_exits) >= MAX_OPEN_POSITIONS:
            overlap_rejects += 1
            continue
        accepted.append(trade)
        active_exits.append(_dt(trade["exit_at"]))

    r = [float(x["r_multiple"]) for x in accepted]
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = None if gross_loss <= 1e-12 else gross_profit / gross_loss
    summary = {
        "target_touches": touch_total,
        "candidate_trades_after_engine_and_rr_gates": len(candidates),
        "trades_after_max10_overlap_gate": len(accepted),
        "overlap_rejects": overlap_rejects,
        "trade_frequency_per_year": len(accepted),
        "win_rate": None if not r else len(wins) / len(r),
        "profit_factor_r": pf,
        "expectancy_r": None if not r else sum(r) / len(r),
        "total_r": sum(r),
        "max_drawdown_r": _max_drawdown(r),
        "median_mae_r": None if not accepted else median(float(x["mae_r"]) for x in accepted),
        "median_mfe_r": None if not accepted else median(float(x["mfe_r"]) for x in accepted),
        "median_duration_hours": None if not accepted else median(float(x["duration_hours"]) for x in accepted),
        "net_points": sum(float(x["net_points"]) for x in accepted),
        "pnl_usd_0p01_lot_assumption": sum(float(x["pnl_usd_0p01_lot_assumption"]) for x in accepted),
        "exit_counts": dict(Counter(str(x.get("exit_reason")) for x in accepted)),
        "guide_state_counts": dict(Counter(str(x.get("guide_state")) for x in accepted)),
        "skip_counts": dict(skips),
    }
    payload = {
        "schema": SCHEMA,
        "mode": "AGGREGATE",
        "year": year,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "adaptive_config": ADAPTIVE_CONFIG,
        "execution_policy": "FIRST_COMPLETED_M15_AFTER_TARGET_TOUCH__M5_M15_ENGINE_GUIDANCE__OPPOSING_HTF_TP",
        "summary": summary,
        "trades": accepted,
        "shards_seen": len(files),
        "expected_shards": shard_count,
        "research_cost_model": {
            "spread_usd": SPREAD_USD,
            "slippage_usd_per_side": SLIPPAGE_USD_PER_SIDE,
            "commission_usd_per_lot_roundtrip": COMMISSION_USD_PER_LOT_ROUNDTRIP,
            "lot": LOT,
            "contract_size_oz_per_lot_assumption": CONTRACT_SIZE_OZ_PER_LOT,
            "min_rr_after_cost": MIN_RR_AFTER_COST,
            "same_bar_policy": "STOP_FIRST",
            "max_hold_hours": MAX_HOLD_HOURS,
            "max_open_positions": MAX_OPEN_POSITIONS,
        },
        "execution_authority": False,
        "live_execution_enabled": False,
        "limitations": [
            "HistData M1 OHLC is not broker bid/ask tick data.",
            "Spread/slippage/commission are fixed research assumptions, not current FP Markets quotes.",
            "Historical high-impact news calendar gating is not applied in V387.",
            "Server-side fill behavior inside an M1 bar is approximated; STOP_FIRST is used when ambiguous.",
            "USD PnL assumes 100 oz/lot and 0.01 lot; R metrics are the primary comparison basis.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V387_AGGREGATE_SUMMARY=" + json.dumps({"year": year, **summary}, sort_keys=True), flush=True)
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("shard")
    s.add_argument("--year", type=int, required=True)
    s.add_argument("--adaptive-json", type=Path, required=True)
    s.add_argument("--csv", type=Path, required=True)
    s.add_argument("--shard-index", type=int, required=True)
    s.add_argument("--shard-count", type=int, required=True)
    s.add_argument("--output", type=Path, required=True)

    a = sub.add_parser("aggregate")
    a.add_argument("--year", type=int, required=True)
    a.add_argument("--inputs", required=True)
    a.add_argument("--output", type=Path, required=True)

    args = p.parse_args()
    if args.mode == "shard":
        run_shard(
            year=args.year,
            adaptive_json=args.adaptive_json,
            csv_path=args.csv,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            output=args.output,
        )
    else:
        run_aggregate(year=args.year, inputs=args.inputs, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
