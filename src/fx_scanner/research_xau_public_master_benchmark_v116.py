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



def _m15_by_utc_day(rows:Sequence[Bar])->dict[tuple[int,int,int],tuple[Bar,...]]:
    buckets:dict[tuple[int,int,int],list[Bar]]={}
    for bar in sorted((x for x in rows if x.timeframe.upper()=="M15"),key=lambda x:ensure_utc(x.timestamp)):
        t=ensure_utc(bar.timestamp)
        buckets.setdefault((t.year,t.month,t.day),[]).append(bar)
    return {k:tuple(v) for k,v in buckets.items()}


def _day_key(ts)->tuple[int,int,int]:
    t=ensure_utc(ts)
    return (t.year,t.month,t.day)


def _first_touch_direction(day_bars:Sequence[Bar],buy_level:float,sell_level:float):
    for idx,bar in enumerate(day_bars):
        buy_hit=float(bar.high)>=float(buy_level)
        sell_hit=float(bar.low)<=float(sell_level)
        if buy_hit and sell_hit:
            return "AMBIGUOUS",idx
        if buy_hit:
            return "LONG",idx
        if sell_hit:
            return "SHORT",idx
    return None,None

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


def simulate_turtle_s2(
    rows:Sequence[AggBar],
    m15_rows:Sequence[Bar],
    costs:M15ResearchCosts,
)->tuple[TournamentTrade,...]:
    # Public Turtle S2 signal rules: 55-day breakout, 20-day opposite exit,
    # N=20D Wilder ATR, initial stop 2N. Single-unit benchmark only.
    # Breakout side is resolved from causal M15 first-touch order.
    tr=_tr(rows);n20=_wilder(tr,20);intraday=_m15_by_utc_day(m15_rows)
    trades=[];i=55
    while i<len(rows)-1:
        n=n20[i-1]
        if n is None or n<=0:
            i+=1;continue
        upper=max(float(x.high) for x in rows[i-55:i])
        lower=min(float(x.low) for x in rows[i-55:i])
        day=intraday.get(_day_key(rows[i].timestamp),())
        direction,touch_idx=_first_touch_direction(day,upper,lower)
        if direction in (None,"AMBIGUOUS"):
            i+=1;continue
        entry=upper if direction=="LONG" else lower
        stop=entry-2*n if direction=="LONG" else entry+2*n

        # After the first causal touch, inspect remaining M15 bars that day.
        same_day_stop=False
        if touch_idx is not None:
            for k,bar in enumerate(day[touch_idx:]):
                if direction=="LONG":
                    stop_hit=float(bar.low)<=stop
                else:
                    stop_hit=float(bar.high)>=stop
                if stop_hit:
                    same_day_stop=True
                    break
        if same_day_stop:
            cst=_cost_r(2*n,0.0,costs)
            trades.append(_mk_trade(
                TURTLE_S2_ID,direction,rows[i].timestamp,day[touch_idx].timestamp,
                day[touch_idx+k].timestamp,i,i,entry,stop,n,stop,0,-1,cst,0,
                "2N_STOP_SAME_DAY_M15_CAUSAL"
            ))
            i+=1;continue

        done=False
        for j in range(i+1,len(rows)):
            exit_channel=(
                min(float(x.low) for x in rows[max(0,j-20):j])
                if direction=="LONG"
                else max(float(x.high) for x in rows[max(0,j-20):j])
            )
            if direction=="LONG":
                if float(rows[j].low)<=stop:
                    exitp=stop;reason="2N_STOP"
                elif float(rows[j].low)<=exit_channel:
                    exitp=exit_channel;reason="20D_OPPOSITE_EXIT"
                else:
                    continue
                gross=(exitp-entry)/(2*n)
            else:
                if float(rows[j].high)>=stop:
                    exitp=stop;reason="2N_STOP"
                elif float(rows[j].high)>=exit_channel:
                    exitp=exit_channel;reason="20D_OPPOSITE_EXIT"
                else:
                    continue
                gross=(entry-exitp)/(2*n)
            hold=j-i;cst=_cost_r(2*n,hold,costs)
            trades.append(_mk_trade(
                TURTLE_S2_ID,direction,rows[i].timestamp,day[touch_idx].timestamp,
                rows[j].timestamp,i,j,entry,exitp,n,stop,0,gross,cst,hold,reason
            ))
            i=j+1;done=True;break
        if not done:
            i+=1
    return tuple(trades)


def simulate_crabel_nr4(
    rows:Sequence[AggBar],
    m15_rows:Sequence[Bar],
    costs:M15ResearchCosts,
)->tuple[TournamentTrade,...]:
    # Classic NR4 + next-day ORB clean-room encoding.
    # The trigger side is determined by actual M15 first-touch sequence.
    # Only a double-touch inside the same M15 bar is treated as unknowable.
    trades=[];ranges=[float(x.high)-float(x.low) for x in rows]
    intraday=_m15_by_utc_day(m15_rows)
    for i in range(10,len(rows)-1):
        if not (ranges[i]<=min(ranges[i-3:i])):
            continue
        j=i+1
        stretch_vals=[
            min(abs(float(x.high)-float(x.open)),abs(float(x.open)-float(x.low)))
            for x in rows[j-10:j]
        ]
        stretch=sum(stretch_vals)/len(stretch_vals)
        if not isfinite(stretch) or stretch<=0:
            continue
        buy=float(rows[j].open)+stretch
        sell=float(rows[j].open)-stretch
        day=intraday.get(_day_key(rows[j].timestamp),())
        direction,touch_idx=_first_touch_direction(day,buy,sell)
        if direction in (None,"AMBIGUOUS"):
            continue
        entry=buy if direction=="LONG" else sell
        exitp=float(rows[j].close)
        gross=(exitp-entry)/stretch if direction=="LONG" else (entry-exitp)/stretch
        cst=_cost_r(stretch,0.0,costs)
        entry_at=day[touch_idx].timestamp if touch_idx is not None else rows[j].timestamp
        trades.append(_mk_trade(
            CRABEL_NR4_ID,direction,rows[i].timestamp,entry_at,rows[j].timestamp,
            i,j,entry,exitp,stretch,0,0,gross,cst,0,"M15_FIRST_TOUCH_TO_DAY_CLOSE"
        ))
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
        TURTLE_S2_ID:simulate_turtle_s2(d1,rows,costs),
        RASCHKE_GRAIL_ID:simulate_holy_grail(h1,costs),
        CRABEL_NR4_ID:simulate_crabel_nr4(d1,rows,costs),
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
            "turtle_s2":"55D breakout / 20D opposite exit / 20D Wilder N / 2N stop; M15 causal first-touch entry sequencing; single-unit signal benchmark, no pyramiding",
            "raschke_holy_grail":"mechanical clean-room encoding of public ADX14>30+rising / EMA20 first-pullback concept; not claimed identical to discretionary execution",
            "crabel_nr4":"classic NR4 next-day ORB using 10D average open-to-nearest-extreme stretch; trigger side resolved by M15 first-touch; only same-M15 double-touch ambiguity skipped; same-day close exit",
            "parameter_search":False,
            "calendar_year_used_for_routing":False,
        },
        "strategies":out,
        "note":"V116 is a public-rule benchmark, not a promotion test. Famous-trader attribution is limited to documented concepts; adaptations are explicitly labelled clean-room.",
    }
