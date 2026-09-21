from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _resample_completed,
    build_d1_context,
)
from .research_xau_liquidity_cartography_v144 import (
    ACCEPT_ATR,
    DISPLACEMENT_BODY_ATR,
    MAX_HOLD_BARS,
    MIN_TARGET_R,
    MSS_LOOKBACK,
    RETEST_MAX_BARS,
    RETEST_TOL_ATR,
    STOP_BUFFER_ATR,
    SWEEP_ATR,
    Setup,
    _confirmed_h1_swings,
    _context_ok,
    _frame,
    _make_trade,
)

RESEARCH_VERSION="XAU_LIQUIDITY_MEMORY_ROUTER_V146"
ARTIFACT_CONTRACT="XAU_LIQUIDITY_MEMORY_ROUTER_V146_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START=datetime(2012,1,1,tzinfo=timezone.utc)
RECENT=datetime(2025,1,1,tzinfo=timezone.utc)

# Independent preregistration: supported by published SR-level persistence evidence.
MEMORY_HALF_LIFE_DAYS=5.0
MAX_POOL_AGE_DAYS=20.0
MAX_TOUCH_BONUS=3
TOUCH_TOL_ATR=0.10
TOUCH_REJECTION_ATR=0.10
TOUCH_COOLDOWN_BARS=4

CANDIDATES=(
    "LMR_SWEEP_REJECTION",
    "LMR_ACCEPTED_BREAK",
    "LMR_COMBINED",
)


@dataclass(slots=True)
class MemoryPool:
    pool_id: str
    kind: str
    level: float
    born_at: Any
    touches: int=0
    last_touch_i: int=-10_000
    consumed: bool=False

    def age_days(self, now) -> float:
        return max(0.0,(ensure_utc(now)-ensure_utc(self.born_at)).total_seconds()/86400.0)

    def strength(self, now) -> float:
        decay=2.0**(-self.age_days(now)/MEMORY_HALF_LIFE_DAYS)
        bounce=1.0+float(min(self.touches,MAX_TOUCH_BONUS))
        return float(bounce*decay)


def _birth_events(rows:Sequence[Bar]) -> tuple[tuple[Any,str,float],...]:
    events=[]
    d1=_resample_completed(rows,"1D")
    for _,r in d1.iterrows():
        ts=ensure_utc(r["time"].to_pydatetime() if hasattr(r["time"],"to_pydatetime") else r["time"])
        events.append((ts,"PDH",float(r["high"])))
        events.append((ts,"PDL",float(r["low"])))

    w1=_resample_completed(rows,"W-MON")
    for _,r in w1.iterrows():
        ts=ensure_utc(r["time"].to_pydatetime() if hasattr(r["time"],"to_pydatetime") else r["time"])
        events.append((ts,"PWH",float(r["high"])))
        events.append((ts,"PWL",float(r["low"])))

    h1=_confirmed_h1_swings(rows).reset_index(drop=True)
    prev_hi=None
    prev_lo=None
    for _,r in h1.iterrows():
        ts=ensure_utc(r["time"].to_pydatetime() if hasattr(r["time"],"to_pydatetime") else r["time"])
        hi=r.get("last_confirmed_swing_high")
        lo=r.get("last_confirmed_swing_low")
        if hi is not None and isfinite(float(hi)) and (prev_hi is None or abs(float(hi)-float(prev_hi))>1e-9):
            events.append((ts,"H1_SWING_HIGH",float(hi)))
            prev_hi=float(hi)
        if lo is not None and isfinite(float(lo)) and (prev_lo is None or abs(float(lo)-float(prev_lo))>1e-9):
            events.append((ts,"H1_SWING_LOW",float(lo)))
            prev_lo=float(lo)

    events.sort(key=lambda x:(x[0],x[1],x[2]))
    return tuple(events)


