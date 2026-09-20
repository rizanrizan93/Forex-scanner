from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="XAU_PUBLIC_MASTER_BENCHMARK_V116"
ARTIFACT_CONTRACT="XAU_PUBLIC_MASTER_BENCHMARK_V116_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

PIP_SIZE=0.01
TURTLE_S2_ID="RICHARD_DENNIS_ECKHARDT_TURTLE_S2_SINGLE_UNIT"
RASCHKE_GRAIL_ID="LINDA_RASCHKE_HOLY_GRAIL_H1_CLEANROOM"
CRABEL_NR4_ID="TOBY_CRABEL_NR4_ORB_CLASSIC_CLEANROOM"


@dataclass(frozen=True, slots=True)
class AggBar:
    symbol:str
    timeframe:str
    timestamp:Any
    open:float
    high:float
    low:float
    close:float
    spread_avg:float


def _aggregate(rows:Sequence[Bar], timeframe:str)->tuple[AggBar,...]:
    src=tuple(sorted((x for x in rows if x.timeframe.upper()=="M15"),key=lambda x:ensure_utc(x.timestamp)))
    groups={}
    order=[]
    for b in src:
        t=ensure_utc(b.timestamp)
        if timeframe=="D1":
            key=(t.year,t.month,t.day)
            stamp=datetime(t.year,t.month,t.day,tzinfo=timezone.utc)
        elif timeframe=="H1":
            key=(t.year,t.month,t.day,t.hour)
            stamp=datetime(t.year,t.month,t.day,t.hour,tzinfo=timezone.utc)
        else:
            raise ValueError("V116_BAD_TIMEFRAME")
        if key not in groups:
            groups[key]={
                "timestamp":stamp,"open":float(b.open),"high":float(b.high),"low":float(b.low),
                "close":float(b.close),"spread_sum":0.0,"n":0,
            }
            order.append(key)
        g=groups[key]
        g["high"]=max(g["high"],float(b.high))
        g["low"]=min(g["low"],float(b.low))
        g["close"]=float(b.close)
        g["spread_sum"]+=float(b.spread_avg)
        g["n"]+=1
    out=[]
    for key in order:
        g=groups[key]
        out.append(AggBar(
            "XAUUSD",timeframe,g["timestamp"],g["open"],g["high"],g["low"],g["close"],
            g["spread_sum"]/max(1,g["n"])
        ))
    return tuple(out)


def _tr(rows):
    out=[]
    prev=None
    for x in rows:
        v=float(x.high)-float(x.low)
        if prev is not None:
            v=max(v,abs(float(x.high)-prev),abs(float(x.low)-prev))
        out.append(v);prev=float(x.close)
    return out


def _wilder(values,period:int):
    out=[None]*len(values)
    if len(values)<period:return out
    seed=sum(float(x) for x in values[:period])/period
    out[period-1]=seed
    last=seed
    for i in range(period,len(values)):
        last=((period-1)*last+float(values[i]))/period
        out[i]=last
    return out


def _ema(values,period:int):
    out=[]
    alpha=2.0/(period+1.0)
    last=float(values[0])
    for v in values:
        last=alpha*float(v)+(1-alpha)*last
        out.append(last)
    return out


def _adx(rows,period:int=14):
    n=len(rows)
    tr=[0.0]*n;plus=[0.0]*n;minus=[0.0]*n
    for i,x in enumerate(rows):
        if i==0:
            tr[i]=float(x.high)-float(x.low);continue
        prev=rows[i-1]
        tr[i]=max(float(x.high)-float(x.low),abs(float(x.high)-float(prev.close)),abs(float(x.low)-float(prev.close)))
        up=float(x.high)-float(prev.high)
        dn=float(prev.low)-float(x.low)
        plus[i]=up if up>dn and up>0 else 0.0
        minus[i]=dn if dn>up and dn>0 else 0.0
    atr=_wilder(tr,period);pdm=_wilder(plus,period);mdm=_wilder(minus,period)
    pdi=[None]*n;mdi=[None]*n;dx=[0.0]*n
    for i in range(n):
        if atr[i] is None or atr[i]<=0 or pdm[i] is None or mdm[i] is None:continue
        pdi[i]=100*pdm[i]/atr[i];mdi[i]=100*mdm[i]/atr[i]
        den=pdi[i]+mdi[i]
        dx[i]=0.0 if den<=0 else 100*abs(pdi[i]-mdi[i])/den
    adx=_wilder(dx,period)
    return adx,pdi,mdi


