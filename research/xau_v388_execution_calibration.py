from __future__ import annotations

"""V388 execution calibration for the frozen XAU adaptive C4 path engine.

Methodology:
- Adaptive path selector remains frozen as M15_LB12_B020.
- Calibration uses 2025 only. 2026 is not read, downloaded, or used here.
- Four predeclared causal confirmation policies are evaluated:
    C60  = confirmed guidance only, up to 60 minutes after zone touch
    C120 = confirmed guidance only, up to 120 minutes after zone touch
    EC60 = early-or-confirmed guidance, up to 60 minutes after zone touch
    EC120= early-or-confirmed guidance, up to 120 minutes after zone touch
- All policies use the same fixed execution geometry so this stage isolates
  confirmation timing/strictness rather than fitting many dimensions at once.
- Exit policy is fixed staged structural delivery: 50% at the nearest valid
  structural target/roadblock, 50% runner to the opposing HTF destination.
  No break-even move is used. Original structural invalidation remains the SL.
- Same-bar ambiguity is STOP_FIRST. Fixed research costs are inherited from V387.
- 2025 is split into H1/H2 internal calibration/validation. A policy is promotable
  only if both halves have positive expectancy and PF>1 with minimum sample counts.

Execution authority is research-only. LIVE trading is always disabled.
"""

import argparse
import glob
import json
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fx_scanner.models import ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import load_price_frame
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity
from xau_v384_adaptive_c4_reforecast_cached import _bar_cache, _completed_bars, _price_before
from xau_v387_execution_pnl_replay import (
    ADAPTIVE_CONFIG,
    COMMISSION_USD_PER_LOT_ROUNDTRIP,
    CONTRACT_SIZE_OZ_PER_LOT,
    LOT,
    SPREAD_USD,
    SLIPPAGE_USD_PER_SIDE,
    _dt,
    _f,
    _find_entry_index,
    _load_adaptive,
    _opposite,
    _price_arrays,
)

SCHEMA = "XAU_V388_EXECUTION_CALIBRATION_V1"
MAX_OPEN_POSITIONS = 10
MAX_HOLD_HOURS = 72.0
MIN_TERMINAL_RR_AFTER_COST = 1.50
MIN_TP1_R_AFTER_COST = 0.75
TP1_FRACTION = 0.50
TP2_FRACTION = 0.50

POLICIES: dict[str, dict[str, Any]] = {
    "C60": {"window_minutes": 60, "allowed_states": {"CONFIRMED_GUIDANCE"}},
    "C120": {"window_minutes": 120, "allowed_states": {"CONFIRMED_GUIDANCE"}},
    "EC60": {
        "window_minutes": 60,
        "allowed_states": {"EARLY_CONFIRMED_GUIDANCE", "CONFIRMED_GUIDANCE"},
    },
    "EC120": {
        "window_minutes": 120,
        "allowed_states": {"EARLY_CONFIRMED_GUIDANCE", "CONFIRMED_GUIDANCE"},
    },
}


def _cost_geometry(entry_mid: float, direction: str, stop_mid: float, target_mid: float) -> dict[str, float] | None:
    sign = 1.0 if direction == "LONG" else -1.0
    per_side = SPREAD_USD / 2.0 + SLIPPAGE_USD_PER_SIDE
    commission_points = COMMISSION_USD_PER_LOT_ROUNDTRIP / CONTRACT_SIZE_OZ_PER_LOT
    entry_fill = entry_mid + sign * per_side
    stop_fill = stop_mid - sign * per_side
    target_fill = target_mid - sign * per_side
    stop_net = sign * (stop_fill - entry_fill) - commission_points
    target_net = sign * (target_fill - entry_fill) - commission_points
    risk_net = -stop_net
    if risk_net <= 1e-9:
        return None
    return {
        "sign": sign,
        "per_side": per_side,
        "commission_points": commission_points,
        "entry_fill": entry_fill,
        "stop_fill": stop_fill,
        "target_fill": target_fill,
        "stop_net": stop_net,
        "target_net": target_net,
        "risk_net": risk_net,
        "rr": target_net / risk_net,
    }


def _valid_ahead(direction: str, entry_mid: float, price: float) -> bool:
    return price > entry_mid if direction == "LONG" else price < entry_mid