def _dedupe_add(active:list[MemoryPool], *, ts, kind:str, level:float, atr:float, serial:int) -> int:
    # Same structural area within 0.10 ATR is treated as one pool; retain the
    # older memory and do not manufacture strength by stacking duplicate labels.
    tol=max(1e-9,TOUCH_TOL_ATR*max(atr,1e-9))
    if any((not p.consumed) and abs(p.level-level)<=tol for p in active):
        return serial
    active.append(MemoryPool(f"{kind}:{serial}",kind,float(level),ts))
    return serial+1


def _split(active:Sequence[MemoryPool], *, price:float) -> tuple[list[MemoryPool],list[MemoryPool]]:
    upper=sorted((p for p in active if not p.consumed and p.level>price),key=lambda p:p.level)
    lower=sorted((p for p in active if not p.consumed and p.level<price),key=lambda p:p.level,reverse=True)
    return upper,lower


def _gravity(upper:Sequence[MemoryPool],lower:Sequence[MemoryPool],*,price:float,atr:float,now,exclude_id:str|None=None)->float:
    if atr<=0:return 0.0
    up=dn=0.0
    for p in upper:
        if p.pool_id==exclude_id:continue
        up+=p.strength(now)/max(0.25,abs(p.level-price)/atr)
    for p in lower:
        if p.pool_id==exclude_id:continue
        dn+=p.strength(now)/max(0.25,abs(price-p.level)/atr)
    total=up+dn
    return 0.0 if total<=0 else float((up-dn)/total)


def _nearest_target(pools:Sequence[MemoryPool],*,direction:str,entry:float,stop:float)->float|None:
    risk=abs(entry-stop)
    if risk<=0:return None
    ordered=sorted((p.level for p in pools if p.level>entry),reverse=False) if direction=="LONG" else sorted((p.level for p in pools if p.level<entry),reverse=True)
    for level in ordered:
        if abs(level-entry)/risk>=MIN_TARGET_R:
            return float(level)
    return None


def _update_memory(active:list[MemoryPool], *, bars:Sequence[Bar], i:int, atr:float):
    if i<=0:return
    b=bars[i]
    prev=float(bars[i-1].close)
    close=float(b.close)
    now=ensure_utc(b.timestamp)
    for p in active:
        if p.consumed:continue
        # Accepted cross consumes a pool only after the current event has had a
        # chance to create an accepted-break setup.
        if prev<p.level and close>=p.level+ACCEPT_ATR*atr:
            p.consumed=True
            continue
        if prev>p.level and close<=p.level-ACCEPT_ATR*atr:
            p.consumed=True
            continue

        if i-p.last_touch_i<TOUCH_COOLDOWN_BARS:
            continue
        if prev<p.level:
            touched=float(b.high)>=p.level-TOUCH_TOL_ATR*atr
            rejected=close<=p.level-TOUCH_REJECTION_ATR*atr
        else:
            touched=float(b.low)<=p.level+TOUCH_TOL_ATR*atr
            rejected=close>=p.level+TOUCH_REJECTION_ATR*atr
        if touched and rejected:
            p.touches+=1
            p.last_touch_i=i

    active[:]=[
        p for p in active
        if (not p.consumed) and p.age_days(now)<=MAX_POOL_AGE_DAYS
    ]


