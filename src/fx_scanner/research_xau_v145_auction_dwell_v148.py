from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_hierarchical_regime_router_v35 import _Asof, build_d1_context
from .research_xau_liquidity_cartography_v144 import (
    ACCEPT_ATR,
    DISPLACEMENT_BODY_ATR,
    MAX_HOLD_BARS,
    MIN_TARGET_R,
    MSS_LOOKBACK,
    STOP_BUFFER_ATR,
    SWEEP_ATR,
    Setup,
    _confirmed_h1_swings,
    _context_ok,
    _daily_weekly_levels,
    _frame,
    _make_trade,
    _pools_at,
)

RESEARCH_VERSION="XAU_AUCTION_DWELL_ROUTER_V148"
ARTIFACT_CONTRACT="XAU_AUCTION_DWELL_ROUTER_V148_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

START=datetime(2012,1,1,tzinfo=timezone.utc)
RECENT=datetime(2025,1,1,tzinfo=timezone.utc)

CONFIRM_BARS=4
MIN_DWELL_CLOSES=3
DWELL_MARGIN_ATR=0.05

CANDIDATES=("ADR_DWELL_REJECTION","ADR_DWELL_ACCEPTANCE","ADR_COMBINED")


def _first_obstacle(pools,*,direction:str,entry:float,stop:float):
    risk=abs(entry-stop)
    if risk<=0:return None
    if direction=="LONG":
        vals=sorted(p.level for p in pools if p.level>entry)
    else:
        vals=sorted((p.level for p in pools if p.level<entry),reverse=True)
    if not vals:return None
    level=float(vals[0])
    return level if abs(level-entry)/risk>=MIN_TARGET_R else None