def _pick_tp1(*, result: dict[str, Any], guide: dict[str, Any], direction: str, entry_mid: float, terminal: float) -> tuple[float | None, str | None]:
    candidates: list[tuple[float, float, str]] = []
    for row in list(guide.get("targets") or []):
        px = _f(dict(row or {}).get("price"))
        if px is None or not _valid_ahead(direction, entry_mid, px):
            continue
        before_terminal = px < terminal if direction == "LONG" else px > terminal
        if before_terminal:
            candidates.append((abs(px - entry_mid), px, str(dict(row or {}).get("source") or "GUIDE_TARGET")))

    rb = dict(result.get("nearest_roadblock") or {})
    rb_px = _f(rb.get("near_edge"))
    if rb_px is not None and _valid_ahead(direction, entry_mid, rb_px):
        before_terminal = rb_px < terminal if direction == "LONG" else rb_px > terminal
        if before_terminal:
            candidates.append((abs(rb_px - entry_mid), rb_px, "NEAREST_ROADBLOCK"))

    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    return float(candidates[0][1]), candidates[0][2]


def _simulate_staged(
    *, arrays: dict[str, Any], entry_idx: int, direction: str, stop_mid: float, tp1_mid: float, terminal_mid: float
) -> dict[str, Any] | None:
    entry_at = arrays["timestamps"][entry_idx]
    entry_mid = float(arrays["open"][entry_idx])
    stop_geom = _cost_geometry(entry_mid, direction, stop_mid, stop_mid)
    tp1_geom = _cost_geometry(entry_mid, direction, stop_mid, tp1_mid)
    tp2_geom = _cost_geometry(entry_mid, direction, stop_mid, terminal_mid)
    if stop_geom is None or tp1_geom is None or tp2_geom is None:
        return None
    risk_net = float(stop_geom["risk_net"])
    tp1_r = float(tp1_geom["target_net"]) / risk_net
    tp2_r = float(tp2_geom["target_net"]) / risk_net
    if tp2_r < MIN_TERMINAL_RR_AFTER_COST:
        return {"rejected": True, "reject_reason": "TERMINAL_RR_LT_1P50", "terminal_rr": tp2_r}
    if tp1_r < MIN_TP1_R_AFTER_COST:
        return {"rejected": True, "reject_reason": "TP1_R_LT_0P75", "tp1_r": tp1_r}

    if direction == "LONG" and not (stop_mid < entry_mid < tp1_mid < terminal_mid):
        return None
    if direction == "SHORT" and not (terminal_mid < tp1_mid < entry_mid < stop_mid):
        return None

    sign = 1.0 if direction == "LONG" else -1.0
    per_side = SPREAD_USD / 2.0 + SLIPPAGE_USD_PER_SIDE
    commission_points = COMMISSION_USD_PER_LOT_ROUNDTRIP / CONTRACT_SIZE_OZ_PER_LOT
    entry_fill = entry_mid + sign * per_side
    stop_net = float(stop_geom["stop_net"])
    tp1_net = float(tp1_geom["target_net"])
    tp2_net = float(tp2_geom["target_net"])

    end_at = entry_at + timedelta(hours=MAX_HOLD_HOURS)
    end_idx = min(bisect_right(arrays["timestamps"], end_at), len(arrays["timestamps"]))
    if end_idx <= entry_idx:
        return None

    tp1_hit = False
    tp1_at = None
    min_low = float("inf")
    max_high = float("-inf")
    exit_idx = end_idx - 1
    exit_reason = "TIMEOUT_PRE_TP1"
    total_net = None

    for i in range(entry_idx, end_idx):
        lo = float(arrays["low"][i])
        hi = float(arrays["high"][i])
        min_low = min(min_low, lo)
        max_high = max(max_high, hi)
        if direction == "LONG":
            stop_hit = lo <= stop_mid
            first_hit = hi >= tp1_mid
            terminal_hit = hi >= terminal_mid
        else:
            stop_hit = hi >= stop_mid
            first_hit = lo <= tp1_mid
            terminal_hit = lo <= terminal_mid

        if not tp1_hit:
            if stop_hit:
                exit_idx = i
                exit_reason = "SL_PRE_TP1"
                total_net = stop_net
                break
            if first_hit:
                tp1_hit = True
                tp1_at = arrays["timestamps"][i]
                if terminal_hit:
                    exit_idx = i
                    exit_reason = "TP1_AND_TP2"
                    total_net = TP1_FRACTION * tp1_net + TP2_FRACTION * tp2_net
                    break
        else:
            if stop_hit:
                exit_idx = i
                exit_reason = "TP1_THEN_SL"
                total_net = TP1_FRACTION * tp1_net + TP2_FRACTION * stop_net
                break
            if terminal_hit:
                exit_idx = i
                exit_reason = "TP1_THEN_TP2"
                total_net = TP1_FRACTION * tp1_net + TP2_FRACTION * tp2_net
                break

    if total_net is None:
        exit_mid = float(arrays["close"][exit_idx])
        exit_fill = exit_mid - sign * per_side
        timeout_net = sign * (exit_fill - entry_fill) - commission_points
        if tp1_hit:
            exit_reason = "TP1_THEN_TIMEOUT"
            total_net = TP1_FRACTION * tp1_net + TP2_FRACTION * timeout_net
        else:
            exit_reason = "TIMEOUT_PRE_TP1"
            total_net = timeout_net

    if direction == "LONG":
        adverse_points = max(0.0, entry_fill - min_low)
        favorable_points = max(0.0, max_high - entry_fill)
    else:
        adverse_points = max(0.0, max_high - entry_fill)
        favorable_points = max(0.0, entry_fill - min_low)

    exit_at = arrays["timestamps"][exit_idx]
    r_multiple = float(total_net) / risk_net
    ounces = LOT * CONTRACT_SIZE_OZ_PER_LOT
    return {
        "rejected": False,
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "tp1_at": tp1_at.isoformat() if tp1_at is not None else None,
        "direction": direction,
        "entry_mid": entry_mid,
        "entry_fill": entry_fill,
        "stop_mid": stop_mid,
        "tp1_mid": tp1_mid,
        "terminal_mid": terminal_mid,
        "exit_reason": exit_reason,
        "risk_net_points": risk_net,
        "tp1_r_after_cost": tp1_r,
        "terminal_rr_after_cost": tp2_r,
        "net_points": float(total_net),
        "r_multiple": r_multiple,
        "mae_r": adverse_points / risk_net,
        "mfe_r": favorable_points / risk_net,
        "duration_hours": max(0.0, (exit_at - entry_at).total_seconds() / 3600.0),
        "pnl_usd_0p01_lot_assumption": float(total_net) * ounces,
    }