def extract_lmr_setups(rows:Sequence[Bar])->tuple[Setup,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    f=_frame(bars)
    d1_lookup=_Asof(build_d1_context(bars))
    h1_frame=_confirmed_h1_swings(bars)
    h1_lookup=_Asof(h1_frame)
    births=_birth_events(bars)
    birth_i=0
    active:list[MemoryPool]=[]
    serial=0
    setups=[]
    cooldown_until=-1

    for i in range(250,len(bars)-RETEST_MAX_BARS-2):
        b=bars[i]
        ts=ensure_utc(b.timestamp)
        atr=float(f.iloc[i]["atr14"])
        if not isfinite(atr) or atr<=0:continue

        while birth_i<len(births) and ensure_utc(births[birth_i][0])<=ts:
            born,kind,level=births[birth_i]
            serial=_dedupe_add(active,ts=born,kind=kind,level=level,atr=atr,serial=serial)
            birth_i+=1
        active[:]=[p for p in active if (not p.consumed) and p.age_days(ts)<=MAX_POOL_AGE_DAYS]
        if i<=cooldown_until:
            _update_memory(active,bars=bars,i=i,atr=atr)
            continue

        prev_price=float(bars[i-1].close)
        upper,lower=_split(active,price=prev_price)
        if not upper and not lower:
            _update_memory(active,bars=bars,i=i,atr=atr)
            continue

        d1=d1_lookup.row(ts)
        h1=h1_lookup.row(ts)
        body=abs(float(b.close)-float(b.open))
        prev_lows=[float(x.low) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        prev_highs=[float(x.high) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        if len(prev_lows)<MSS_LOOKBACK:
            _update_memory(active,bars=bars,i=i,atr=atr)
            continue

        made=False
        # Sweep-rejection uses the closest pre-event pool on either side.
        event_pairs=[]
        if upper:event_pairs.append((upper[0],"SHORT"))
        if lower:event_pairs.append((lower[0],"LONG"))
        for pool,direction in event_pairs:
            if direction=="SHORT":
                swept=float(b.high)>=pool.level+SWEEP_ATR*atr
                rejected=float(b.close)<pool.level and float(b.close)<float(b.open)
                mss=float(b.close)<min(prev_lows)
            else:
                swept=float(b.low)<=pool.level-SWEEP_ATR*atr
                rejected=float(b.close)>pool.level and float(b.close)>float(b.open)
                mss=float(b.close)>max(prev_highs)
            if not(swept and rejected and mss and body>=DISPLACEMENT_BODY_ATR*atr):
                continue
            if not _context_ok(d1,h1,direction,strict=False):
                continue
            entry_i=i+1
            entry=float(bars[entry_i].open)
            stop=float(b.high)+STOP_BUFFER_ATR*atr if direction=="SHORT" else float(b.low)-STOP_BUFFER_ATR*atr
            up2,lo2=_split(active,price=entry)
            gravity=_gravity(up2,lo2,price=entry,atr=atr,now=ts,exclude_id=pool.pool_id)
            if (direction=="LONG" and gravity<0) or (direction=="SHORT" and gravity>0):
                continue
            target=_nearest_target(up2 if direction=="LONG" else lo2,direction=direction,entry=entry,stop=stop)
            if target is None:continue
            setups.append(Setup("LMR_SWEEP_REJECTION",direction,i,entry_i,entry,stop,target,atr,pool.kind,pool.level,gravity))
            cooldown_until=i+2
            made=True
            break

        if not made:
            # Accepted break: closest pre-event pool only. The break itself is
            # observed now; pool remains present until memory update below.
            event_pairs=[]
            if upper:event_pairs.append((upper[0],"LONG"))
            if lower:event_pairs.append((lower[0],"SHORT"))
            for pool,direction in event_pairs:
                accepted=(float(b.close)>=pool.level+ACCEPT_ATR*atr and float(b.close)>float(b.open)) if direction=="LONG" else (float(b.close)<=pool.level-ACCEPT_ATR*atr and float(b.close)<float(b.open))
                if not(accepted and body>=DISPLACEMENT_BODY_ATR*atr):
                    continue
                if not _context_ok(d1,h1,direction,strict=True):
                    continue
                retest_i=None
                for j in range(i+1,min(len(bars),i+1+RETEST_MAX_BARS)):
                    x=bars[j]
                    touched=float(x.low)<=pool.level+RETEST_TOL_ATR*atr and float(x.high)>=pool.level-RETEST_TOL_ATR*atr
                    held=float(x.close)>pool.level if direction=="LONG" else float(x.close)<pool.level
                    if touched and held:
                        retest_i=j;break
                if retest_i is None or retest_i+1>=len(bars):continue
                signal_i=retest_i;entry_i=retest_i+1;entry=float(bars[entry_i].open)
                local=bars[max(i,retest_i-2):retest_i+1]
                stop=min(float(x.low) for x in local)-STOP_BUFFER_ATR*atr if direction=="LONG" else max(float(x.high) for x in local)+STOP_BUFFER_ATR*atr
                # Build target from other persistent pools; crossed pool is excluded.
                others=[p for p in active if p.pool_id!=pool.pool_id]
                up2,lo2=_split(others,price=entry)
                gravity=_gravity(up2,lo2,price=entry,atr=atr,now=ensure_utc(bars[retest_i].timestamp))
                if (direction=="LONG" and gravity<=0) or (direction=="SHORT" and gravity>=0):continue
                target=_nearest_target(up2 if direction=="LONG" else lo2,direction=direction,entry=entry,stop=stop)
                if target is None:continue
                setups.append(Setup("LMR_ACCEPTED_BREAK",direction,signal_i,entry_i,entry,stop,target,atr,pool.kind,pool.level,gravity))
                cooldown_until=retest_i+2
                made=True
                break

        _update_memory(active,bars=bars,i=i,atr=atr)

    return tuple(setups)


def simulate_lmr(rows:Sequence[Bar],*,costs,pip_size:float)->dict[str,tuple[TournamentTrade,...]]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    rev=[];cont=[]
    for s in extract_lmr_setups(bars):
        t=_make_trade(bars,s,costs=costs,pip_size=pip_size)
        if t is None:continue
        if s.family=="LMR_SWEEP_REJECTION":rev.append(t)
        else:cont.append(t)
    combined=sorted((*rev,*cont),key=lambda t:(ensure_utc(t.entry_at),t.strategy_id))
    return {"LMR_SWEEP_REJECTION":tuple(rev),"LMR_ACCEPTED_BREAK":tuple(cont),"LMR_COMBINED":tuple(combined)}


def _metrics(trades):return compute_metrics(tuple(trades)).payload()
def _period(trades,start,end):
    a,b=ensure_utc(start),ensure_utc(end);return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)
def _capital(trades,*,broker_spec,leverage_tiers):
    return _simulate(trades,spec=broker_spec,tiers=leverage_tiers,starting_balance=100.0,account_leverage=100.0,margin_cap_pct=50.0)


def evaluate_v146(rows:Sequence[Bar],*,evaluation_end,pip_size,costs,broker_spec,leverage_tiers):
    end=ensure_utc(evaluation_end)
    routes=simulate_lmr(rows,costs=costs,pip_size=pip_size)
    out={}
    for cid,trades in routes.items():
        full=_period(trades,START,end);recent=_period(trades,RECENT,end)
        out[cid]={
            "full_metrics":_metrics(full),"recent_metrics":_metrics(recent),
            "full_live100":_capital(full,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
            "recent_live100":_capital(recent,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
            "long_metrics":_metrics(tuple(t for t in full if t.direction=="LONG")),
            "short_metrics":_metrics(tuple(t for t in full if t.direction=="SHORT")),
        }
    return {
        "research_version":RESEARCH_VERSION,"artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,"execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,"live_execution_enabled":False,
        "contract":{
            "strategy":"Liquidity Memory Router (LMR)",
            "sources":["PDH/PDL","PWH/PWL","two-H1-confirmed swing high/low"],
            "all_source_base_weights_equal":True,
            "memory_strength":"(1 + min(previous_bounces,3)) * 2^(-age_days/5)",
            "memory_half_life_days":MEMORY_HALF_LIFE_DAYS,
            "max_pool_age_days":MAX_POOL_AGE_DAYS,
            "touch_tolerance_atr":TOUCH_TOL_ATR,
            "touch_rejection_atr":TOUCH_REJECTION_ATR,
            "touch_cooldown_bars":TOUCH_COOLDOWN_BARS,
            "consumption":"accepted cross >= V144 ACCEPT_ATR after event evaluation",
            "event_rules":"same V144 sweep/accept/displacement/MSS/context logic",
            "target":"next active persistent liquidity pool with >=1.5R",
            "threshold_grid_search":False,"calendar_routing":False,"future_outcome_routing":False,
            "capital":"$100 / 1:100 / 20% risk / 50% margin cap",
            "execution_authority":False,
        },
        "candidates":out,
        "note":"V146 was preregistered from independent support/resistance persistence evidence before V145 forensic results were read.",
    }
