"""RIZAN R32: predeclared XAUUSD profit × frequency ATR exits; READ ONLY.

Source: audited R30 2012-2026; select only on immediately prior TWO
fully matured calendar years. 2019-26 annually evaluated, 2026 partial.
No broker orders, no leverage, no account-compounding claims.

Entry decision is at candle close; entry is NEXT candle OPEN (a proxy,
not executable broker prices). Stops/targets are modelled using subsequent
bar OHLC. Stop takes precedence if stop and target touch in same bar.
Trailing level updates only AFTER a completed candle, and a stop gap
is filled at the next bar OPEN if worse. One active 1oz position per
timeframe. Commission/spread/slippage are hypothetical cost scenarios.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import r30_pareto_direction_search as source

TF_HOLDS={"1W":(2,3,4,6,8),"1D":(1,2,3,5,7),
          "4h":(1,2,3,4,6),"1h":(1,2,4)}
ENTRIES=("always","ema","ema_adx","ema_mom","ema_pullback",
         "ema_breakout","ema_pressure","ema_macd","ema_rejection")
EXITS=(
 ("fixed",0.,0.),("stop",1.5,0.),("stop",3.,0.),
 ("target",0.,3.),("target",0.,6.),
 ("trail",2.,0.),("trail",3.5,0.),
 ("bracket",1.5,4.),("bracket",2.5,6.),("bracket",3.,9.),
)
MODES=("max_net","max_signals","profit_frequency")
COST=(.7,2.,5.)
VALID_MIN={"1W":10,"1D":30,"4h":55,"1h":90}
OUT=Path("artifacts/r32")
CONTRACT="RIZAN_R32_PROFIT_AND_SIGNAL_FREQUENCY_2012_2026_V1"
REFERENCE="R31.1 W1 EMA BUY 4W / 75 trades / +2825.987 USD per 1oz, $2 assumed cost"

def masks(d,z,side):
    s=1 if side=="BUY" else -1
    ema=s*(z.ema8-z.ema21)>0
    adx=z.adx14>=18
    mom=s*z.roc3>0
    pressure=s*z.clv>.2
    wick=s*z.sweep5>0
    breakout=s*z.break8>0
    rsi=s*(z.rsi14-50)>0
    macd=s*z.macdh>0
    sources={
        "always":np.ones(len(d),dtype=bool),
        "ema":ema,"ema_adx":ema&adx,"ema_mom":ema&mom,
        "ema_pullback":ema&(~mom)&pressure,
        "ema_breakout":ema&breakout,
        "ema_pressure":ema&pressure,
        "ema_macd":ema&macd,
        "ema_rejection":ema&wick&pressure,
    }
    return {k:np.asarray(pd.Series(v).fillna(False),bool) for k,v in sources.items()}


def _gap_ok(idx,i,k,tf):
    """True only if all intermediate sampled bars belong to same trade."""
    if i+k>=len(idx):return False
    for j in range(i+1,i+k+1):
        gap=idx[j]-idx[j-1]
        if tf=="1W":
            if gap!=pd.Timedelta(days=7):return False
        elif tf=="1D":
            if not pd.Timedelta(days=1)<=gap<=pd.Timedelta(days=4):return False
        else:
            if gap!=pd.Timedelta(hours=1 if tf=="1h" else 4):return False
    return True


def exits(d,atr,tf,h,style,sl,tp):
    """Construct only future trade labels; no future candle used in signal mask.

    style: fixed, stop, target, trail, bracket.
    If both stop and target touch, adverse stop takes precedence.
    Trailing stop after completed bar high/low, effective NEXT bar.
    """
    n=len(d)
    o=d.o.to_numpy(float); hi=d.h.to_numpy(float)
    lo=d.l.to_numpy(float); c=d.c.to_numpy(float)
    idx=d.index
    entry=np.roll(o,-1)
    good=np.isfinite(entry)&np.isfinite(atr)&(atr>0)
    good[-h:]=False
    gross={};end_indices={}
    for side in ("BUY","SELL"):
        sign=1 if side=="BUY" else -1
        ret=np.full(n,np.nan)
        end=np.full(n,-1,dtype=np.int32)
        for i in np.flatnonzero(good):
            if not _gap_ok(idx,i,h,tf):continue
            ep=entry[i];offset=atr[i]
            stop=(ep-sign*sl*offset) if style in ("stop","bracket","trail") else None
            target=(ep+sign*tp*offset) if style in ("target","bracket") else None
            favorable=ep
            for k in range(1,h+1):
                j=i+k
                # Gap-to-stop fills at bar OPEN (worse price than stop).
                if stop is not None:
                    if (sign==1 and o[j]<=stop) or (sign==-1 and o[j]>=stop):
                        exitp=o[j];break
                    if (sign==1 and lo[j]<=stop) or (sign==-1 and hi[j]>=stop):
                        exitp=stop;break
                # If both stop and target traded, stop branch above wins.
                if target is not None and (
                    (sign==1 and hi[j]>=target) or (sign==-1 and lo[j]<=target)
                ):
                    exitp=target;break
                exitp=c[j]
                # Trail advance only from prior CLOSED bar for next bar.
                if style=="trail" and k<h:
                    favorable=(max(favorable,hi[j]) if sign==1
                               else min(favorable,lo[j]))
                    next_stop=favorable-sign*sl*offset
                    stop=max(stop,next_stop) if sign==1 else min(stop,next_stop)
            ret[i]=sign*(exitp-ep)
            end[i]=j
        gross[side]=ret
        end_indices[side]=end
    return gross,end_indices


def pick(signal,eligible,ends):
    """At most one open trade, signal i triggers entry at bar i+1."""
    indices=np.flatnonzero(signal&eligible&np.isfinite(ends)&(ends>=0))
    selected=[]
    last_exit=-1
    for i in indices:
        if i<last_exit:continue
        selected.append(int(i))
        last_exit=int(ends[i])
    return np.asarray(selected,dtype=np.int64)


def stats(indices,gross,cost=2.):
    if len(indices)==0:
        return {"n":0,"net":0.,"pf":None,"dd":0.,"win":None}
    pnl=np.asarray(gross[indices],float)-cost
    gain=pnl[pnl>0].sum()
    loss=-pnl[pnl<0].sum()
    eq=np.r_[0.,pnl.cumsum()]
    dd=float(np.max(np.maximum.accumulate(eq)-eq))
    return {"n":int(len(indices)),"net":float(pnl.sum()),
            "pf":float(gain/loss) if loss>0 else None,
            "dd":dd,"win":float(np.mean(pnl>0)),
            "mean":float(pnl.mean())}


def ranked(q,mode,plus_years,mintrades):
    if (q["n"]<mintrades or q["net"]<=0
            or (q["pf"] or 0)<=1.02):return None
    if mode=="max_net":
        return (q["net"],plus_years,q["n"])
    if mode=="max_signals":
        if q["net"]<5*q["n"]/4 or plus_years<1:return None
        return (q["n"],q["net"],-q["dd"])
    if mode=="profit_frequency":
        if plus_years<2:return None
        return (q["net"]*np.sqrt(q["n"])/(50+q["dd"]),q["net"],q["n"])
    raise ValueError("R32_INVALID_MODE")


def run(tf,mode):
    if tf not in TF_HOLDS or mode not in MODES:raise ValueError("R32_INVALID_TF_MODE")
    scope="spliced" if tf in ("4h","1h") else "archived"
    d,z,_,src_valid,times,provenance=source.read_data(
        {"1W":"1W","1D":"1D","4h":"4h","1h":"1h"}[tf],scope)
    if set(range(2012,2027))-set(provenance["actual_years"]):
        raise ValueError("R32_FULL_PRICE_2012_26_SOURCE_MISSING")
    atr=z.atr14.to_numpy(float)
    year=np.asarray(times.year,int)
    entry_masks={side:masks(d,z,side) for side in ("BUY","SELL")}
    # Keep tiny research receipt without storing hypothetical future labels.
    selected_by_year={y:None for y in range(2019,2027)}
    candidates=0
    for h,(style,sl,tp) in itertools.product(TF_HOLDS[tf],EXITS):
        gross,ends=exits(d,atr,tf,h,style,sl,tp)
        for side in ("BUY","SELL"):
            valid=src_valid & np.isfinite(gross[side])&(ends[side]>=0)
            # Maturity guard: signal close+exit candle must PRECEDE test boundary.
            endt=d.index.asi8[np.maximum(0,ends[side])].copy()
            closeoffset=pd.Timedelta(hours=1 if tf=="1h" else
                                    4 if tf=="4h" else
                                    24 if tf=="1D" else 168).value
            endt+=closeoffset
            for name,mask in entry_masks[side].items():
                candidates+=1
                policy={"tf":tf,"side":side,"entry":name,"hold":h,
                        "exit":style,"atr_sl_or_trail":sl,"atr_tp":tp}
                for evaluation_year in range(2019,2027):
                    yrmask=valid & mask & (year>=evaluation_year-2)&(year<evaluation_year)
                    cutoff=pd.Timestamp(f"{evaluation_year}-01-01",tz="UTC").value
                    yrmask &= endt<cutoff
                    ids=pick(mask,yrmask,ends[side])
                    if len(ids)<VALID_MIN[tf]:continue
                    eachyear=[ids[year[ids]==y] for y in (evaluation_year-2,evaluation_year-1)]
                    if min(map(len,eachyear))<max(2,VALID_MIN[tf]//5):continue
                    q=stats(ids,gross[side],2.)
                    positive=sum(stats(t,gross[side],2.)["net"]>0 for t in eachyear)
                    rank=ranked(q,mode,positive,VALID_MIN[tf])
                    if rank is None:continue
                    prev=selected_by_year[evaluation_year]
                    if prev is None or (rank,repr(policy))>(prev["rank"],repr(prev["policy"])):
                        selected_by_year[evaluation_year]={
                            "rank":rank,"policy":policy,"selection":q,
                            "validation_positive_years":positive}
    # Evaluate selected policy on only its already selected evaluation year,
    # and keep global no-overlap state if a long position crosses year boundary.
    annual=[]
    portfolio=[]
    last_exit=-1
    prior=0
    for y in range(2019,2027):
        p=selected_by_year[y]
        if p is None:
            annual.append({"year":y,"status":"WAIT_NO_ELIGIBLE_PRIOR_YEAR_POLICY",
                           "n":0,"net":0.,"selection":None})
            continue
        cfg=p["policy"]
        gross,ends=exits(d,atr,tf,cfg["hold"],cfg["exit"],
                         cfg["atr_sl_or_trail"],cfg["atr_tp"])
        side=cfg["side"]
        gate=entry_masks[side][cfg["entry"]]
        eligible=src_valid & (year==y)&np.isfinite(gross[side])
        selected=pick(gate,eligible,ends[side])
        # Reconcile one active position across adjacent years.
        selected=np.asarray([i for i in selected if i>=last_exit],
                            dtype=np.int64)
        if len(selected):last_exit=int(ends[side][selected[-1]])
        net=stats(selected,gross[side],2.)
        yearly=[
            {"signal_bar":int(i),"side":side,
             "exit_bar":int(ends[side][i]),
             "entry_time":d.index[i+1].isoformat(),
             "exit_time":d.index[int(ends[side][i])].isoformat(),
             "gross_usd_1oz":float(gross[side][i]),
             "net_cost2_usd_1oz":float(gross[side][i]-2)}
            for i in selected
        ]
        portfolio+=yearly
        annual.append({"year":y,"status":"REPLAYED","n":net["n"],
                      "net":net["net"],"profit_factor":net["pf"],
                      "dd":net["dd"],"win":net["win"],"selected":cfg,
                      "validation":p["selection"],"trades":yearly})
        print(json.dumps({"tf":tf,"mode":mode,"year":y,"n":net["n"],
            "net":round(net["net"],3),"policy":cfg},allow_nan=False),flush=True)
    portfolio.sort(key=lambda x:x["signal_bar"])
    pn=np.asarray([q["net_cost2_usd_1oz"] for q in portfolio])
    e=np.r_[0.,pn.cumsum()]
    dd=float(np.max(np.maximum.accumulate(e)-e))
    total=float(pn.sum())
    cost5=total-3*len(pn)
    report={
        "contract":CONTRACT,"symbol":"XAUUSD","tf":tf,"mode":mode,
        "source":provenance,"historical_years":list(range(2012,2027)),
        "evaluation_years":list(range(2019,2027)),
        "target":"next completed OPEN entry, ATR stop/target/trail, bounded CLOSE",
        "selection":"two prior calendar years with fully matured exits, never selected on current-year test",
        "candidate_count":candidates,
        "total_trades":len(portfolio),
        "net_usd_1oz_cost2":total,
        "net_usd_1oz_cost5":cost5,
        "max_realized_dd_usd_1oz":dd,
        "profit_factor_cost2":stats(np.arange(len(pn)),pn+2,2.)["pf"],
        "positive_years":int(sum(q["net"]>0 for q in annual)),
        "annual":annual,
        "nonoverlap":"one fixed 1 troy oz long OR short at one time, per timeframe",
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_verified":False,
        "partial_2026":True,"notionals_or_compounding_modelled":False,
        "limitations":[
            "Research 2019–2026 was repeatedly viewed in prior versions; no pristine test",
            "No real FP Markets bid/ask, swaps, latency, slippage, margin or leverage",
            "Stop/target barriers use OHLC, stop-first same-bar ambiguous resolution",
            "Floating drawdown/margin loss may be much larger than realized-close DD",
            "Annual policy changes; no single future live model is established",
            "Profit in USD for fixed 1oz, not an account balance",
            "H1/H4 source 2012-18 rehosted independently and 2019-26 original R10",
            "Candidate universe tuned after R31.1; considerable multiple-testing risk",
            "No direct ForexScanner or cTrader order integration"
        ]
    }
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/f"r32-{tf}-{mode}.json"
    path.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R32_COMPLETE","tf":tf,"mode":mode,
        "profit":total,"cost5":cost5,"n":len(portfolio),"dd":dd,
        "positive_years":report["positive_years"],"file":str(path)},allow_nan=False),flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=tuple(TF_HOLDS),required=True)
    p.add_argument("--mode",choices=MODES,required=True)
    a=p.parse_args()
    run(a.tf,a.mode)
