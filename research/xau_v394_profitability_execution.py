from __future__ import annotations

"""V394 profitability-first execution calibration for frozen XAU C4 zones.

Selection uses 2025 only and is split H1/H2 internally. The zone/path selector is
not re-trained here. V394 isolates entry timing with one fixed exit model:
structural stop behind the touched zone plus 0.05 ATR and a 1.50R target AFTER
fixed research costs. No break-even move. Same-bar ambiguity is STOP_FIRST.

Policies are predeclared before results:
- EDGE25: limit at 25% zone penetration.
- EDGE50: limit at 50% zone penetration.
- SWEEP_RECLAIM_M5: >=20% penetration then completed M5 reclaim of near edge.
- CONFIRM_M15: canonical CONFIRMED_GUIDANCE within 120 minutes (baseline).

Research only. DEMO/LIVE execution authority is always false.
"""

import argparse
import glob
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from fx_scanner.models import ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import load_price_frame
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity
from xau_v384_adaptive_c4_reforecast_cached import _bar_cache, _completed_bars, _price_before
from xau_v387_execution_pnl_replay import (
    ADAPTIVE_CONFIG,
    COMMISSION_USD_PER_LOT_ROUNDTRIP,
    CONTRACT_SIZE_OZ_PER_LOT,
    LOT,
    SLIPPAGE_USD_PER_SIDE,
    SPREAD_USD,
    _dt,
    _f,
    _find_entry_index,
    _load_adaptive,
    _opposite,
    _price_arrays,
)

SCHEMA = "XAU_V394_PROFITABILITY_EXECUTION_V1"
MAX_OPEN_POSITIONS = 10
MAX_HOLD_HOURS = 24.0
STOP_BUFFER_ATR = 0.05
TARGET_R_AFTER_COST = 1.50
MAX_LIMIT_WAIT_MINUTES = 240
SWEEP_WINDOW_MINUTES = 120
CONFIRM_WINDOW_MINUTES = 120
MAX_MARKET_CHASE_ATR = 0.25

MIN_TOTAL_TRADES = 40
MIN_HALF_TRADES = 15
MIN_HALF_EXPECTANCY_R = 0.05
MIN_HALF_PF = 1.15

POLICIES: dict[str, dict[str, Any]] = {
    "EDGE25": {"kind": "LIMIT_DEPTH", "depth": 0.25},
    "EDGE50": {"kind": "LIMIT_DEPTH", "depth": 0.50},
    "SWEEP_RECLAIM_M5": {"kind": "SWEEP_RECLAIM_M5", "min_depth": 0.20},
    "CONFIRM_M15": {"kind": "CONFIRM_M15"},
}


