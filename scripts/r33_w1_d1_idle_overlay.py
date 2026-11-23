"""RIZAN R33: W1 4-week EMA baseline + D1 extra entries in verified idle windows.

No overlapping exposure: max ONE troy ounce across BOTH timeframes.
Source: original R9.8 XAUUSD D1/W1 2012–2026. Replay 2019–2026,
2026 incomplete. Fixed R31.1 W1 original reference is 75 trades and
+2825.987 $/oz at assumed $2 round-trip cost.

D1 candidates are existing annual 2-prior-year-selected R32 frozen trades,
not newly optimized on test-year profits. This follow-up's selection of
filters after reviewing R32/R32.1 is EXPLORATORY and NOT blind OOS.

At an identical D1/W1 opening, W1 baseline has priority. Existing D1
overlay is closed at that observable W1 open, after which W1 may enter.
Trades can exit at bar close and the next trade enter at the same clock
boundary; no more than 1oz concurrently. No live broker/orders.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import r30_pareto_direction_search as source
import r31_profit_grid as r31

CONTRACT="RIZAN_R33_W1_D1_IDLE_EXTRA_ENTRY_NO_OVERLAP_20261124_V1"
MODES=("max_net","max_signals","profit_frequency")
GATES=("any","d1_ema","d1_adx","d1_breakout","prior_week_ema")
R32_PATH=Path("artifacts/r32")
OUT=Path("artifacts/r33")
COST=2.
BASE_N=75
BASE_NET=2825.987

def historic():
    w,zw,_,validw,tw,pw=source.read_data("1W","archived")
    d,zd,_,validd,td,pd=source.read_data("1D","archived")
    if pw.get("scope")!="FULL_D1_W1_FROM_2012" or pd.get("scope")!="FULL_D1_W1_FROM_2012":
        raise ValueError("R33_SOURCE_REPRODUCIBILITY_FAILURE")
    if not set(range(2012,2027)).issubset(set(w.index.year)) or not set(range(2012,2027)).issubset(set(d.index.year)):
        raise ValueError("R33_SOURCE_HISTORY_2012_2026_MISSING")
    return w,zw,validw,tw,d,zd,validd,td

def baseline(w,z,valid,times):
    ok,gross,_,_=r31.exit_frames(w,"1W",4)
    mask=(z.ema8-z.ema21>0).to_numpy(dtype=bool)
    years=np.asarray(times.year)
    pick=r31.choose_indices(mask,valid&ok&(years>=2019)&(years<=2026),4)
    trades=[]
    for i in pick:
        begin=w.index[i+1]
        # W1 bar at i+4 completes before next Monday, which is the
        # conservative flat-again availability boundary.
        end=w.index[i+4]+pd.Timedelta(days=7)
        trades.append({
            "kind":"main","side":"BUY","signal_index":int(i),
            "entry_time":begin,"exit_time":end,
            "entry_price":float(w.o.iloc[i+1]),
            "signed_gross":float(gross[i]),
            "year":int(years[i]),
            "exit_bar":int(i+4)
        })
    value=sum(t["signed_gross"]-COST for t in trades)
    if len(trades)!=BASE_N or not math.isclose(value,BASE_NET,abs_tol=1e-3):
        raise ValueError("R33_FROZEN_W1_REFERENCE_MISMATCH")
    return trades

def frozen_d1_trades(d,times,mode):
    if mode not in MODES:raise ValueError("R33_UNKNOWN_MODE")
    x=json.loads((R32_PATH/f"r32-1D-{mode}.json").read_text())
    if (x.get("contract")!="RIZAN_R32_PROFIT_AND_SIGNAL_FREQUENCY_2012_2026_V1"
            or x.get("tf")!="1D" or x.get("mode")!=mode
            or x.get("research_only") is not True
            or x.get("execution_authority") is not False
            or x.get("forward_verified") is not False
            or x.get("historical_years")!=list(range(2012,2027))):
        raise ValueError("R33_FROZEN_D1_SOURCE_NOT_PROVEN")
    alltrades=[]
    n=0
    for annual in x["annual"]:
        if annual.get("status")!="REPLAYED":continue
        for q in annual["trades"]:
            i=int(q["signal_bar"])
            j=int(q["exit_bar"])
            if (i<0 or j>=len(d) or i+1>=j+1 or j<=i
                    or q["side"] not in ("BUY","SELL")
                    or q["entry_time"]!=d.index[i+1].isoformat()
                    or q["exit_time"]!=d.index[j].isoformat()
                    or annual["year"]!=int(times.year[i])):
                raise ValueError("R33_ORIGINAL_R32_D1_TRADE_PARITY_FAIL")
            price=float(d.o.iloc[i+1])
            sign=1 if q["side"]=="BUY" else -1
            signed=float(q["gross_usd_1oz"])
            if not math.isclose(signed-COST,q["net_cost2_usd_1oz"],abs_tol=1e-6):
                raise ValueError("R33_GROSS_TO_NET_INVALID")
            alltrades.append({
                "kind":"overlay","side":q["side"],"signal_index":i,
                "entry_time":d.index[i+1],
                "exit_time":d.index[j]+pd.Timedelta(days=1),
                "entry_price":price,
                "signed_gross":signed,
                "year":int(times.year[i]),
                "exit_bar":j,
            })
            n+=1
    if n!=x["total_trades"]:raise ValueError("R33_D1_TRADE_COUNT_FAIL")
    return alltrades

def gates(d,zd,w,zw):
    """Daily overlay permissions at daily signal CLOSE, with last completed W1.

    Each W1 observation becomes visible the Monday 00:00 UTC AFTER that
    week's candle was completed; current unfinished weekly OHLC is NEVER
    used. The gate is evaluated on the daily signal bar itself.
    """
    wk=pd.DataFrame({
        "ema_pos":((zw.ema8-zw.ema21)>0).to_numpy(dtype=bool)
    },index=w.index+pd.Timedelta(days=7))
    wk=wk[~wk.index.duplicated()].sort_index()
    last=wk.reindex(d.index+pd.Timedelta(days=1),method="ffill")
    a=np.asarray((zd.ema8-zd.ema21)>0,dtype=bool)
    b=np.asarray(zd.adx14>=18,dtype=bool)
    c=np.asarray(zd.break8>0,dtype=bool)
    prev=np.asarray(last["ema_pos"].fillna(False),bool)
    observed=last["ema_pos"].notna().to_numpy()
    return {
        "any":{s:np.ones(len(d),bool) for s in ("BUY","SELL")},
        "d1_ema":{"BUY":a,"SELL":~a},
        "d1_adx":{"BUY":a&b,"SELL":(~a)&b},
        "d1_breakout":{"BUY":a&c,"SELL":(~a)&np.asarray(zd.break8<0,bool)},
        "prior_week_ema":{"BUY":prev&observed,"SELL":(~prev)&observed},
    }

def schedule(main,candidates,d,w,allowed,gate):
    """One position, W1 priority, voluntary flat-time D1 overlay only.

    Main trades are frozen and must not be skipped. Overlays may be
    preempted only at the W1 opening at observable W1 OPEN price.
    """
    if gate not in GATES:raise ValueError("R33_UNKNOWN_GATE")
    chosen=[]
    for t in candidates:
        m=allowed[gate][t["side"]]
        if bool(m[t["signal_index"]]):chosen.append(t)
    events=sorted(main+chosen,key=lambda t:(t["entry_time"],0 if t["kind"]=="main" else 1))
    w_open={x:float(v) for x,v in zip(w.index,w.o)}
    ret=[]
    current=None
    rejected={"during_main":0,"during_overlay":0,"filters":len(candidates)-len(chosen),
              "preempted":0}
    def close(t,preempt=False,when=None):
        if preempt:
            if t["kind"]!="overlay" or when not in w_open:
                raise ValueError("R33_PREEMPTION_WITHOUT_W1_OPEN")
            direction=1 if t["side"]=="BUY" else -1
            signed=direction*(w_open[when]-t["entry_price"])
            exitat=when
        else:
            signed=t["signed_gross"]
            exitat=t["exit_time"]
        return {
            "kind":t["kind"],"side":t["side"],
            "entry_time":t["entry_time"].isoformat(),
            "exit_time":exitat.isoformat(),
            "preempted":bool(preempt),
            "net_cost2_usd_oz":float(signed-COST),
            "entry_year":t["entry_time"].year,
        }
    for ev in events:
        when=ev["entry_time"]
        if current is not None and current["exit_time"]<=when:
            ret.append(close(current))
            current=None
        if current is not None:
            if ev["kind"]=="main" and current["kind"]=="overlay":
                ret.append(close(current,preempt=True,when=when))
                current=None
                rejected["preempted"]+=1
            else:
                if ev["kind"]=="main":
                    raise ValueError("R33_MAIN_TRADE_CONFLICT")
                rejected["during_main" if current["kind"]=="main" else "during_overlay"]+=1
                continue
        current=ev
    if current is not None:ret.append(close(current))
    ret.sort(key=lambda v:(v["exit_time"],v["entry_time"]))
    actual=sorted(ret,key=lambda v:v["entry_time"])
    for previous,next_ in zip(actual,actual[1:]):
        if pd.Timestamp(next_["entry_time"])<pd.Timestamp(previous["exit_time"]):
            raise ValueError("R33_PORTFOLIO_OVERLAP_RISK")
    if sum(q["kind"]=="main" for q in ret)!=BASE_N:
        raise ValueError("R33_MAIN_TRADE_COUNT_CHANGED")
    values=np.array([q["net_cost2_usd_oz"] for q in ret],float)
    equity=np.r_[0,values.cumsum()]
    maxdd=float(np.max(np.maximum.accumulate(equity)-equity))
    annually={
        str(y):{
            "n":int(sum(pd.Timestamp(q["entry_time"]).year==y for q in ret)),
            "net":float(sum(q["net_cost2_usd_oz"] for q in ret
                            if pd.Timestamp(q["entry_time"]).year==y))
        }
        for y in range(2019,2027)
    }
    positive=values[values>0].sum()
    losses=-values[values<0].sum()
    result={
        "total_trades":len(ret),"main_trades":BASE_N,
        "additional_trades":sum(q["kind"]=="overlay" for q in ret),
        "net_cost2_usd_per_1oz":float(values.sum()),
        "net_cost5_usd_per_1oz":float(values.sum()-3*len(ret)),
        "incremental_net_vs_frozen_w1":float(values.sum()-BASE_NET),
        "max_realized_dd_usd_per_1oz":maxdd,
        "profit_factor_cost2":float(positive/losses) if losses>0 else None,
        "positive_years":sum(annually[k]["net"]>0 for k in annually),
        "annually":annually,
        "rejected":rejected,"trade_receipts":ret,
    }
    return result

def run(mode,gate):
    w,zw,validw,tw,d,zd,validd,td=historic()
    main=baseline(w,zw,validw,tw)
    extras=frozen_d1_trades(d,td,mode)
    allowed=gates(d,zd,w,zw)
    result=schedule(main,extras,d,w,allowed,gate)
    doc={
        "contract":CONTRACT,
        "symbol":"XAUUSD","source":"R9.8 D1/W1 historical 2012-2026",
        "evaluation_years":list(range(2019,2027)),
        "mode":mode,"gate":gate,
        "baseline_trades":BASE_N,
        "baseline_net_cost2_usd_per_1oz":BASE_NET,
        "original_d1_candidate_trades":len(extras),
        "max_portfolio_exposure_oz":1.,
        "max_concurrent_positions":1,
        "pyramiding":False,"leverage":False,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_verified":False,
        "partial_2026":True,
        "signal_selection":"R32 two prior calendar years; gate only closed D1 and prior completed W1",
        "result":result,
        "limitations":[
            "Historical 2019-2026 outcomes repeatedly inspected; follow-up gate selection NOT independent OOS",
            "Fixed R31.1 W1 75-trade benchmark; overlays derived from R32 D1 annual model selections",
            "Next D1 and W1 opens are quote proxies, not FP Markets executable fills; 2 and 5 USD/oz assumed costs",
            "Main W1 exit treated conservatively as next Monday, although actual source candle closes Friday",
            "D1 overlay preempted at next W1 Monday observed OPEN to prevent overlapping exposures",
            "One fixed ounce combined gross exposure, no leverage, lot sizing or account compounding",
            "Realized drawdown excludes intrabar adverse excursion, swap and margin/liquidation",
            "No deployment or modification of Frozen V1, cTrader or ForexScanner"
        ],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/f"r33-{mode}-{gate}.json"
    path.write_text(json.dumps(doc,indent=2,allow_nan=False)+"\n")
    print(json.dumps({
        "stage":"R33_COMPLETE","mode":mode,"gate":gate,
        "candidate_trades":len(extras),"extra_executed":result["additional_trades"],
        "all_trades":result["total_trades"],"net":result["net_cost2_usd_per_1oz"],
        "net5":result["net_cost5_usd_per_1oz"],
        "increment":result["incremental_net_vs_frozen_w1"],
        "dd":result["max_realized_dd_usd_per_1oz"],
        "positive_years":result["positive_years"],
        "path":str(path)
    },allow_nan=False),flush=True)
    return doc

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",required=True,choices=MODES)
    parser.add_argument("--gate",required=True,choices=GATES)
    args=parser.parse_args()
    run(args.mode,args.gate)
