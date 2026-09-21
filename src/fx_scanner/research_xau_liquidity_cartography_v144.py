from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import _cost_r
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _bars_frame,
    _wilder_atr,
    build_d1_context,
    build_h1_context,
)

RESEARCH_VERSION = "XAU_LIQUIDITY_CARTOGRAPHY_V144"
ARTIFACT_CONTRACT = "XAU_LIQUIDITY_CARTOGRAPHY_V144_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

START = datetime(2012, 1, 1, tzinfo=timezone.utc)
RECENT = datetime(2025, 1, 1, tzinfo=timezone.utc)

# Frozen before V144 results. These are mechanistic thresholds, not a grid.
SWEEP_ATR = 0.05
ACCEPT_ATR = 0.10
RETEST_TOL_ATR = 0.10
STOP_BUFFER_ATR = 0.10
DISPLACEMENT_BODY_ATR = 0.50
MSS_LOOKBACK = 3
RETEST_MAX_BARS = 3
MIN_TARGET_R = 1.50
MAX_HOLD_BARS = 32

POOL_WEIGHTS = {
    "PWH": 4.0,
    "PWL": 4.0,
    "PDH": 3.0,
    "PDL": 3.0,
    "H1_SWING_HIGH": 2.0,
    "H1_SWING_LOW": 2.0,
}

CANDIDATES = (
    "LCR_SWEEP_REJECTION",
    "LCR_ACCEPTED_BREAK",
    "LCR_COMBINED",
)


@dataclass(frozen=True, slots=True)
class LiquidityPool:
    kind: str
    level: float
    weight: float


@dataclass(frozen=True, slots=True)
class Setup:
    family: str
    direction: str
    signal_i: int
    entry_i: int
    entry_price: float
    stop: float
    target: float
    atr: float
    pool_kind: str
    pool_level: float
    gravity: float


def _frame(rows: Sequence[Bar]) -> pd.DataFrame:
    x = _bars_frame(rows)
    x["atr14"] = _wilder_atr(x, 14)
    x["body"] = (x["close"] - x["open"]).abs()
    return x


def _daily_weekly_levels(frame: pd.DataFrame) -> tuple[dict[Any, tuple[float,float]], dict[Any, tuple[float,float]]]:
    x = frame.set_index("time")
    d = x.resample("1D", label="left", closed="left").agg(high=("high","max"), low=("low","min")).dropna()
    w = x.resample("W-MON", label="left", closed="left").agg(high=("high","max"), low=("low","min")).dropna()

    day_map: dict[Any, tuple[float,float]] = {}
    days = list(d.index)
    for i in range(1, len(days)):
        day_map[days[i].date()] = (float(d.iloc[i-1]["high"]), float(d.iloc[i-1]["low"]))

    week_map: dict[Any, tuple[float,float]] = {}
    weeks = list(w.index)
    for i in range(1, len(weeks)):
        a = weeks[i]
        b = weeks[i+1] if i+1 < len(weeks) else frame["time"].iloc[-1] + pd.Timedelta(days=7)
        value = (float(w.iloc[i-1]["high"]), float(w.iloc[i-1]["low"]))
        for day in pd.date_range(a, b - pd.Timedelta(days=1), freq="1D", tz="UTC"):
            week_map[day.date()] = value
    return day_map, week_map


def _confirmed_h1_swings(rows: Sequence[Bar]) -> pd.DataFrame:
    h1 = build_h1_context(rows).copy().reset_index(drop=True)
    highs = h1["high"].astype(float).to_numpy()
    lows = h1["low"].astype(float).to_numpy()
    swing_hi = np.full(len(h1), np.nan)
    swing_lo = np.full(len(h1), np.nan)
    last_hi = np.nan
    last_lo = np.nan

    # Pivot at i is only known after H1 bars i+1 and i+2 have completed.
    for j in range(len(h1)):
        pivot = j - 2
        if pivot >= 2:
            if highs[pivot] > highs[pivot-1] and highs[pivot] > highs[pivot-2] and highs[pivot] >= highs[pivot+1] and highs[pivot] >= highs[pivot+2]:
                last_hi = float(highs[pivot])
            if lows[pivot] < lows[pivot-1] and lows[pivot] < lows[pivot-2] and lows[pivot] <= lows[pivot+1] and lows[pivot] <= lows[pivot+2]:
                last_lo = float(lows[pivot])
        swing_hi[j] = last_hi
        swing_lo[j] = last_lo

    h1["last_confirmed_swing_high"] = swing_hi
    h1["last_confirmed_swing_low"] = swing_lo
    return h1