def _m15_boundaries(completed: list[datetime], touch_at: datetime, window_minutes: int) -> list[datetime]:
    start = bisect_right(completed, ensure_utc(touch_at))
    end_at = ensure_utc(touch_at) + timedelta(minutes=int(window_minutes))
    out: list[datetime] = []
    for at in completed[start:]:
        if at > end_at:
            break
        out.append(ensure_utc(at))
    return out


def run_shard(*, adaptive_json: Path, csv_path: Path, shard_index: int, shard_count: int, output: Path) -> dict[str, Any]:
    adaptive_payload, touches = _load_adaptive(adaptive_json)
    price = load_price_frame(csv_path)
    arrays = _price_arrays(price)
    bars, completed, _frames = _bar_cache(price)
    selected = [row for i, row in enumerate(touches) if i % shard_count == shard_index]

    engine_cache: dict[str, dict[str, Any] | None] = {}
    cache_hits = 0
    cache_misses = 0
    trades: dict[str, list[dict[str, Any]]] = {k: [] for k in POLICIES}
    skips: dict[str, Counter[str]] = {k: Counter() for k in POLICIES}

    def engine_at(at: datetime) -> dict[str, Any] | None:
        nonlocal cache_hits, cache_misses
        key = ensure_utc(at).isoformat()
        if key in engine_cache:
            cache_hits += 1
            return engine_cache[key]
        cache_misses += 1
        px = _price_before(arrays, at)
        if px is None:
            engine_cache[key] = None
            return None
        h1 = _completed_bars(bars, completed, "H1", at)
        h4 = _completed_bars(bars, completed, "H4", at)
        m15 = _completed_bars(bars, completed, "M15", at)
        m5 = _completed_bars(bars, completed, "M5", at)
        if len(h1) < 80 or len(h4) < 40 or len(m15) < 32 or len(m5) < 32:
            engine_cache[key] = None
            return None
        engine_cache[key] = evaluate_sd_liquidity(
            bars_h1=h1, bars_h4=h4, bars_m15=m15, bars_m5=m5, as_of=at, price_now=float(px)
        )
        return engine_cache[key]

    for pos, episode in enumerate(selected, start=1):
        touch_at = _dt(episode["resolved_at"])
        original_zone = str(episode.get("final_target_zone_id") or episode.get("target_zone_id") or "")
        leg_direction = str(episode.get("final_direction") or episode.get("direction") or "").upper()
        expected_reversal = _opposite(leg_direction)

        for policy_id, policy in POLICIES.items():
            accepted = False
            last_reason = "NO_VALID_CONFIRMATION_IN_WINDOW"
            boundaries = _m15_boundaries(completed["M15"], touch_at, int(policy["window_minutes"]))
            if not boundaries:
                skips[policy_id]["NO_M15_BOUNDARY_IN_WINDOW"] += 1
                continue

            for confirm_at in boundaries:
                result = engine_at(confirm_at)
                if result is None:
                    last_reason = "ENGINE_UNAVAILABLE"
                    continue

                active_ids = {
                    str(dict(z or {}).get("zone_id") or "")
                    for z in list(result.get("active_zones") or [])
                    if not bool(dict(z or {}).get("intraday_quarantined"))
                }
                selected_ids = {
                    str(dict(result.get(key) or {}).get("zone_id") or "")
                    for key in ("main_reversal_zone", "decision_zone", "refinement_zone", "confirmation_zone")
                }
                if not original_zone or original_zone not in (active_ids | selected_ids):
                    last_reason = "TOUCHED_ZONE_NOT_ACTIVE_OR_REFINED"
                    continue

                guide = dict(result.get("entry_guide") or {})
                guide_state = str(guide.get("state") or "")
                if guide_state not in set(policy["allowed_states"]):
                    last_reason = f"GUIDE_{guide_state or 'EMPTY'}"
                    continue

                direction = str(guide.get("direction") or "").upper()
                if direction != expected_reversal:
                    last_reason = "REVERSAL_DIRECTION_MISMATCH"
                    continue

                stop_mid = _f(guide.get("invalidation"))
                terminal = _f(dict(result.get("structural_destination") or {}).get("price"))
                if stop_mid is None:
                    last_reason = "NO_STRUCTURAL_SL"
                    continue
                if terminal is None:
                    last_reason = "NO_OPPOSING_HTF_DESTINATION"
                    continue

                entry_idx = _find_entry_index(arrays["timestamps"], confirm_at)
                if entry_idx is None:
                    last_reason = "NO_ENTRY_BAR"
                    continue
                entry_mid = float(arrays["open"][entry_idx])
                tp1, tp1_source = _pick_tp1(
                    result=result, guide=guide, direction=direction, entry_mid=entry_mid, terminal=float(terminal)
                )
                if tp1 is None:
                    last_reason = "NO_VALID_STRUCTURAL_TP1"
                    continue

                sim = _simulate_staged(
                    arrays=arrays,
                    entry_idx=entry_idx,
                    direction=direction,
                    stop_mid=float(stop_mid),
                    tp1_mid=float(tp1),
                    terminal_mid=float(terminal),
                )
                if sim is None:
                    last_reason = "INVALID_EXECUTION_GEOMETRY"
                    continue
                if sim.get("rejected"):
                    last_reason = str(sim.get("reject_reason") or "REJECTED")
                    continue

                sim.update(
                    {
                        "policy_id": policy_id,
                        "episode_index": episode.get("index"),
                        "touch_at": touch_at.isoformat(),
                        "confirmation_at": confirm_at.isoformat(),
                        "confirmation_delay_minutes": max(0.0, (confirm_at - touch_at).total_seconds() / 60.0),
                        "original_target_zone_id": original_zone,
                        "guide_state": guide_state,
                        "tp1_source": tp1_source,
                        "execution_zone_id": str(dict(result.get("decision_zone") or {}).get("zone_id") or ""),
                    }
                )
                trades[policy_id].append(sim)
                accepted = True
                break

            if not accepted:
                skips[policy_id][last_reason] += 1

        if pos % 20 == 0 or pos == len(selected):
            summary = {k: len(v) for k, v in trades.items()}
            pct = 100.0 * pos / max(1, len(selected))
            print(
                f"V388_PROGRESS shard={shard_index+1}/{shard_count} processed={pos}/{len(selected)} "
                f"pct={pct:.1f} candidates={json.dumps(summary, sort_keys=True)} "
                f"cache_miss={cache_misses} cache_hit={cache_hits}",
                flush=True,
            )

    payload = {
        "schema": SCHEMA,
        "mode": "SHARD",
        "year": 2025,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "adaptive_config": ADAPTIVE_CONFIG,
        "adaptive_schema": adaptive_payload.get("schema"),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "target_touches": len(touches),
        "shard_target_touches": len(selected),
        "policies": POLICIES,
        "trades": trades,
        "skip_counts": {k: dict(v) for k, v in skips.items()},
        "engine_cache": {"entries": len(engine_cache), "hits": cache_hits, "misses": cache_misses},
        "fixed_execution": {
            "tp1_fraction": TP1_FRACTION,
            "tp2_fraction": TP2_FRACTION,
            "max_hold_hours": MAX_HOLD_HOURS,
            "min_terminal_rr_after_cost": MIN_TERMINAL_RR_AFTER_COST,
            "min_tp1_r_after_cost": MIN_TP1_R_AFTER_COST,
            "same_bar_policy": "STOP_FIRST",
            "break_even_after_tp1": False,
            "structural_sl": True,
            "spread_usd": SPREAD_USD,
            "slippage_usd_per_side": SLIPPAGE_USD_PER_SIDE,
            "commission_usd_per_lot_roundtrip": COMMISSION_USD_PER_LOT_ROUNDTRIP,
        },
        "execution_authority": False,
        "live_execution_enabled": False,
        "holdout_2026_used": False,
        "news_gate": "NOT_APPLIED_NO_CAUSAL_HISTORICAL_CALENDAR_IN_V388",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _max_drawdown(rs: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda x: str(x.get("entry_at") or ""))
    accepted: list[dict[str, Any]] = []
    active_exits: list[datetime] = []
    overlap_rejects = 0
    for row in rows:
        at = _dt(row["entry_at"])
        active_exits = [x for x in active_exits if x > at]
        if len(active_exits) >= MAX_OPEN_POSITIONS:
            overlap_rejects += 1
            continue
        accepted.append(row)
        active_exits.append(_dt(row["exit_at"]))

    rs = [float(x["r_multiple"]) for x in accepted]
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = None if gl <= 1e-12 else gp / gl
    return {
        "trades": len(accepted),
        "overlap_rejects": overlap_rejects,
        "win_rate": None if not rs else len(wins) / len(rs),
        "profit_factor_r": pf,
        "expectancy_r": None if not rs else sum(rs) / len(rs),
        "total_r": sum(rs),
        "max_drawdown_r": _max_drawdown(rs),
        "median_mae_r": None if not accepted else median(float(x["mae_r"]) for x in accepted),
        "median_mfe_r": None if not accepted else median(float(x["mfe_r"]) for x in accepted),
        "median_duration_hours": None if not accepted else median(float(x["duration_hours"]) for x in accepted),
        "median_confirmation_delay_minutes": None if not accepted else median(float(x["confirmation_delay_minutes"]) for x in accepted),
        "exit_counts": dict(Counter(str(x.get("exit_reason")) for x in accepted)),
        "guide_state_counts": dict(Counter(str(x.get("guide_state")) for x in accepted)),
    }


def _pf_pass(value: Any) -> bool:
    return value is None or float(value) > 1.0


def run_aggregate(*, inputs: str, output: Path) -> dict[str, Any]:
    files = sorted(Path(p) for p in glob.glob(inputs))
    if len(files) != 4:
        raise RuntimeError(f"Expected 4 V388 shard files, got {len(files)}: {files}")

    all_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skip_counts: dict[str, Counter[str]] = {k: Counter() for k in POLICIES}
    cache_entries = cache_hits = cache_misses = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA or payload.get("mode") != "SHARD" or int(payload.get("year")) != 2025:
            raise RuntimeError(f"Unexpected shard payload: {path}")
        for policy_id in POLICIES:
            all_rows[policy_id].extend(dict(x) for x in list(dict(payload.get("trades") or {}).get(policy_id) or []))
            skip_counts[policy_id].update(dict(dict(payload.get("skip_counts") or {}).get(policy_id) or {}))
        c = dict(payload.get("engine_cache") or {})
        cache_entries += int(c.get("entries") or 0)
        cache_hits += int(c.get("hits") or 0)
        cache_misses += int(c.get("misses") or 0)

    split_at = datetime(2025, 7, 1, tzinfo=UTC)
    results: dict[str, Any] = {}
    promotable: list[tuple[tuple[float, ...], str]] = []
    diagnostics: list[tuple[tuple[float, ...], str]] = []

    for policy_id in POLICIES:
        rows = all_rows[policy_id]
        h1 = [x for x in rows if _dt(x["entry_at"]) < split_at]
        h2 = [x for x in rows if _dt(x["entry_at"]) >= split_at]
        s_all = _summary(rows)
        s_h1 = _summary(h1)
        s_h2 = _summary(h2)
        results[policy_id] = {
            "policy": POLICIES[policy_id],
            "overall": s_all,
            "2025_H1": s_h1,
            "2025_H2": s_h2,
            "skip_counts": dict(skip_counts[policy_id]),
        }

        exp_all = float(s_all.get("expectancy_r") or -999.0)
        pf_all = float(s_all.get("profit_factor_r") or 999.0) if s_all.get("trades", 0) else -999.0
        diagnostics.append(((exp_all, pf_all, -float(s_all.get("max_drawdown_r") or 999.0)), policy_id))

        enough = int(s_all.get("trades") or 0) >= 12 and int(s_h1.get("trades") or 0) >= 4 and int(s_h2.get("trades") or 0) >= 4
        exp_h1 = s_h1.get("expectancy_r")
        exp_h2 = s_h2.get("expectancy_r")
        stable_positive = (
            enough
            and exp_h1 is not None
            and exp_h2 is not None
            and float(exp_h1) > 0.0
            and float(exp_h2) > 0.0
            and _pf_pass(s_h1.get("profit_factor_r"))
            and _pf_pass(s_h2.get("profit_factor_r"))
        )
        if stable_positive:
            pf1 = float(s_h1.get("profit_factor_r") or 999.0)
            pf2 = float(s_h2.get("profit_factor_r") or 999.0)
            key = (
                min(float(exp_h1), float(exp_h2)),
                min(pf1, pf2),
                float(s_all.get("expectancy_r") or -999.0),
                -float(s_all.get("max_drawdown_r") or 999.0),
            )
            promotable.append((key, policy_id))

    promotable.sort(reverse=True)
    diagnostics.sort(reverse=True)
    champion = promotable[0][1] if promotable else None
    diagnostic_best = diagnostics[0][1] if diagnostics else None
    decision = "FREEZE_V388_EXECUTION_POLICY" if champion else "REJECT_ALL_V388_POLICIES"

    payload = {
        "schema": "XAU_V388_EXECUTION_CALIBRATION_AGGREGATE_V1",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "calibration_year": 2025,
        "internal_split": "2025_H1_vs_2025_H2",
        "adaptive_config": ADAPTIVE_CONFIG,
        "results": results,
        "selection": {
            "decision": decision,
            "champion": champion,
            "diagnostic_best_if_no_champion": diagnostic_best,
            "criteria": {
                "min_total_trades": 12,
                "min_trades_each_half": 4,
                "both_halves_expectancy_gt_0": True,
                "both_halves_pf_gt_1": True,
                "ranking": "min_half_expectancy -> min_half_PF -> overall_expectancy -> lower_maxDD",
            },
        },
        "engine_cache": {"entries_sum": cache_entries, "hits": cache_hits, "misses": cache_misses},
        "holdout_2026_used": False,
        "execution_authority": False,
        "live_execution_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V388_CALIBRATION_SUMMARY=" + json.dumps(payload["selection"], sort_keys=True), flush=True)
    for policy_id in POLICIES:
        row = results[policy_id]
        print("V388_POLICY=" + json.dumps({"policy": policy_id, "overall": row["overall"], "H1": row["2025_H1"], "H2": row["2025_H2"]}, sort_keys=True), flush=True)
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--adaptive-json", type=Path, required=True)
    s.add_argument("--csv", type=Path, required=True)
    s.add_argument("--shard-index", type=int, required=True)
    s.add_argument("--shard-count", type=int, required=True)
    s.add_argument("--output", type=Path, required=True)
    a = sub.add_parser("aggregate")
    a.add_argument("--inputs", required=True)
    a.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.mode == "shard":
        run_shard(
            adaptive_json=args.adaptive_json,
            csv_path=args.csv,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            output=args.output,
        )
    else:
        run_aggregate(inputs=args.inputs, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