def _cost_r(risk_price:float,hold_days:float,costs:M15ResearchCosts)->float:
    risk_pips=abs(float(risk_price))/PIP_SIZE
    if risk_pips<=0:return 0.0
    pips=(
        float(costs.spread_pips)*float(costs.spread_multiplier)
        +float(costs.slippage_pips)*float(costs.slippage_multiplier)
        +float(costs.commission_pips_round_trip)
        +float(costs.swap_pips_per_day)*max(0.0,float(hold_days))
    )
    return pips/risk_pips


def _mk_trade(strategy_id,direction,signal,entry_at,exit_at,si,ei,entry,exitp,atr,stop,target,gross_r,cost_r,bars_held,reason):
    return TournamentTrade(
        strategy_id,"XAUUSD",direction,signal,entry_at,exit_at,si,ei,
        float(entry),float(exitp),float(atr),float(stop),float(target),
        float(gross_r),float(cost_r),float(gross_r-cost_r),int(bars_held),reason
    )


def simulate_turtle_s2(rows:Sequence[AggBar],costs:M15ResearchCosts)->tuple[TournamentTrade,...]:
    # Public Turtle S2 signal rules: 55-day breakout, 20-day opposite exit, N=20D Wilder ATR,
    # initial stop 2N. This benchmark is deliberately single-unit: no 0.5N pyramiding/portfolio sizing.
    tr=_tr(rows);n20=_wilder(tr,20)
    trades=[];i=55
    while i<len(rows)-1:
        n=n20[i-1]
        if n is None or n<=0:i+=1;continue
        upper=max(x.high for x in rows[i-55:i]);lower=min(x.low for x in rows[i-55:i])
        long_hit=rows[i].high>upper;short_hit=rows[i].low<lower
        if long_hit==short_hit:
            i+=1;continue
        direction="LONG" if long_hit else "SHORT"
        entry=upper if long_hit else lower
        stop=entry-2*n if long_hit else entry+2*n
        # Same-day initial-stop ambiguity is treated stop-first.
        if (long_hit and rows[i].low<=stop) or (short_hit and rows[i].high>=stop):
            c=_cost_r(2*n,0.0,costs)
            trades.append(_mk_trade(TURTLE_S2_ID,direction,rows[i].timestamp,rows[i].timestamp,rows[i].timestamp,i,i,entry,stop,n,stop,0,-1,c,0,"STOP_FIRST_ENTRY_DAY"))
            i+=1;continue
        done=False
        for j in range(i+1,len(rows)):
            exit_channel=(
                min(x.low for x in rows[max(0,j-20):j])
                if direction=="LONG"
                else max(x.high for x in rows[max(0,j-20):j])
            )
            if direction=="LONG":
                if rows[j].low<=stop:
                    exitp=stop;reason="2N_STOP"
                elif rows[j].low<=exit_channel:
                    exitp=exit_channel;reason="20D_OPPOSITE_EXIT"
                else:
                    continue
                gross=(exitp-entry)/(2*n)
            else:
                if rows[j].high>=stop:
                    exitp=stop;reason="2N_STOP"
                elif rows[j].high>=exit_channel:
                    exitp=exit_channel;reason="20D_OPPOSITE_EXIT"
                else:
                    continue
                gross=(entry-exitp)/(2*n)
            hold=j-i;c=_cost_r(2*n,hold,costs)
            trades.append(_mk_trade(TURTLE_S2_ID,direction,rows[i].timestamp,rows[i].timestamp,rows[j].timestamp,i,j,entry,exitp,n,stop,0,gross,c,hold,reason))
            i=j+1;done=True;break
        if not done:i+=1
    return tuple(trades)