def _context_ok(d1: Mapping[str,Any] | None, h1: Mapping[str,Any] | None, direction: str, *, strict: bool) -> bool:
    if d1 is None or h1 is None:
        return False
    side = 1 if direction == "LONG" else -1
    d1_side = int(d1.get("regime_side") or 0)
    if d1_side not in {0, side}:
        return False

    vals = [h1.get(k) for k in ("close","ema20","ema50","ema200","adx14","plus_di14","minus_di14")]
    try:
        close, e20, e50, e200, adx, pdi, mdi = [float(v) for v in vals]
    except (TypeError, ValueError):
        return False
    if not all(isfinite(v) for v in (close,e20,e50,e200,adx,pdi,mdi)):
        return False

    if direction == "LONG":
        soft = close > e200 and pdi > mdi
        normal = soft and e20 > e50
    else:
        soft = close < e200 and mdi > pdi
        normal = soft and e20 < e50
    return bool(normal and adx >= 15.0) if strict else bool(soft)


def _pools_at(
    *,
    ts,
    price: float,
    day_map,
    week_map,
    h1_row: Mapping[str,Any] | None,
) -> tuple[list[LiquidityPool], list[LiquidityPool]]:
    day = ensure_utc(ts).date()
    upper: list[LiquidityPool] = []
    lower: list[LiquidityPool] = []

    def add(kind: str, raw):
        try:
            level = float(raw)
        except (TypeError, ValueError):
            return
        if not isfinite(level) or level <= 0:
            return
        pool = LiquidityPool(kind, level, POOL_WEIGHTS[kind])
        if level > price:
            upper.append(pool)
        elif level < price:
            lower.append(pool)

    d = day_map.get(day)
    if d:
        add("PDH", d[0]); add("PDL", d[1])
    w = week_map.get(day)
    if w:
        add("PWH", w[0]); add("PWL", w[1])
    if h1_row is not None:
        add("H1_SWING_HIGH", h1_row.get("last_confirmed_swing_high"))
        add("H1_SWING_LOW", h1_row.get("last_confirmed_swing_low"))

    # Deduplicate same/near-identical levels while keeping strongest type.
    def dedupe(items):
        out: list[LiquidityPool] = []
        for p in sorted(items, key=lambda z: (-z.weight, z.level)):
            if any(abs(p.level-q.level) <= max(1e-9, price*1e-7) for q in out):
                continue
            out.append(p)
        return out
    return dedupe(upper), dedupe(lower)


def _gravity(upper: Sequence[LiquidityPool], lower: Sequence[LiquidityPool], *, price: float, atr: float, exclude: float | None = None) -> float:
    if atr <= 0:
        return 0.0
    up = 0.0
    dn = 0.0
    for p in upper:
        if exclude is not None and abs(p.level-exclude) <= 1e-9:
            continue
        up += p.weight / max(0.25, abs(p.level-price)/atr)
    for p in lower:
        if exclude is not None and abs(p.level-exclude) <= 1e-9:
            continue
        dn += p.weight / max(0.25, abs(price-p.level)/atr)
    total = up + dn
    return 0.0 if total <= 0 else float((up-dn)/total)


def _nearest_target(pools: Sequence[LiquidityPool], *, direction: str, entry: float, stop: float) -> float | None:
    risk = abs(entry-stop)
    if risk <= 0:
        return None
    if direction == "LONG":
        levels = sorted(p.level for p in pools if p.level > entry)
    else:
        levels = sorted((p.level for p in pools if p.level < entry), reverse=True)
    for level in levels:
        if abs(level-entry)/risk >= MIN_TARGET_R:
            return float(level)
    return None