def _zone_lookup(result: dict[str, Any], zone_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for key in ("main_reversal_zone", "decision_zone", "refinement_zone", "confirmation_zone", "nearest_demand", "nearest_supply"):
        row = dict(result.get(key) or {})
        if row:
            rows.append(row)
    rows.extend(dict(x or {}) for x in list(result.get("active_zones") or []))
    for row in rows:
        if str(row.get("zone_id") or "") == zone_id:
            return row
    return {}


def _near_far(zone: dict[str, Any], direction: str) -> tuple[float, float, float] | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    atr = _f(zone.get("atr"))
    if low is None or high is None or atr is None or atr <= 0 or high <= low:
        return None
    if direction == "LONG":
        return high, low, atr
    if direction == "SHORT":
        return low, high, atr
    return None


def _limit_level(near: float, far: float, depth: float) -> float:
    return near + float(depth) * (far - near)


def _find_limit_fill(arrays: dict[str, Any], touch_at: datetime, direction: str, level: float) -> int | None:
    start = max(0, bisect_left(arrays["timestamps"], ensure_utc(touch_at)) - 1)
    end_at = ensure_utc(touch_at) + timedelta(minutes=MAX_LIMIT_WAIT_MINUTES)
    end = min(len(arrays["timestamps"]), bisect_right(arrays["timestamps"], end_at))
    for i in range(start, end):
        if direction == "LONG" and float(arrays["low"][i]) <= level:
            return i
        if direction == "SHORT" and float(arrays["high"][i]) >= level:
            return i
    return None


def _m5_sweep_reclaim_entry(
    *, bars: dict[str, Any], completed: dict[str, list[datetime]], arrays: dict[str, Any], touch_at: datetime,
    direction: str, near: float, far: float, atr: float, min_depth: float,
) -> int | None:
    width = abs(far - near)
    if width <= 1e-9:
        return None
    start = bisect_right(completed["M5"], ensure_utc(touch_at))
    end_at = ensure_utc(touch_at) + timedelta(minutes=SWEEP_WINDOW_MINUTES)
    running_extreme = near
    for j in range(start, len(completed["M5"])):
        at = ensure_utc(completed["M5"][j])
        if at > end_at:
            break
        bar = bars["M5"][j]
        if direction == "LONG":
            running_extreme = min(running_extreme, float(bar.low))
            depth = max(0.0, (near - running_extreme) / width)
            reclaimed = float(bar.close) >= near
        else:
            running_extreme = max(running_extreme, float(bar.high))
            depth = max(0.0, (running_extreme - near) / width)
            reclaimed = float(bar.close) <= near
        if depth < min_depth or not reclaimed:
            continue
        idx = _find_entry_index(arrays["timestamps"], at)
        if idx is None:
            return None
        px = float(arrays["open"][idx])
        if abs(px - near) / atr > MAX_MARKET_CHASE_ATR:
            return None
        return idx
    return None


def _m15_confirm_entry(
    *, completed: dict[str, list[datetime]], arrays: dict[str, Any], engine_at: Any, touch_at: datetime,
    original_zone: str, expected_reversal: str, near: float, atr: float,
) -> int | None:
    start = bisect_right(completed["M15"], ensure_utc(touch_at))
    end_at = ensure_utc(touch_at) + timedelta(minutes=CONFIRM_WINDOW_MINUTES)
    for at in completed["M15"][start:]:
        at = ensure_utc(at)
        if at > end_at:
            break
        result = engine_at(at)
        if result is None:
            continue
        recognized = _zone_lookup(result, original_zone)
        if not recognized:
            continue
        guide = dict(result.get("entry_guide") or {})
        if str(guide.get("state") or "") != "CONFIRMED_GUIDANCE":
            continue
        if str(guide.get("direction") or "").upper() != expected_reversal:
            continue
        idx = _find_entry_index(arrays["timestamps"], at)
        if idx is None:
            return None
        px = float(arrays["open"][idx])
        if abs(px - near) / atr > MAX_MARKET_CHASE_ATR:
            return None
        return idx
    return None


def _cost_geometry(entry_mid: float, direction: str, stop_mid: float) -> dict[str, float] | None:
    sign = 1.0 if direction == "LONG" else -1.0
    per_side = SPREAD_USD / 2.0 + SLIPPAGE_USD_PER_SIDE
    commission_points = COMMISSION_USD_PER_LOT_ROUNDTRIP / CONTRACT_SIZE_OZ_PER_LOT
    entry_fill = entry_mid + sign * per_side
    stop_fill = stop_mid - sign * per_side
    stop_net = sign * (stop_fill - entry_fill) - commission_points
    risk_net = -stop_net
    if risk_net <= 1e-9:
        return None
    target_fill = entry_fill + sign * (TARGET_R_AFTER_COST * risk_net + commission_points)
    target_mid = target_fill + sign * per_side
    return {
        "sign": sign,
        "per_side": per_side,
        "commission_points": commission_points,
        "entry_fill": entry_fill,
        "stop_fill": stop_fill,
        "risk_net": risk_net,
        "target_mid": target_mid,
    }


def _simulate(
    *, arrays: dict[str, Any], entry_idx: int, entry_mid: float, direction: str, stop_mid: float,
) -> dict[str, Any] | None:
    geom = _cost_geometry(entry_mid, direction, stop_mid)
    if geom is None:
        return None
    sign = float(geom["sign"])
    target_mid = float(geom["target_mid"])
    if direction == "LONG" and not (stop_mid < entry_mid < target_mid):
        return None
    if direction == "SHORT" and not (target_mid < entry_mid < stop_mid):
        return None
    entry_at = arrays["timestamps"][entry_idx]
    end_at = entry_at + timedelta(hours=MAX_HOLD_HOURS)
    end = min(len(arrays["timestamps"]), bisect_right(arrays["timestamps"], end_at))
    if end <= entry_idx:
        return None
    min_low = float("inf")
    max_high = float("-inf")
    exit_idx = end - 1
    exit_reason = "TIMEOUT"
    exit_mid = float(arrays["close"][exit_idx])
    for i in range(entry_idx, end):
        lo = float(arrays["low"][i]); hi = float(arrays["high"][i])
        min_low = min(min_low, lo); max_high = max(max_high, hi)
        if direction == "LONG":
            stop_hit = lo <= stop_mid; target_hit = hi >= target_mid
        else:
            stop_hit = hi >= stop_mid; target_hit = lo <= target_mid
        if stop_hit:  # STOP_FIRST when both happen in one M1 bar.
            exit_idx = i; exit_reason = "SL"; exit_mid = stop_mid; break
        if target_hit:
            exit_idx = i; exit_reason = "TP_1P50R"; exit_mid = target_mid; break
    per_side = float(geom["per_side"]); commission = float(geom["commission_points"])
    entry_fill = float(geom["entry_fill"])
    exit_fill = exit_mid - sign * per_side
    net_points = sign * (exit_fill - entry_fill) - commission
    risk_net = float(geom["risk_net"])
    if direction == "LONG":
        adverse = max(0.0, entry_fill - min_low); favorable = max(0.0, max_high - entry_fill)
    else:
        adverse = max(0.0, max_high - entry_fill); favorable = max(0.0, entry_fill - min_low)
    exit_at = arrays["timestamps"][exit_idx]
    return {
        "entry_at": entry_at.isoformat(), "exit_at": exit_at.isoformat(), "direction": direction,
        "entry_mid": entry_mid, "stop_mid": stop_mid, "target_mid": target_mid,
        "exit_reason": exit_reason, "risk_net_points": risk_net, "r_multiple": net_points / risk_net,
        "net_points": net_points, "mae_r": adverse / risk_net, "mfe_r": favorable / risk_net,
        "duration_hours": max(0.0, (exit_at-entry_at).total_seconds()/3600.0),
        "pnl_usd_0p01_lot_assumption": net_points * LOT * CONTRACT_SIZE_OZ_PER_LOT,
    }


def run_shard(*, adaptive_json: Path, csv_path: Path, shard_index: int, shard_count: int, output: Path) -> dict[str, Any]:
    adaptive_payload, touches = _load_adaptive(adaptive_json)
    price = load_price_frame(csv_path)
    arrays = _price_arrays(price)
    bars, completed, _frames = _bar_cache(price)
    selected = [row for i, row in enumerate(touches) if i % shard_count == shard_index]
    trades: dict[str, list[dict[str, Any]]] = {k: [] for k in POLICIES}
    skips: dict[str, Counter[str]] = {k: Counter() for k in POLICIES}
    cache: dict[str, dict[str, Any] | None] = {}

    def engine_at(at: datetime) -> dict[str, Any] | None:
        key = ensure_utc(at).isoformat()
        if key in cache:
            return cache[key]
        px = _price_before(arrays, at)
        if px is None:
            cache[key] = None; return None
        h1 = _completed_bars(bars, completed, "H1", at); h4 = _completed_bars(bars, completed, "H4", at)
        m15 = _completed_bars(bars, completed, "M15", at); m5 = _completed_bars(bars, completed, "M5", at)
        if len(h1) < 80 or len(h4) < 40 or len(m15) < 32 or len(m5) < 32:
            cache[key] = None; return None
        cache[key] = evaluate_sd_liquidity(bars_h1=h1, bars_h4=h4, bars_m15=m15, bars_m5=m5, as_of=at, price_now=float(px))
        return cache[key]

    for pos, episode in enumerate(selected, start=1):
        touch_at = _dt(episode["resolved_at"])
        original_zone = str(episode.get("final_target_zone_id") or episode.get("target_zone_id") or "")
        expected_reversal = _opposite(str(episode.get("final_direction") or episode.get("direction") or "").upper())
        result = engine_at(touch_at)
        zone = {} if result is None else _zone_lookup(result, original_zone)
        if not zone:
            for policy in POLICIES: skips[policy]["ZONE_NOT_RECOGNIZED_AT_TOUCH"] += 1
            continue
        direction = str(zone.get("direction") or "").upper()
        if direction != expected_reversal:
            for policy in POLICIES: skips[policy]["DIRECTION_MISMATCH"] += 1
            continue
        nfa = _near_far(zone, direction)
        if nfa is None:
            for policy in POLICIES: skips[policy]["INVALID_ZONE_GEOMETRY"] += 1
            continue
        near, far, atr = nfa
        stop_mid = far - STOP_BUFFER_ATR*atr if direction == "LONG" else far + STOP_BUFFER_ATR*atr

        for policy_id, policy in POLICIES.items():
            entry_idx: int | None = None
            entry_mid: float | None = None
            if policy["kind"] == "LIMIT_DEPTH":
                entry_mid = _limit_level(near, far, float(policy["depth"]))
                entry_idx = _find_limit_fill(arrays, touch_at, direction, entry_mid)
            elif policy["kind"] == "SWEEP_RECLAIM_M5":
                entry_idx = _m5_sweep_reclaim_entry(
                    bars=bars, completed=completed, arrays=arrays, touch_at=touch_at, direction=direction,
                    near=near, far=far, atr=atr, min_depth=float(policy["min_depth"]),
                )
                if entry_idx is not None: entry_mid = float(arrays["open"][entry_idx])
            else:
                entry_idx = _m15_confirm_entry(
                    completed=completed, arrays=arrays, engine_at=engine_at, touch_at=touch_at,
                    original_zone=original_zone, expected_reversal=direction, near=near, atr=atr,
                )
                if entry_idx is not None: entry_mid = float(arrays["open"][entry_idx])
            if entry_idx is None or entry_mid is None:
                skips[policy_id]["NO_ENTRY"] += 1; continue
            simulated = _simulate(arrays=arrays, entry_idx=entry_idx, entry_mid=entry_mid, direction=direction, stop_mid=stop_mid)
            if simulated is None:
                skips[policy_id]["INVALID_EXECUTION_GEOMETRY"] += 1; continue
            simulated.update({
                "policy": policy_id, "episode_index": episode.get("index"), "touch_at": touch_at.isoformat(),
                "zone_id": original_zone, "zone_timeframe": zone.get("timeframe"), "zone_low": zone.get("low"),
                "zone_high": zone.get("high"), "zone_atr": atr,
            })
            trades[policy_id].append(simulated)
        if pos % 25 == 0 or pos == len(selected):
            print("V394_PROGRESS=" + json.dumps({"shard": shard_index, "processed": pos, "total": len(selected), "trades": {k:len(v) for k,v in trades.items()}}, sort_keys=True), flush=True)

    payload = {
        "schema": SCHEMA, "mode": "SHARD", "year": 2025, "generated_at": datetime.now(tz=UTC).isoformat(),
        "adaptive_config": ADAPTIVE_CONFIG, "adaptive_schema": adaptive_payload.get("schema"),
        "shard_index": shard_index, "shard_count": shard_count, "target_touches": len(touches),
        "policies": {k: dict(v) for k,v in POLICIES.items()}, "trades": trades,
        "skip_counts": {k: dict(v) for k,v in skips.items()},
        "cost_model": {"spread_usd":SPREAD_USD,"slippage_usd_per_side":SLIPPAGE_USD_PER_SIDE,"commission_usd_per_lot_roundtrip":COMMISSION_USD_PER_LOT_ROUNDTRIP,"target_r_after_cost":TARGET_R_AFTER_COST,"stop_buffer_atr":STOP_BUFFER_ATR},
        "execution_authority": False, "demo_auto_execution": False, "live_execution_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return payload


def _max_drawdown(values: list[float]) -> float:
    equity=0.0; peak=0.0; dd=0.0
    for v in values:
        equity += v; peak=max(peak,equity); dd=max(dd,peak-equity)
    return dd


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows=sorted(rows,key=lambda x:str(x.get("entry_at") or ""))
    r=[float(x["r_multiple"]) for x in rows]
    wins=[x for x in r if x>0]; losses=[x for x in r if x<0]
    gp=sum(wins); gl=abs(sum(losses)); pf=None if gl<=1e-12 else gp/gl
    return {
        "trades":len(rows), "wins":len(wins), "losses":len(losses), "win_rate":None if not r else len(wins)/len(r),
        "profit_factor_r":pf, "expectancy_r":None if not r else sum(r)/len(r), "total_r":sum(r), "max_drawdown_r":_max_drawdown(r),
        "median_mae_r":None if not rows else median(float(x["mae_r"]) for x in rows),
        "median_mfe_r":None if not rows else median(float(x["mfe_r"]) for x in rows),
        "median_duration_hours":None if not rows else median(float(x["duration_hours"]) for x in rows),
        "exit_counts":dict(Counter(str(x.get("exit_reason")) for x in rows)),
    }


def _pf_pass(m: dict[str, Any]) -> bool:
    pf=m.get("profit_factor_r")
    if pf is None:
        return int(m.get("losses") or 0)==0 and int(m.get("wins") or 0)>0
    return float(pf) > MIN_HALF_PF


def run_aggregate(*, inputs: str, output: Path) -> dict[str, Any]:
    files=sorted(Path(p) for p in glob.glob(inputs))
    if not files: raise RuntimeError(f"No shard files matched {inputs}")
    by_policy: dict[str,list[dict[str,Any]]] = {k:[] for k in POLICIES}
    skips: dict[str,Counter[str]] = {k:Counter() for k in POLICIES}
    for path in files:
        p=json.loads(path.read_text(encoding="utf-8"))
        for k in POLICIES:
            by_policy[k].extend(dict(x) for x in list(dict(p.get("trades") or {}).get(k) or []))
            skips[k].update(dict(dict(p.get("skip_counts") or {}).get(k) or {}))
    results={}
    promotable=[]
    for policy, rows in by_policy.items():
        rows=sorted(rows,key=lambda x:str(x.get("entry_at") or ""))
        accepted=[]; active=[]
        for row in rows:
            entry=_dt(row["entry_at"]); active=[x for x in active if x>entry]
            if len(active)>=MAX_OPEN_POSITIONS: continue
            accepted.append(row); active.append(_dt(row["exit_at"]))
        h1=[x for x in accepted if _dt(x["entry_at"]).month<=6]
        h2=[x for x in accepted if _dt(x["entry_at"]).month>=7]
        overall=_metrics(accepted); m1=_metrics(h1); m2=_metrics(h2)
        checks={
            "min_total":overall["trades"]>=MIN_TOTAL_TRADES, "min_h1":m1["trades"]>=MIN_HALF_TRADES, "min_h2":m2["trades"]>=MIN_HALF_TRADES,
            "h1_expectancy":m1["expectancy_r"] is not None and float(m1["expectancy_r"])>MIN_HALF_EXPECTANCY_R,
            "h2_expectancy":m2["expectancy_r"] is not None and float(m2["expectancy_r"])>MIN_HALF_EXPECTANCY_R,
            "h1_pf":_pf_pass(m1), "h2_pf":_pf_pass(m2),
        }
        passed=all(checks.values())
        results[policy]={"overall":overall,"H1":m1,"H2":m2,"checks":checks,"passed":passed,"skip_counts":dict(skips[policy])}
        if passed:
            min_exp=min(float(m1["expectancy_r"]),float(m2["expectancy_r"]))
            def pf_rank(m:dict[str,Any])->float: return 999.0 if m.get("profit_factor_r") is None else float(m["profit_factor_r"])
            min_pf=min(pf_rank(m1),pf_rank(m2))
            promotable.append((min_exp,min_pf,float(overall["expectancy_r"] or -999),-float(overall["max_drawdown_r"]),policy))
    promotable.sort(reverse=True)
    champion=promotable[0][-1] if promotable else None
    payload={
        "schema":SCHEMA,"mode":"AGGREGATE_2025_SELECTION","generated_at":datetime.now(tz=UTC).isoformat(),
        "criteria":{"min_total_trades":MIN_TOTAL_TRADES,"min_half_trades":MIN_HALF_TRADES,"min_half_expectancy_r_strict_gt":MIN_HALF_EXPECTANCY_R,"min_half_pf_strict_gt":MIN_HALF_PF,"target_r_after_cost":TARGET_R_AFTER_COST},
        "results":results,"champion":champion,"decision":"FREEZE_V394_CHAMPION_FOR_2026_HOLDOUT" if champion else "REJECT_ALL_V394_POLICIES",
        "ranking":"min_half_expectancy -> min_half_PF -> overall_expectancy -> lower_maxDD",
        "execution_authority":False,"demo_auto_execution":False,"live_execution_enabled":False,
        "next_gate":"2026 untouched holdout for frozen champion only" if champion else "Redesign WHERE/entry family; do not loosen production gates.",
    }
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("V394_SELECTION="+json.dumps({"champion":champion,"decision":payload["decision"],"results":results},sort_keys=True),flush=True)
    return payload


def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="mode",required=True)
    s=sub.add_parser("shard"); s.add_argument("--adaptive-json",type=Path,required=True); s.add_argument("--csv",type=Path,required=True); s.add_argument("--shard-index",type=int,required=True); s.add_argument("--shard-count",type=int,required=True); s.add_argument("--output",type=Path,required=True)
    a=sub.add_parser("aggregate"); a.add_argument("--inputs",required=True); a.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.mode=="shard": run_shard(adaptive_json=args.adaptive_json,csv_path=args.csv,shard_index=args.shard_index,shard_count=args.shard_count,output=args.output)
    else: run_aggregate(inputs=args.inputs,output=args.output)
    return 0


if __name__=="__main__": raise SystemExit(main())