def simulate_crabel_nr4(rows:Sequence[AggBar],costs:M15ResearchCosts)->tuple[TournamentTrade,...]:
    # Classic published NR4 + ORB clean-room encoding:
    # setup day is narrowest of last 4; following day uses Crabel's classic 10-day
    # average "stretch" = distance from open to closest daily extreme; exit at same-day close.
    trades=[]
    ranges=[x.high-x.low for x in rows]
    for i in range(10,len(rows)-1):
        if not (ranges[i]<=min(ranges[i-3:i])):
            continue
        j=i+1
        stretch_vals=[min(abs(x.high-x.open),abs(x.open-x.low)) for x in rows[j-10:j]]
        stretch=sum(stretch_vals)/len(stretch_vals)
        if not isfinite(stretch) or stretch<=0:continue
        buy=rows[j].open+stretch;sell=rows[j].open-stretch
        lh=rows[j].high>=buy;sh=rows[j].low<=sell
        if lh==sh:continue  # no intraday sequence -> do not choose with hindsight
        direction="LONG" if lh else "SHORT"
        entry=buy if lh else sell
        exitp=rows[j].close
        gross=(exitp-entry)/stretch if lh else (entry-exitp)/stretch
        c=_cost_r(stretch,0.0,costs)
        trades.append(_mk_trade(CRABEL_NR4_ID,direction,rows[i].timestamp,rows[j].timestamp,rows[j].timestamp,i,j,entry,exitp,stretch,0,0,gross,c,0,"SAME_DAY_CLOSE"))
    return tuple(trades)


def simulate_holy_grail(rows:Sequence[AggBar],costs:M15ResearchCosts)->tuple[TournamentTrade,...]:
    # Mechanical encoding of Raschke's public setup, not a claim to reproduce discretionary management:
    # ADX14 >30 and rising -> first pullback to EMA20 -> stop-entry beyond pullback bar -> structural stop;
    # target prior impulse extreme. One setup per ADX >30 episode, no re-entry.
    closes=[x.close for x in rows];ema20=_ema(closes,20);adx,pdi,mdi=_adx(rows,14)
    trades=[];armed=False;used=False;direction=None;impulse_extreme=None;i=30
    while i<len(rows)-2:
        a=adx[i]
        prev=adx[i-1] if i>0 else None
        if a is None or prev is None:
            i+=1;continue
        if a<30:
            armed=False;used=False;direction=None;impulse_extreme=None;i+=1;continue
        if not armed and a>30 and a>prev:
            direction="LONG" if rows[i].close>=ema20[i] else "SHORT"
            armed=True;used=False
            impulse_extreme=rows[i].high if direction=="LONG" else rows[i].low
            i+=1;continue
        if not armed or used:
            i+=1;continue
        if direction=="LONG":
            impulse_extreme=max(float(impulse_extreme),rows[i].high)
            touch=rows[i].low<=ema20[i]<=rows[i].high
        else:
            impulse_extreme=min(float(impulse_extreme),rows[i].low)
            touch=rows[i].low<=ema20[i]<=rows[i].high
        if not touch:
            i+=1;continue
        setup=i;trigger=rows[setup].high if direction=="LONG" else rows[setup].low
        stop=rows[setup].low if direction=="LONG" else rows[setup].high
        risk=trigger-stop if direction=="LONG" else stop-trigger
        target=float(impulse_extreme)
        valid_target=(target>trigger) if direction=="LONG" else (target<trigger)
        used=True
        if risk<=0 or not valid_target:
            i+=1;continue
        entry_bar=rows[setup+1]
        filled=entry_bar.high>=trigger if direction=="LONG" else entry_bar.low<=trigger
        if not filled:
            i+=1;continue
        # Conservative entry-bar ambiguity: stop counts, target does not.
        if (direction=="LONG" and entry_bar.low<=stop) or (direction=="SHORT" and entry_bar.high>=stop):
            c=_cost_r(risk,0.0,costs)
            trades.append(_mk_trade(RASCHKE_GRAIL_ID,direction,rows[setup].timestamp,entry_bar.timestamp,entry_bar.timestamp,setup,setup+1,trigger,stop,risk,stop,target,-1,c,0,"STOP_FIRST_ENTRY_BAR"))
            i=setup+2;continue
        done=False
        for j in range(setup+2,min(len(rows),setup+2+120)):
            if direction=="LONG":
                stop_hit=rows[j].low<=stop;target_hit=rows[j].high>=target
            else:
                stop_hit=rows[j].high>=stop;target_hit=rows[j].low<=target
            if stop_hit:
                exitp=stop;reason="STRUCTURAL_STOP"
            elif target_hit:
                exitp=target;reason="PRIOR_IMPULSE_TARGET"
            elif adx[j] is not None and adx[j]<30:
                exitp=rows[j].close;reason="ADX_LOST_30"
            else:
                continue
            gross=(exitp-trigger)/risk if direction=="LONG" else (trigger-exitp)/risk
            hold=j-(setup+1);c=_cost_r(risk,hold/24.0,costs)
            trades.append(_mk_trade(RASCHKE_GRAIL_ID,direction,rows[setup].timestamp,entry_bar.timestamp,rows[j].timestamp,setup,j,trigger,exitp,risk,stop,target,gross,c,hold,reason))
            i=j+1;done=True;break
        if not done:i+=1
    return tuple(trades)