def _make_trade(
    bars: Sequence[Bar],
    setup: Setup,
    *,
    costs,
    pip_size: float,
) -> TournamentTrade | None:
    risk = abs(setup.entry_price-setup.stop)
    if risk <= 0:
        return None
    risk_pips = risk/float(pip_size)
    last_i = min(len(bars)-1, setup.entry_i+MAX_HOLD_BARS)
    for j in range(setup.entry_i, last_i+1):
        b = bars[j]
        if setup.direction == "LONG":
            stop_hit = float(b.low) <= setup.stop
            target_hit = float(b.high) >= setup.target
        else:
            stop_hit = float(b.high) >= setup.stop
            target_hit = float(b.low) <= setup.target

        raw_target = target_hit
        if j == setup.entry_i:
            target_hit = False
        held = j-setup.entry_i
        cost = _cost_r(risk_pips=risk_pips, bars_held=held, costs=costs)

        if stop_hit:
            gross = -1.0
            return TournamentTrade(
                f"V144_{setup.family}", "XAUUSD", setup.direction,
                ensure_utc(bars[setup.signal_i].timestamp), ensure_utc(bars[setup.entry_i].timestamp), ensure_utc(b.timestamp),
                setup.signal_i, j, setup.entry_price, setup.stop, setup.atr, setup.stop, setup.target,
                gross, cost, gross-cost, held,
                "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
            )
        if target_hit:
            gross = abs(setup.target-setup.entry_price)/risk
            return TournamentTrade(
                f"V144_{setup.family}", "XAUUSD", setup.direction,
                ensure_utc(bars[setup.signal_i].timestamp), ensure_utc(bars[setup.entry_i].timestamp), ensure_utc(b.timestamp),
                setup.signal_i, j, setup.entry_price, setup.target, setup.atr, setup.stop, setup.target,
                gross, cost, gross-cost, held, "LIQUIDITY_TARGET_HIT",
            )

    if last_i < setup.entry_i+MAX_HOLD_BARS:
        return None
    b = bars[last_i]
    exit_price = float(b.close)
    gross = ((exit_price-setup.entry_price)/risk if setup.direction=="LONG" else (setup.entry_price-exit_price)/risk)
    cost = _cost_r(risk_pips=risk_pips, bars_held=MAX_HOLD_BARS, costs=costs)
    return TournamentTrade(
        f"V144_{setup.family}", "XAUUSD", setup.direction,
        ensure_utc(bars[setup.signal_i].timestamp), ensure_utc(bars[setup.entry_i].timestamp), ensure_utc(b.timestamp),
        setup.signal_i, last_i, setup.entry_price, exit_price, setup.atr, setup.stop, setup.target,
        gross, cost, gross-cost, MAX_HOLD_BARS, "TIME_EXIT",
    )


