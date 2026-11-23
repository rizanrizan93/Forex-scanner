"""RIZAN R31 | XAUUSD net-profit-first large-scale rule research, 2012-2026.

Completed-bar features -> next candle OPEN entry -> exit at H-th next
candle CLOSE. Strict no overlapping same-TF exposure, one ounce per trade,
no leverage, execution API, order placement or equity compounding.
True broker spread, overnight swap, liquidity, margin and slippage are NOT
known; all dollar profits are explicit COST SCENARIOS, NOT realized PnL.

For each 2019-2026 evaluation year, candidates are ranked on the two
PREVIOUS calendar years with fully matured exits BEFORE the test boundary.
The 2019-2026 years have been repeatedly investigated in prior RIZAN
studies, so not a pristine holdout. Multiple comparisons generate bias.
This is exploratory, not deployment authority.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

import r30_pareto_direction_search as source
from r10_million import wilson

CONTRACT="RIZAN_R31_XAU_NET_PROFIT_FROZEN_RESEARCH_V1"
TFS=("1h","4h","1D","1W")
COST_MAIN=2.0
COST_SCENARIOS=(.7,2.0,5.0)
YEAR_START=2019
YEAR_END=2026
MIN_TRADES={"1h":70,"4h":35,"1D":14,"1W":7}
MODES=("max_net","net_dd","profit_frequency")
HOLD={"1h":(1,2,4),"4h":(1,2,3),"1D":(1,2),"1W":(1,2)}
OUT=Path("artifacts/r31")
MAX_POLICY_PAIRS=25000
EXECUTION_AUTHORITY=False


def tobool(v):
    return np.asarray(pd.Series(v).fillna(False),dtype=bool)


def sides(d,z,times,tf):
    n=len(d)
    close=d.c.astype(float)
    h=d.h.astype(float)
    l=d.l.astype(float)
    atr=z.atr14.replace(0,np.nan)
    em=(z.ema8-z.ema21)/atr
    diag=z.di
    mom=z.roc3
    clv=z.clv
    body=z.body
    bb=z.bbwidth
    bbmid=z.bbmedian
    rk=z.atr_rank
    rsi=z.rsi14
    # Source OHLC-derived SMC/ICT inspired geometry is a proxy, not DOM flow.
    context={}
    for side in ("BUY","SELL"):
        sign=1 if side=="BUY" else -1
        trend=sign*em>0
        pressure=sign*clv>.25
        gap=sign*diag>0
        br=sign*z.break8>0
        sweep=sign*z.sweep5>0
        out={
            "always":np.ones(n,bool),
            "ema_trend":tobool(trend),
            "ema_adx":tobool(trend & (z.adx14>=18)),
            "ema_di":tobool(trend & gap),
            "macd_trend":tobool(trend & (sign*z.macdh>0)),
            "body_pressure":tobool(sign*body>.25),
            "close_pressure":tobool(pressure),
            "rsi_momentum":tobool(sign*(rsi-50)>8),
            "rsi_reversion":tobool(sign*(rsi-50)<-10 & pressure) if False else tobool((sign*(rsi-50)<-10)&pressure),
            "sweep_reclaim":tobool(sweep & pressure),
            "sweep_with_trend":tobool(sweep & trend),
            "breakout":tobool(br),
            "breakout_pressure":tobool(br & pressure),
            "breakout_adx":tobool(br & (z.adx14>=18)),
            "displacement":tobool((sign*body>.45)&(z.rangeratio>1.15)),
            "trend_pullback":tobool(trend&(sign*mom<0)&pressure),
            "trend_continuation":tobool(trend&(sign*mom>0)&pressure),
            "compression_release":tobool((bb<bbmid)&(sign*body>.35)&trend),
            "discount_reclaim":tobool(((z.discount<.3) if side=="BUY" else (z.discount>.7))&pressure),
            "premium_break":tobool(((z.discount>.7) if side=="BUY" else (z.discount<.3))&br),
            "trend_highvol":tobool(trend & (rk>.5) & (z.adx14>=18)),
            "trend_lowvol":tobool(trend & (rk<.5) & pressure),
            "counter_sweep":tobool((~trend)&sweep&pressure),
        }
        context[side]={
            "base":out,
            "quality":{
                "any":np.ones(n,bool),
                "trend":tobool(trend),
                "counter":tobool(~trend),
                "adx15":tobool(z.adx14>=15),
                "adx22":tobool(z.adx14>=22),
                "di_align":tobool(gap),
                "momentum":tobool(sign*mom>0),
                "reversal":tobool(sign*mom<0),
            },
        }
    # Session known at decision timestamp; no future price is observed.
    local=times.tz_convert("Asia/Jakarta")
    london=times.tz_convert("Europe/London")
    ny=times.tz_convert("America/New_York")
    session={
        "all":np.ones(n,bool),
    }
    if tf in ("1h","4h"):
        session.update({
            "asia":tobool((local.hour>=8)&(local.hour<13)),
            "london":tobool((london.hour>=8)&(london.hour<16)),
            "newyork":tobool((ny.hour>=8)&(ny.hour<15)),
            "london_ny":tobool(
                ((london.hour>=8)&(london.hour<16))
                |((ny.hour>=8)&(ny.hour<15))),
        })
    v={
        "all":np.ones(n,bool),
        "atr_high":tobool(rk>.50),
        "atr_low":tobool(rk<=.50),
        "range_expansion":tobool(z.rangeratio>=1.15),
    }
    return context,session,v


def exit_frames(d,tf,hold):
    """Exactly next OPEN -> H-th next CLOSE. Labels only, never inputs."""
    n=len(d)
    a=d.o.to_numpy(float)
    b=d.c.to_numpy(float)
    high=d.h.to_numpy(float)
    low=d.l.to_numpy(float)
    idx=d.index
    x=np.arange(n)
    entry=x+1
    end=x+hold
    ok=end<n
    delta=1 if tf=="1h" else 4 if tf=="4h" else 0
    if delta:
        for k in range(1,hold+1):
            ix=x+k
            q=ix<n
            check=np.zeros(n,bool)
            check[q]=(idx.asi8[ix[q]]-idx.asi8[ix[q]-1])==pd.Timedelta(hours=delta).value
            ok &=check
    elif tf=="1W":
        for k in range(1,hold+1):
            ix=x+k
            q=ix<n
            check=np.zeros(n,bool)
            check[q]=(idx.asi8[ix[q]]-idx.asi8[ix[q]-1])==pd.Timedelta(days=7).value
            ok &=check
    else:
        for k in range(1,hold+1):
            ix=x+k
            q=ix<n
            check=np.zeros(n,bool)
            gap=idx.asi8[ix[q]]-idx.asi8[ix[q]-1]
            check[q]=(gap>=pd.Timedelta(days=1).value)&(gap<=pd.Timedelta(days=4).value)
            ok &=check
    gross=np.full(n,np.nan,float)
    end_t=np.full(n,np.datetime64("NaT","ns"),dtype="datetime64[ns]")
    valid=np.flatnonzero(ok)
    gross[valid]=b[end[valid]]-a[entry[valid]]
    # End is actual bar CLOSE, not timestamp of open.
    closeoffset=pd.Timedelta(hours=delta or (24 if tf=="1D" else 168))
    end_t[valid]=(idx[end[valid]]+closeoffset).tz_localize(None).to_numpy("datetime64[ns]")
    adverse=np.full((2,n),np.nan)
    for i in valid:
        seg=slice(i+1,i+hold+1)
        adverse[0,i]=np.min(low[seg])-a[i+1]
        adverse[1,i]=a[i+1]-np.max(high[seg])
    return ok & np.isfinite(gross),gross,end_t,adverse


def choose_indices(signal,eligible,hold):
    indices=np.flatnonzero(signal & eligible)
    if hold==1 or len(indices)==0:return indices
    taken=[]
    last=-hold
    for i in indices:
        if i>=last+hold:
            taken.append(i)
            last=i
    return np.asarray(taken,dtype=np.int64)


def metrics(indices,side,gross,cost=COST_MAIN):
    if len(indices)==0:
        return {"n":0,"correct":0,"accuracy":None,"gross_usd_oz":0.,
                "net_usd_oz":0.,"net_mean_usd_oz":None,"profit_factor":None,
                "max_drawdown_usd_oz":0.,"winning_years":0}
    signed=gross[indices]*(1 if side=="BUY" else -1)
    net=signed-cost
    wins=int(np.sum(net>0))
    profits=float(net[net>0].sum())
    losses=float(-net[net<0].sum())
    curve=np.concatenate([[0.],np.cumsum(net)])
    dd=float(np.max(np.maximum.accumulate(curve)-curve))
    return {"n":len(indices),"correct":wins,"accuracy":wins/len(indices),
            "gross_usd_oz":float(signed.sum()),"net_usd_oz":float(net.sum()),
            "net_mean_usd_oz":float(net.mean()),
            "profit_factor":profits/losses if losses>0 else None,
            "max_drawdown_usd_oz":dd,
            "wilson_lower95":float(wilson(wins,len(indices))),
            "positive_trades":wins,"negative_trades":int((net<0).sum())}


def stability_pnl(indices,side,gross,times,cost=COST_MAIN):
    if len(indices)==0:return 0
    yy=times.year
    distinct=np.unique(yy[indices])
    net=(1 if side=="BUY" else -1)*gross[indices]-cost
    return int(sum(net[yy[indices]==y].sum()>0 for y in distinct))


def policy_rank(m,mode,distinct_positive):
    if (m["n"]==0 or m["net_usd_oz"]<=0
            or m["net_mean_usd_oz"]<=0
            or (m["profit_factor"] or 0)<=1.03):
        return None
    net=m["net_usd_oz"]
    dd=max(.01,m["max_drawdown_usd_oz"])
    if mode=="max_net":
        return (net,distinct_positive,m["n"])
    if mode=="net_dd":
        if distinct_positive<2:return None
        return (net/dd,net,m["n"])
    if mode=="profit_frequency":
        return (net*np.sqrt(m["n"]),distinct_positive,net)
    raise ValueError("R31_MODE_UNKNOWN")


def candidate_masks(tf,context,sessions,vol):
    seen=0
    for side in ("BUY","SELL"):
        cfg=context[side]
        for (bn,bm),(cn,cm),(sn,sm),(vn,vm) in itertools.product(
                cfg["base"].items(),cfg["quality"].items(),
                sessions.items(),vol.items()):
            # The overlapping filters are intentional; candidate count is
            # a search-space upper bound, not independent models learned.
            if bn=="always" and cn=="any" and sn=="all" and vn=="all":
                continue
            candidate=bm & cm & sm & vm
            if not np.any(candidate):continue
            seen+=1
            yield side,{"base":bn,"regime":cn,"session":sn,"volatility":vn},candidate
    if seen==0:raise ValueError("R31_CANDIDATE_UNIVERSE_EMPTY")


def runner(tf,hold,mode):
    if tf not in TFS or hold not in HOLD[tf] or mode not in MODES:
        raise ValueError("R31_INVALID_HORIZON_OR_MODE")
    scope="spliced" if tf in ("1h","4h") else "archived"
    d,z,_,base_valid,times,source_manifest=source.read_data(tf,scope)
    valid_h,gross,finish,adverse=exit_frames(d,tf,hold)
    valid=base_valid & valid_h
    context,sessions,vol=sides(d,z,times,tf)
    years=times.year.to_numpy() if hasattr(times.year,"to_numpy") else np.asarray(times.year)
    min_n=MIN_TRADES[tf]
    annual=[]
    evaluations=[]
    search_count=0
    total_scored=0
    for year in range(YEAR_START,YEAR_END+1):
        # Candidate's validation EXIT must mature strictly before test year.
        boundary=np.datetime64(f"{year}-01-01T00:00:00","ns")
        selection=valid & (years>=year-2)&(years<year)&(finish<boundary)
        evaluation=valid & (years==year)
        best={side:None for side in ("BUY","SELL")}
        cand_count=0
        for side,policy,signal in candidate_masks(tf,context,sessions,vol):
            if year==YEAR_START:search_count+=1
            cand_count+=1
            idx=choose_indices(signal,selection,hold)
            if len(idx)<min_n:continue
            # Ensure both years supply at least a fifth of the floor
            a=np.sum(years[idx]==year-2);b=np.sum(years[idx]==year-1)
            if min(a,b)<max(2,min_n//5):continue
            m=metrics(idx,side,gross)
            stable=stability_pnl(idx,side,gross,times)
            rank=policy_rank(m,mode,stable)
            if rank is None:continue
            total_scored+=1
            previous=best[side]
            if previous is None or (rank,str(policy))>(previous["rank"],str(previous["policy"])):
                best[side]={"policy":policy,"mask":signal,"rank":rank,
                            "validation":m,"validation_positive_years":stable}
        if cand_count>MAX_POLICY_PAIRS:
            raise ValueError("R31_TOO_MANY_RULES_UNBOUNDED")
        bsignal=np.zeros(len(d),bool);ssignal=np.zeros(len(d),bool)
        for side,output in (("BUY",bsignal),("SELL",ssignal)):
            if best[side] is not None:output[:]=best[side]["mask"]
        overlap=bsignal & ssignal
        bsignal &= ~overlap
        ssignal &= ~overlap
        # Portfolio positions never overlap, even between BUY and SELL.
        candidate_indices=np.flatnonzero((bsignal|ssignal)&evaluation)
        final_buy=[];final_sell=[]
        last_signal=-hold
        for ix in candidate_indices:
            if ix<last_signal+hold:continue
            last_signal=ix
            (final_buy if bsignal[ix] else final_sell).append(ix)
        picks={"BUY":np.asarray(final_buy,dtype=np.int64),
               "SELL":np.asarray(final_sell,dtype=np.int64)}
        selected={}
        trade_net=[]
        for side,idx in picks.items():
            m=metrics(idx,side,gross)
            selected[side]={
                "policy":best[side]["policy"] if best[side] else None,
                "validation":best[side]["validation"] if best[side] else None,
                "evaluation":m,
            }
            if len(idx):
                net=((1 if side=="BUY" else -1)*gross[idx]-COST_MAIN)
                trade_net.extend((int(i),float(p)) for i,p in zip(idx,net))
        trade_net.sort()
        returns=np.array([p for _,p in trade_net])
        eq=np.r_[0,np.cumsum(returns)]
        annual_row={
            "year":year,"candidate_policies_considered":cand_count,
            "signals_buy":len(picks["BUY"]),"signals_sell":len(picks["SELL"]),
            "conflicts":int(np.sum(overlap&evaluation)),
            "eligible_bars":int(evaluation.sum()),
            "total_trades":int(len(trade_net)),
            "net_profit_usd_per_1oz":float(returns.sum()),
            "max_realized_drawdown_usd_per_1oz":float(
                np.max(np.maximum.accumulate(eq)-eq)),
            "sides":selected,
            "cost_sensitivity":{
                str(cost):float(returns.sum()+(COST_MAIN-cost)*len(returns))
                for cost in COST_SCENARIOS
            },
            "trade_receipts":[{"bar_index":int(i),"net_usd_oz":p}
                              for i,p in trade_net],
        }
        annual.append(annual_row)
        evaluations.extend((year,i,p) for i,p in trade_net)
        print(json.dumps({
            "stage":"annual","tf":tf,"hold":hold,"mode":mode,
            "year":year,"trades":len(trade_net),
            "net_usd_oz":round(float(returns.sum()),2),
            "drawdown_usd_oz":round(annual_row["max_realized_drawdown_usd_per_1oz"],2),
            "buy":selected["BUY"]["evaluation"],"sell":selected["SELL"]["evaluation"],
        },allow_nan=False),flush=True)
    # Preserve chronological order for true realized portfolio drawdown.
    evaluations.sort(key=lambda x:x[1])
    pnl=np.asarray([z for _,_,z in evaluations])
    eq=np.r_[0.,np.cumsum(pnl)]
    net=float(pnl.sum())
    max_dd=float(np.max(np.maximum.accumulate(eq)-eq))
    total=len(pnl)
    result={
        "contract":CONTRACT,"symbol":"XAUUSD","timeframe":tf,
        "hold_candles":hold,"mode":mode,
        "backtest_entry":"NEXT_BAR_OPEN",
        "backtest_exit":"H_TH_NEXT_BAR_CLOSE",
        "position_rule":"MAX_ONE_1OZ_POSITION_PER_TIMEFRAME_NO_OVERLAP",
        "reference_price_is_not_broker_fill":True,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_verified":False,
        "price_source":source_manifest,
        "data_years":list(range(2012,2027)),
        "validation_rule":"TWO_PRIOR_YEARS_MATURED_EXITS_ONLY",
        "evaluation_years":list(range(YEAR_START,YEAR_END+1)),
        "cost_scenario_main_usd_oz":COST_MAIN,
        "cost_scenarios_usd_oz":list(COST_SCENARIOS),
        "candidate_rules_considered":search_count,
        "strategy_evaluations_with_positive_validation_profit":total_scored,
        "hypothetical_net_profit_usd_per_1oz":net,
        "hypothetical_max_realized_drawdown_usd_per_1oz":max_dd,
        "total_trades":total,
        "positive_eval_years":int(sum(r["net_profit_usd_per_1oz"]>0 for r in annual)),
        "annual":annual,
        "cost_sensitivity_net_profit":{
            str(c):float(net+(COST_MAIN-c)*total) for c in COST_SCENARIOS
        },
        "limitations":[
            "Exact original XAU source 2012–2018 is redistributed independent archive; 2019–26 original R10 and source boundary documented",
            "2019–26 test years inspected in prior RIZAN research; multiple-testing bias substantial",
            "Current completed-candle features and next OPEN-to-CLOSE execution proxy; no bid/ask, spread, swaps, latency or market impact",
            "1oz fixed notional, NO leverage or position sizing or compounding; USD/oz is NOT account balance",
            "No guaranteed ability to trade source close/open prices or drawdown including intrabar excursions",
            "Optimized on 2-year prior validation only; annual test outcomes never used to select that year's model",
            "SMC/ICT labels for OHLC geometry only, not institutional flow",
            "Not integrated into ForexScanner or cTrader and no valid buy/sell live signals emitted",
        ],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/f"r31-{tf}-h{hold}-{mode}.json"
    path.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"complete","file":str(path),"tf":tf,
        "horizon":hold,"mode":mode,"trades":total,
        "profit":round(net,2),"max_dd":round(max_dd,2),
        "candidate_rules_considered":search_count,
        "costs":result["cost_sensitivity_net_profit"]}),flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=TFS,required=True)
    p.add_argument("--hold",type=int,required=True)
    p.add_argument("--mode",choices=MODES,required=True)
    a=p.parse_args()
    runner(a.tf,a.hold,a.mode)