def _period(trades,start,end):
    a=ensure_utc(start);b=ensure_utc(end)
    return tuple(x for x in trades if a<=ensure_utc(x.entry_at)<b)


def evaluate_v116(
    rows:Sequence[Bar],*,costs:M15ResearchCosts,evaluation_start,evaluation_end,
    era_windows:Mapping[str,tuple[Any,Any]],
)->dict[str,Any]:
    d1=_aggregate(rows,"D1");h1=_aggregate(rows,"H1")
    start=ensure_utc(evaluation_start);end=ensure_utc(evaluation_end)
    all_trades={
        TURTLE_S2_ID:simulate_turtle_s2(d1,costs),
        RASCHKE_GRAIL_ID:simulate_holy_grail(h1,costs),
        CRABEL_NR4_ID:simulate_crabel_nr4(d1,costs),
    }
    out={}
    for name,trades in all_trades.items():
        ev=_period(trades,start,end)
        eras={k:compute_metrics(_period(trades,a,b)).payload() for k,(a,b) in era_windows.items()}
        annual={}
        for y in range(start.year,end.year+1):
            a=datetime(y,1,1,tzinfo=start.tzinfo);b=min(datetime(y+1,1,1,tzinfo=start.tzinfo),end)
            if a<end:annual[str(y)]=compute_metrics(_period(trades,a,b)).payload()
        out[name]={
            "full":compute_metrics(ev).payload(),
            "eras":eras,
            "annual":annual,
            "trade_count_raw":len(trades),
        }
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "contract":{
            "data":"Dukascopy XAUUSD BID M15 aggregated causally to UTC H1/D1",
            "costs":"provided stress model deducted in normalized R units",
            "turtle_s2":"55D breakout / 20D opposite exit / 20D Wilder N / 2N stop; single-unit signal benchmark, no pyramiding",
            "raschke_holy_grail":"mechanical clean-room encoding of public ADX14>30+rising / EMA20 first-pullback concept; not claimed identical to discretionary execution",
            "crabel_nr4":"classic NR4 next-day ORB using 10D average open-to-nearest-extreme stretch; ambiguous two-sided trigger days skipped; same-day close exit",
            "parameter_search":False,
            "calendar_year_used_for_routing":False,
        },
        "strategies":out,
        "note":"V116 is a public-rule benchmark, not a promotion test. Famous-trader attribution is limited to documented concepts; adaptations are explicitly labelled clean-room.",
    }