def extract_lcr_setups(rows: Sequence[Bar]) -> tuple[Setup, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    f = _frame(bars)
    day_map, week_map = _daily_weekly_levels(f)
    d1_lookup = _Asof(build_d1_context(bars))
    h1_lookup = _Asof(_confirmed_h1_swings(bars))

    setups: list[Setup] = []
    cooldown_until = -1

    for i in range(250, len(bars)-RETEST_MAX_BARS-2):
        if i <= cooldown_until:
            continue
        atr = float(f.iloc[i]["atr14"])
        if not isfinite(atr) or atr <= 0:
            continue
        b = bars[i]
        ts = ensure_utc(b.timestamp)
        h1 = h1_lookup.row(ts)
        d1 = d1_lookup.row(ts)
        # Classify event-side liquidity from the last completed M15 close, not
        # from the current bar close. Otherwise an accepted breakout would move
        # the crossed pool to the opposite side before we can detect the event.
        event_price = float(bars[i-1].close)
        upper, lower = _pools_at(ts=ts, price=event_price, day_map=day_map, week_map=week_map, h1_row=h1)
        if not upper and not lower:
            continue

        body = abs(float(b.close)-float(b.open))
        prev_lows = [float(x.low) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        prev_highs = [float(x.high) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        if len(prev_lows) < MSS_LOOKBACK:
            continue

        # 1) SWEEP -> REJECT -> MSS reversal.
        # We only use pools that were on the correct side of the signal open,
        # preventing post-event reclassification from manufacturing a sweep.
        for pool, direction in [
            *((p,"SHORT") for p in upper if p.level >= float(b.open)),
            *((p,"LONG") for p in lower if p.level <= float(b.open)),
        ]:
            if direction == "SHORT":
                swept = float(b.high) >= pool.level + SWEEP_ATR*atr
                rejected = float(b.close) < pool.level and float(b.close) < float(b.open)
                mss = float(b.close) < min(prev_lows)
            else:
                swept = float(b.low) <= pool.level - SWEEP_ATR*atr
                rejected = float(b.close) > pool.level and float(b.close) > float(b.open)
                mss = float(b.close) > max(prev_highs)
            if not (swept and rejected and mss and body >= DISPLACEMENT_BODY_ATR*atr):
                continue
            if not _context_ok(d1,h1,direction,strict=False):
                continue

            entry_i = i+1
            entry = float(bars[entry_i].open)
            stop = (float(b.high)+STOP_BUFFER_ATR*atr) if direction=="SHORT" else (float(b.low)-STOP_BUFFER_ATR*atr)
            # Rebuild target map at the signal close; exclude swept pool and
            # require post-sweep gravity to point at least weakly with the trade.
            up2, dn2 = _pools_at(ts=ts, price=entry, day_map=day_map, week_map=week_map, h1_row=h1)
            gravity = _gravity(up2,dn2,price=entry,atr=atr,exclude=pool.level)
            if (direction=="LONG" and gravity < 0.0) or (direction=="SHORT" and gravity > 0.0):
                continue
            target = _nearest_target(up2 if direction=="LONG" else dn2,direction=direction,entry=entry,stop=stop)
            if target is None:
                continue
            setups.append(Setup("SWEEP_REJECTION",direction,i,entry_i,entry,stop,target,atr,pool.kind,pool.level,gravity))
            cooldown_until = i+2
            break
        if cooldown_until >= i:
            continue

        # 2) BREAK -> ACCEPT -> RETEST continuation.
        for pool, direction in [
            *((p,"LONG") for p in upper),
            *((p,"SHORT") for p in lower),
        ]:
            if direction == "LONG":
                accepted = float(b.close) >= pool.level + ACCEPT_ATR*atr and float(b.close)>float(b.open)
            else:
                accepted = float(b.close) <= pool.level - ACCEPT_ATR*atr and float(b.close)<float(b.open)
            if not (accepted and body >= DISPLACEMENT_BODY_ATR*atr):
                continue
            if not _context_ok(d1,h1,direction,strict=True):
                continue

            retest_i = None
            for j in range(i+1, min(len(bars), i+1+RETEST_MAX_BARS)):
                x = bars[j]
                touched = float(x.low) <= pool.level + RETEST_TOL_ATR*atr and float(x.high) >= pool.level - RETEST_TOL_ATR*atr
                held = float(x.close) > pool.level if direction=="LONG" else float(x.close) < pool.level
                if touched and held:
                    retest_i = j
                    break
            if retest_i is None or retest_i+1 >= len(bars):
                continue

            signal_i = retest_i
            entry_i = retest_i+1
            entry = float(bars[entry_i].open)
            local = bars[max(i,retest_i-2):retest_i+1]
            stop = (min(float(x.low) for x in local)-STOP_BUFFER_ATR*atr) if direction=="LONG" else (max(float(x.high) for x in local)+STOP_BUFFER_ATR*atr)
            h1_retest = h1_lookup.row(ensure_utc(bars[retest_i].timestamp))
            up2,dn2 = _pools_at(ts=ensure_utc(bars[retest_i].timestamp),price=entry,day_map=day_map,week_map=week_map,h1_row=h1_retest)
            gravity = _gravity(up2,dn2,price=entry,atr=atr,exclude=pool.level)
            if (direction=="LONG" and gravity <= 0.0) or (direction=="SHORT" and gravity >= 0.0):
                continue
            target = _nearest_target(up2 if direction=="LONG" else dn2,direction=direction,entry=entry,stop=stop)
            if target is None:
                continue
            setups.append(Setup("ACCEPTED_BREAK",direction,signal_i,entry_i,entry,stop,target,atr,pool.kind,pool.level,gravity))
            cooldown_until = retest_i+2
            break

    return tuple(setups)


def simulate_lcr(rows: Sequence[Bar], *, costs, pip_size: float) -> dict[str, tuple[TournamentTrade,...]]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    setups = extract_lcr_setups(bars)
    rev: list[TournamentTrade] = []
    cont: list[TournamentTrade] = []
    for s in setups:
        t = _make_trade(bars,s,costs=costs,pip_size=pip_size)
        if t is None:
            continue
        if s.family == "SWEEP_REJECTION":
            rev.append(t)
        else:
            cont.append(t)
    combined = sorted((*rev,*cont), key=lambda t: (ensure_utc(t.entry_at),t.strategy_id))
    return {
        "LCR_SWEEP_REJECTION": tuple(rev),
        "LCR_ACCEPTED_BREAK": tuple(cont),
        "LCR_COMBINED": tuple(combined),
    }


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _period(trades,start,end):
    a,b=ensure_utc(start),ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _capital(trades, *, broker_spec, leverage_tiers):
    return _simulate(
        trades,
        spec=broker_spec,
        tiers=leverage_tiers,
        starting_balance=100.0,
        account_leverage=100.0,
        margin_cap_pct=50.0,
    )


def evaluate_v144(rows: Sequence[Bar], *, evaluation_end, pip_size, costs, broker_spec, leverage_tiers):
    end = ensure_utc(evaluation_end)
    routes = simulate_lcr(rows,costs=costs,pip_size=pip_size)
    out = {}
    for cid,trades in routes.items():
        full=_period(trades,START,end)
        recent=_period(trades,RECENT,end)
        direction = {
            "LONG": _metrics(tuple(t for t in full if t.direction=="LONG")),
            "SHORT": _metrics(tuple(t for t in full if t.direction=="SHORT")),
        }
        pool_breakdown = {}
        for kind in POOL_WEIGHTS:
            vals=tuple(t for t in full if kind in t.strategy_id)  # reserved, no outcome-driven routing
            if vals:
                pool_breakdown[kind]=_metrics(vals)
        out[cid]={
            "full_metrics":_metrics(full),
            "recent_metrics":_metrics(recent),
            "full_live100":_capital(full,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
            "recent_live100":_capital(recent,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
            "direction_metrics":direction,
        }
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "strategy":"Liquidity Cartography Router (LCR)",
            "liquidity_lines":["PDH","PDL","PWH","PWL","last-confirmed H1 swing high","last-confirmed H1 swing low"],
            "pool_weights":POOL_WEIGHTS,
            "sweep_atr":SWEEP_ATR,
            "accept_atr":ACCEPT_ATR,
            "retest_tolerance_atr":RETEST_TOL_ATR,
            "stop_buffer_atr":STOP_BUFFER_ATR,
            "displacement_body_atr":DISPLACEMENT_BODY_ATR,
            "mss_lookback_m15":MSS_LOOKBACK,
            "retest_max_bars":RETEST_MAX_BARS,
            "min_target_r":MIN_TARGET_R,
            "max_hold_bars":MAX_HOLD_BARS,
            "gravity":"sum(weight/distance_ATR) upper vs lower; post-event direction must agree",
            "target":"next mapped liquidity pool satisfying >=1.5R",
            "threshold_grid_search":False,
            "calendar_routing":False,
            "future_outcome_routing":False,
            "same_day_future_levels":False,
            "h1_swing_confirmation_delay_bars":2,
            "capital":"$100 / 1:100 / 20% risk / 50% margin cap",
            "execution_authority":False,
        },
        "candidates":out,
        "note":"V144 is a first-principles strategy experiment, not a filter on H3. Historical success is not promotion.",
    }
