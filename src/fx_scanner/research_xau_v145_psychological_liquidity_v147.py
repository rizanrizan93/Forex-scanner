from __future__ import annotations

from datetime import datetime, timezone
from math import floor, isfinite
from typing import Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_hierarchical_regime_router_v35 import _Asof, build_d1_context
from .research_xau_liquidity_cartography_v144 import (
    ACCEPT_ATR, DISPLACEMENT_BODY_ATR, MAX_HOLD_BARS, MIN_TARGET_R,
    MSS_LOOKBACK, RETEST_MAX_BARS, RETEST_TOL_ATR, STOP_BUFFER_ATR,
    SWEEP_ATR, Setup, _confirmed_h1_swings, _context_ok, _frame, _make_trade,
)

RESEARCH_VERSION="XAU_PSYCHOLOGICAL_LIQUIDITY_LATTICE_V147"
ARTIFACT_CONTRACT="XAU_PSYCHOLOGICAL_LIQUIDITY_LATTICE_V147_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START=datetime(2012,1,1,tzinfo=timezone.utc)
RECENT=datetime(2025,1,1,tzinfo=timezone.utc)

ROUND_STEP_USD=10.0
ROUND_50_USD=50.0
ROUND_100_USD=100.0
MAX_LATTICE_STEPS=20

CANDIDATES=("PLL_SWEEP_REJECTION","PLL_ACCEPTED_BREAK","PLL_COMBINED")


def _tier(level:float)->int:
    n=int(round(level))
    if abs(level/ROUND_100_USD-round(level/ROUND_100_USD))<1e-9:return 3
    if abs(level/ROUND_50_USD-round(level/ROUND_50_USD))<1e-9:return 2
    return 1


def _nearest_rounds(price:float)->tuple[float,float]:
    lo=floor(price/ROUND_STEP_USD)*ROUND_STEP_USD
    if abs(price-lo)<1e-9:
        return lo-ROUND_STEP_USD,lo+ROUND_STEP_USD
    return lo,lo+ROUND_STEP_USD


def _target_round(*,entry:float,stop:float,direction:str,crossed_level:float)->float|None:
    risk=abs(entry-stop)
    if risk<=0:return None
    tier=_tier(crossed_level)
    step={1:ROUND_STEP_USD,2:ROUND_50_USD,3:ROUND_100_USD}[tier]
    if direction=="LONG":
        k=floor(entry/step)+1
        for _ in range(MAX_LATTICE_STEPS):
            level=float(k*step)
            if level>entry and abs(level-entry)/risk>=MIN_TARGET_R:return level
            k+=1
    else:
        k=floor(entry/step)
        if abs(k*step-entry)<1e-9:k-=1
        for _ in range(MAX_LATTICE_STEPS):
            level=float(k*step)
            if level<entry and abs(entry-level)/risk>=MIN_TARGET_R:return level
            k-=1
    return None