def extract_adr_setups(rows:Sequence[Bar])->tuple[Setup,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    f=_frame(bars)
    day_map,week_map=_daily_weekly_levels(f)
    d1_lookup=_Asof(build_d1_context(bars))
    h1_lookup=_Asof(_confirmed_h1_swings(bars))
    setups=[]
    cooldown_until=-1

    for i in range(250,len(bars)-CONFIRM_BARS-2):
        if i<=cooldown_until:continue
        b=bars[i];ts=ensure_utc(b.timestamp);atr=float(f.iloc[i]["atr14"])
        if not isfinite(atr) or atr<=0:continue
        prior=float(bars[i-1].close)
        h1_event=h1_lookup.row(ts)
        upper,lower=_pools_at(ts=ts,price=prior,day_map=day_map,week_map=week_map,h1_row=h1_event)
        upper=sorted(upper,key=lambda p:p.level-prior)
        lower=sorted(lower,key=lambda p:prior-p.level)
        if not upper and not lower:continue

        prev_lows=[float(x.low) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        prev_highs=[float(x.high) for x in bars[max(0,i-MSS_LOOKBACK):i]]
        if len(prev_lows)<MSS_LOOKBACK:continue

        confirm=bars[i+1:i+1+CONFIRM_BARS]
        signal_i=i+CONFIRM_BARS
        signal_ts=ensure_utc(bars[signal_i].timestamp)
        entry_i=signal_i+1
        if entry_i>=len(bars):continue
        d1=d1_lookup.row(signal_ts);h1=h1_lookup.row(signal_ts)

        made=False
        # Sweep then persistent rejection. The event candle need not itself close
        # back inside; the auction state is decided by the following four closes.
        for pool,direction in [
            *(([upper[0],"SHORT"],) if upper else ()),
            *(([lower[0],"LONG"],) if lower else ()),
        ]:
            if direction=="SHORT":
                swept=float(b.high)>=pool.level+SWEEP_ATR*atr
                dwell=sum(float(x.close)<=pool.level-DWELL_MARGIN_ATR*atr for x in confirm)
                no_reaccept=all(float(x.close)<pool.level+DWELL_MARGIN_ATR*atr for x in confirm)
                final_ok=float(confirm[-1].close)<=pool.level-DWELL_MARGIN_ATR*atr and float(confirm[-1].close)<min(prev_lows)
                displacement=float(b.high)-float(confirm[-1].close)>=DISPLACEMENT_BODY_ATR*atr
            else:
                swept=float(b.low)<=pool.level-SWEEP_ATR*atr
                dwell=sum(float(x.close)>=pool.level+DWELL_MARGIN_ATR*atr for x in confirm)
                no_reaccept=all(float(x.close)>pool.level-DWELL_MARGIN_ATR*atr for x in confirm)
                final_ok=float(confirm[-1].close)>=pool.level+DWELL_MARGIN_ATR*atr and float(confirm[-1].close)>max(prev_highs)
                displacement=float(confirm[-1].close)-float(b.low)>=DISPLACEMENT_BODY_ATR*atr
            if not(swept and dwell>=MIN_DWELL_CLOSES and no_reaccept and final_ok and displacement):
                continue
            if not _context_ok(d1,h1,direction,strict=False):continue
            entry=float(bars[entry_i].open)
            event_window=bars[i:signal_i+1]
            stop=max(float(x.high) for x in event_window)+STOP_BUFFER_ATR*atr if direction=="SHORT" else min(float(x.low) for x in event_window)-STOP_BUFFER_ATR*atr
            up2,lo2=_pools_at(ts=signal_ts,price=entry,day_map=day_map,week_map=week_map,h1_row=h1)
            target=_first_obstacle(up2 if direction=="LONG" else lo2,direction=direction,entry=entry,stop=stop)
            if target is None:continue
            setups.append(Setup("ADR_DWELL_REJECTION",direction,signal_i,entry_i,entry,stop,target,atr,pool.kind,pool.level,float(dwell)/CONFIRM_BARS))
            cooldown_until=signal_i+2;made=True;break
        if made:continue

        # Cross then dwell acceptance. One close is not enough: at least 3/4
        # subsequent closes must stay beyond the level, with no strong opposite close.
        for pool,direction in [
            *(([upper[0],"LONG"],) if upper else ()),
            *(([lower[0],"SHORT"],) if lower else ()),
        ]:
            body=abs(float(b.close)-float(b.open))
            if direction=="LONG":
                crossed=float(b.close)>=pool.level+ACCEPT_ATR*atr and float(b.close)>float(b.open)
                dwell=sum(float(x.close)>=pool.level+DWELL_MARGIN_ATR*atr for x in confirm)
                no_reject=all(float(x.close)>pool.level-DWELL_MARGIN_ATR*atr for x in confirm)
                final_ok=float(confirm[-1].close)>=pool.level+DWELL_MARGIN_ATR*atr
            else:
                crossed=float(b.close)<=pool.level-ACCEPT_ATR*atr and float(b.close)<float(b.open)
                dwell=sum(float(x.close)<=pool.level-DWELL_MARGIN_ATR*atr for x in confirm)
                no_reject=all(float(x.close)<pool.level+DWELL_MARGIN_ATR*atr for x in confirm)
                final_ok=float(confirm[-1].close)<=pool.level-DWELL_MARGIN_ATR*atr
            if not(crossed and body>=DISPLACEMENT_BODY_ATR*atr and dwell>=MIN_DWELL_CLOSES and no_reject and final_ok):
                continue
            if not _context_ok(d1,h1,direction,strict=True):continue
            entry=float(bars[entry_i].open)
            event_window=bars[i:signal_i+1]
            stop=min(float(x.low) for x in event_window)-STOP_BUFFER_ATR*atr if direction=="LONG" else max(float(x.high) for x in event_window)+STOP_BUFFER_ATR*atr
            up2,lo2=_pools_at(ts=signal_ts,price=entry,day_map=day_map,week_map=week_map,h1_row=h1)
            target=_first_obstacle(up2 if direction=="LONG" else lo2,direction=direction,entry=entry,stop=stop)
            if target is None:continue
            setups.append(Setup("ADR_DWELL_ACCEPTANCE",direction,signal_i,entry_i,entry,stop,target,atr,pool.kind,pool.level,float(dwell)/CONFIRM_BARS))
            cooldown_until=signal_i+2;break

    return tuple(setups)


def simulate_adr(rows:Sequence[Bar],*,costs,pip_size:float)->dict[str,tuple[TournamentTrade,...]]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    rej=[];acc=[]
    for s in extract_adr_setups(bars):
        t=_make_trade(bars,s,costs=costs,pip_size=pip_size)
        if t is None:continue
        if s.family=="ADR_DWELL_REJECTION":rej.append(t)
        else:acc.append(t)
    combined=sorted((*rej,*acc),key=lambda t:(ensure_utc(t.entry_at),t.strategy_id))
    return {"ADR_DWELL_REJECTION":tuple(rej),"ADR_DWELL_ACCEPTANCE":tuple(acc),"ADR_COMBINED":tuple(combined)}


def _metrics(trades):return compute_metrics(tuple(trades)).payload()
def _period(trades,start,end):
    a,b=ensure_utc(start),ensure_utc(end);return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)
def _capital(trades,*,broker_spec,leverage_tiers):
    return _simulate(trades,spec=broker_spec,tiers=leverage_tiers,starting_balance=100.0,account_leverage=100.0,margin_cap_pct=50.0)


def evaluate_v148(rows:Sequence[Bar],*,evaluation_end,pip_size,costs,broker_spec,leverage_tiers):
    end=ensure_utc(evaluation_end);routes=simulate_adr(rows,costs=costs,pip_size=pip_size);out={}
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
            "strategy":"Auction Dwell Router (ADR)",
            "liquidity_sources":"same objective V144 PD/PW/H1-confirmed pools",
            "confirm_bars":CONFIRM_BARS,"minimum_dwell_closes":MIN_DWELL_CLOSES,
            "dwell_margin_atr":DWELL_MARGIN_ATR,
            "acceptance":"initial cross plus 3/4 subsequent closes on accepted side, no strong opposite close",
            "rejection":"initial sweep plus 3/4 subsequent closes on rejected side, final MSS confirmation",
            "entry":"next M15 open after four completed confirmation bars",
            "stop":"event+confirmation structural extreme plus V144 0.10 ATR buffer",
            "target":"nearest mapped liquidity obstacle only; skip if nearest obstacle offers <1.5R",
            "threshold_grid_search":False,"calendar_routing":False,"future_outcome_routing":False,
            "capital":"$100 / 1:100 / 20% risk / 50% margin cap","execution_authority":False,
        },
        "candidates":out,
        "note":"V148 replaces one-candle acceptance/rejection with an observable multi-bar auction state and corrects target semantics so nearer liquidity cannot be skipped.",
    }