def extract_pll_setups(rows:Sequence[Bar])->tuple[Setup,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    f=_frame(bars)
    d1_lookup=_Asof(build_d1_context(bars))
    h1_lookup=_Asof(_confirmed_h1_swings(bars))
    setups=[]
    cooldown_until=-1

    for i in range(250,len(bars)-RETEST_MAX_BARS-2):
        if i<=cooldown_until:continue
        b=bars[i];ts=ensure_utc(b.timestamp)
        atr=float(f.iloc[i]["atr14"])
        if not isfinite(atr) or atr<=0:continue
        prior=float(bars[i-1].close)
        lower,upper=_nearest_rounds(prior)
        d1=d1_lookup.row(ts);h1=h1_lookup.row(ts)
        body=abs(float(b.close)-float(b.open))
        prev_lows=[float(x.low) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        prev_highs=[float(x.high) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        if len(prev_lows)<MSS_LOOKBACK:continue

        made=False
        for level,direction in ((upper,"SHORT"),(lower,"LONG")):
            if direction=="SHORT":
                swept=float(b.high)>=level+SWEEP_ATR*atr
                rejected=float(b.close)<level and float(b.close)<float(b.open)
                mss=float(b.close)<min(prev_lows)
            else:
                swept=float(b.low)<=level-SWEEP_ATR*atr
                rejected=float(b.close)>level and float(b.close)>float(b.open)
                mss=float(b.close)>max(prev_highs)
            if not(swept and rejected and mss and body>=DISPLACEMENT_BODY_ATR*atr):continue
            if not _context_ok(d1,h1,direction,strict=False):continue
            entry_i=i+1;entry=float(bars[entry_i].open)
            stop=float(b.high)+STOP_BUFFER_ATR*atr if direction=="SHORT" else float(b.low)-STOP_BUFFER_ATR*atr
            target=_target_round(entry=entry,stop=stop,direction=direction,crossed_level=level)
            if target is None:continue
            setups.append(Setup("PLL_SWEEP_REJECTION",direction,i,entry_i,entry,stop,target,atr,f"ROUND_T{_tier(level)}",level,float(_tier(level))))
            cooldown_until=i+2;made=True;break

        if made:continue

        for level,direction in ((upper,"LONG"),(lower,"SHORT")):
            accepted=(float(b.close)>=level+ACCEPT_ATR*atr and float(b.close)>float(b.open)) if direction=="LONG" else (float(b.close)<=level-ACCEPT_ATR*atr and float(b.close)<float(b.open))
            if not(accepted and body>=DISPLACEMENT_BODY_ATR*atr):continue
            if not _context_ok(d1,h1,direction,strict=True):continue
            retest_i=None
            for j in range(i+1,min(len(bars),i+1+RETEST_MAX_BARS)):
                x=bars[j]
                touched=float(x.low)<=level+RETEST_TOL_ATR*atr and float(x.high)>=level-RETEST_TOL_ATR*atr
                held=float(x.close)>level if direction=="LONG" else float(x.close)<level
                if touched and held:
                    retest_i=j;break
            if retest_i is None or retest_i+1>=len(bars):continue
            entry_i=retest_i+1;entry=float(bars[entry_i].open)
            local=bars[max(i,retest_i-2):retest_i+1]
            stop=min(float(x.low) for x in local)-STOP_BUFFER_ATR*atr if direction=="LONG" else max(float(x.high) for x in local)+STOP_BUFFER_ATR*atr
            target=_target_round(entry=entry,stop=stop,direction=direction,crossed_level=level)
            if target is None:continue
            setups.append(Setup("PLL_ACCEPTED_BREAK",direction,retest_i,entry_i,entry,stop,target,atr,f"ROUND_T{_tier(level)}",level,float(_tier(level))))
            cooldown_until=retest_i+2;break
    return tuple(setups)


def simulate_pll(rows:Sequence[Bar],*,costs,pip_size:float)->dict[str,tuple[TournamentTrade,...]]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    rev=[];cont=[]
    for s in extract_pll_setups(bars):
        t=_make_trade(bars,s,costs=costs,pip_size=pip_size)
        if t is None:continue
        if s.family=="PLL_SWEEP_REJECTION":rev.append(t)
        else:cont.append(t)
    combined=sorted((*rev,*cont),key=lambda t:(ensure_utc(t.entry_at),t.strategy_id))
    return {"PLL_SWEEP_REJECTION":tuple(rev),"PLL_ACCEPTED_BREAK":tuple(cont),"PLL_COMBINED":tuple(combined)}


def _metrics(trades):return compute_metrics(tuple(trades)).payload()
def _period(trades,start,end):
    a,b=ensure_utc(start),ensure_utc(end);return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)
def _capital(trades,*,broker_spec,leverage_tiers):
    return _simulate(trades,spec=broker_spec,tiers=leverage_tiers,starting_balance=100.0,account_leverage=100.0,margin_cap_pct=50.0)


def evaluate_v147(rows:Sequence[Bar],*,evaluation_end,pip_size,costs,broker_spec,leverage_tiers):
    end=ensure_utc(evaluation_end);routes=simulate_pll(rows,costs=costs,pip_size=pip_size);out={}
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
            "strategy":"Psychological Liquidity Lattice (PLL)",
            "round_lattice_usd":[10.0,50.0,100.0],
            "tiers":"$10 minor, $50 major, $100 supermajor",
            "event_rules":"V144 sweep/accept/displacement/MSS/context mechanics",
            "target":"first same-tier-or-higher lattice level in direction satisfying >=1.5R",
            "no_gravity_filter":True,
            "threshold_grid_search":False,"calendar_routing":False,"future_outcome_routing":False,
            "capital":"$100 / 1:100 / 20% risk / 50% margin cap","execution_authority":False,
        },
        "candidates":out,
        "note":"V147 is an independent psychological-price-level family preregistered from price-clustering literature, not selected from V145 outcomes.",
    }
