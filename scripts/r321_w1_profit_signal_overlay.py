"""RIZAN R32.1: no-leverage max 1oz W1 profit + extra signal overlay.

Main arm is FIXED W1 EMA8>EMA21 BUY next Monday open to fourth W1 close
matching original unoptimized R31.1 control. Optional R32 W1 trades execute
only when the main arm is flat; a newly available main-arm entry preempts
a current overlay at NEXT Monday OPEN. Both branches are 1 fixed ounce:
aggregate gross exposure never exceeds 1 ounce, never pyramids/leverage.

Experiments chosen after R31/R32 outcomes were inspected: NOT blind forward
validation. Broker spread/overnight swap and actual executable prices unknown.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import numpy as np

import r30_pareto_direction_search as data
import r31_profit_grid as r31

MODES=("max_signals","profit_frequency","max_net")
GATES=("any_flat","ema_direction")
CONTRACT="RIZAN_R321_W1_NO_LEVERAGE_EXTRA_SIGNALS_V1"
OUT=Path("artifacts/r321")
R32=Path("artifacts/r32")
COST=2.
BASELINE_N=75
BASELINE_NET=2825.987


def read_trades(d,z,valid,times,mode):
    h=4
    valid_exit,gross,_,_=r31.exit_frames(d,"1W",h)
    year=np.asarray(times.year)
    mask=np.asarray(z.ema8-z.ema21>0,bool)
    eligible=valid & valid_exit & (year>=2019) &(year<=2026)
    picked=r31.choose_indices(mask,eligible,h)
    baseline=[]
    for i in picked:
        baseline.append({
            "kind":"baseline","side":"BUY","signal_bar":int(i),
            "entry_bar":int(i+1),"exit_bar":int(i+h),
            "signed_gross_usd_oz":float(gross[i]),"year":int(year[i]),
        })
    original=sum(x["signed_gross_usd_oz"]-COST for x in baseline)
    if len(baseline)!=BASELINE_N or not math.isclose(
        original,BASELINE_NET,abs_tol=1e-3
    ):
        raise ValueError("R321_BASELINE_W1_HISTORY_NOT_REPRODUCED")

    receipt=R32/f"r32-1W-{mode}.json"
    x=json.loads(receipt.read_text())
    if (x.get("contract")!="RIZAN_R32_PROFIT_AND_SIGNAL_FREQUENCY_2012_2026_V1"
        or x.get("tf")!="1W" or x.get("mode")!=mode
        or x.get("research_only") is not True
        or x.get("execution_authority") is not False
        or len(x.get("annual",[]))!=8):
        raise ValueError("R321_R32_SOURCE_INVALID")
    candidates=[]
    for row in x["annual"]:
        if row["status"]!="REPLAYED":continue
        for t in row["trades"]:
            i=int(t["signal_bar"])
            j=int(t["exit_bar"])
            side=t["side"]
            if (t["entry_time"]!=d.index[i+1].isoformat()
                or t["exit_time"]!=d.index[j].isoformat()
                or side not in ("BUY","SELL")
                or j<=i or i>=len(d)-1):
                raise ValueError("R321_R32_SOURCE_TRADE_MISMATCH")
            candidates.append({
                "kind":"overlay","side":side,
                "signal_bar":i,"entry_bar":i+1,"exit_bar":j,
                "signed_gross_usd_oz":float(t["gross_usd_1oz"]),
                "year":int(year[i]),
            })
    if len(candidates)!=x["total_trades"]:
        raise ValueError("R321_R32_TRADE_COUNT_INVALID")
    return baseline,candidates


def portfolio(d,z,base,extra,filter_mode):
    if filter_mode not in GATES:raise ValueError("R321_FILTER_UNKNOWN")
    e=np.asarray(z.ema8-z.ema21>0,bool)
    # Main arm goes first at equal entry timestamp. This is a mechanical
    # priority known at the open, not a future predicted conflict.
    events=sorted(
        base+extra,key=lambda q:(q["entry_bar"],0 if q["kind"]=="baseline" else 1)
    )
    openp=d.o.to_numpy(float)
    results=[]
    active=None
    ignored={"base":0,"overlay_busy":0,"overlay_filter":0,"preempted":0}
    def finish(x,stop_bar=None):
        ending=int(stop_bar if stop_bar is not None else x["exit_bar"])
        if ending>=len(d):raise ValueError("R321_END_OUT_OF_RANGE")
        if stop_bar is None:
            gross=x["signed_gross_usd_oz"]
            phase=1
        else:
            direction=1 if x["side"]=="BUY" else -1
            gross=direction*(openp[ending]-openp[x["entry_bar"]])
            phase=0
        return {
            "kind":x["kind"],"side":x["side"],"year":x["year"],
            "signal_bar":x["signal_bar"],"entry_bar":x["entry_bar"],
            "exit_bar":ending,"exit_phase":phase,"preempted":stop_bar is not None,
            "net_cost2_usd_oz":float(gross-COST),
        }
    for ev in events:
        start=ev["entry_bar"]
        if start>=len(d):continue
        if active is not None and start>active["exit_bar"]:
            results.append(finish(active))
            active=None
        if active is not None and start<=active["exit_bar"]:
            if ev["kind"]=="baseline" and active["kind"]=="overlay":
                # At the exact OPEN of the new main trade, close the
                # overlay first, using observable open (not future close).
                results.append(finish(active,stop_bar=start))
                ignored["preempted"]+=1
                active=None
            else:
                if ev["kind"]=="baseline":
                    # With original predeclared 4W non-overlapping base
                    # episodes this should never occur.
                    raise ValueError("R321_BASE_CONFLICT_WITH_ACTIVE_BASE")
                ignored["overlay_busy"]+=1
                continue
        if ev["kind"]=="overlay":
            if filter_mode=="ema_direction" and (
                (ev["side"]=="BUY")!=bool(e[ev["signal_bar"]])
            ):
                ignored["overlay_filter"]+=1
                continue
        active=ev
    if active is not None:results.append(finish(active))
    results.sort(key=lambda x:(x["exit_bar"],x["exit_phase"],x["entry_bar"]))
    # Each arm is fully closed before another position enters. Verified by
    # exact entry-time ordering independent of exit-event chronological sort.
    episodes=sorted(results,key=lambda x:x["entry_bar"])
    for a,b in zip(episodes,episodes[1:]):
        if b["entry_bar"]<=a["exit_bar"] and not (
                a["preempted"] and b["entry_bar"]==a["exit_bar"]):
            raise ValueError("R321_OVERLAPPING_RISK_EXPOSURE")
    total=sum(q["net_cost2_usd_oz"] for q in results)
    timeline=[q["net_cost2_usd_oz"] for q in results]
    profit=0.;peak=0.;dd=0.
    for pnl in timeline:
        profit+=pnl;peak=max(peak,profit);dd=max(dd,peak-profit)
    annual={str(y):{
        "n":sum(q["year"]==y for q in results),
        "profit":sum(q["net_cost2_usd_oz"] for q in results if q["year"]==y)
    } for y in range(2019,2027)}
    winners=sum(1 for v in timeline if v>0)
    gain=sum(v for v in timeline if v>0)
    loss=-sum(v for v in timeline if v<0)
    return {
        "n":len(results),"baseline_n":sum(x["kind"]=="baseline" for x in results),
        "overlay_n":sum(x["kind"]=="overlay" for x in results),
        "net_cost2_usd_per_fixed1oz":float(total),
        "net_cost5_usd_per_fixed1oz":float(total-3*len(results)),
        "max_realized_dd_usd_per_fixed1oz":float(dd),
        "profit_factor_cost2":gain/loss if loss>0 else None,
        "positive_years":sum(v["profit"]>0 for v in annual.values()),
        "annual":annual,
        "ignored":ignored,"trades":results,
    }


def run(mode,gate):
    if mode not in MODES or gate not in GATES:raise ValueError("R321_INVALID_CONFIG")
    d,z,_,valid,times,source=data.read_data("1W","archived")
    baseline,extra=read_trades(d,z,valid,times,mode)
    p=portfolio(d,z,baseline,extra,gate)
    if p["baseline_n"]!=BASELINE_N:
        raise ValueError("R321_MUST_NOT_SKIP_FROZEN_BASELINE_75")
    if p["overlay_n"]>len(extra) or p["n"]!=p["baseline_n"]+p["overlay_n"]:
        raise ValueError("R321_SIGNAL_COUNT_INVALID")
    report={
        "contract":CONTRACT,"symbol":"XAUUSD","tf":"1W",
        "mode":mode,"overlay_filter":gate,
        "source":"R9.8 original XAUUSD 2012-2026; 2019-26 evaluation",
        "years":list(range(2019,2027)),
        "historical_reference_W1_EMA_BUY_4W":{
            "n":BASELINE_N,"net_cost2_usd_fixed1oz":BASELINE_NET,
        },
        "overlay_source":"R32 strict two-prior-year policies, mode "+mode,
        "max_gross_risk_exposure_oz":1.,
        "max_concurrent_positions":1,
        "compounding":False,"leverage":False,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_verified":False,
        "partial_2026":True,
        "result":p,
        "limitations":[
            "R32.1 overlay chosen after observing R31.1 and R32 historical results; not blind forward test",
            "R31.1 base W1 and R32 overlay never overlap, main W1 entry preempts overlay at next open",
            "Intrabar broker spreads, latency, swaps and slippage not measured; no market execution proof",
            "One ounce fixed position, no compounded account balance and no leverage",
            "Preempted overlay exit at next OPEN assumes availability at that price",
            "Drawdown realized at closed trade timestamps, floating margin stress not modelled",
            "2019-2026 already repeatedly examined during R31/R32 optimization",
            "No cTrader or ForexScanner live signal changes"
        ],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/f"r321-{mode}-{gate}.json"
    path.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R321_COMPLETE","mode":mode,"gate":gate,
        "n":p["n"],"overlay":p["overlay_n"],
        "net":p["net_cost2_usd_per_fixed1oz"],
        "net5":p["net_cost5_usd_per_fixed1oz"],
        "dd":p["max_realized_dd_usd_per_fixed1oz"],
        "positive_years":p["positive_years"],
        "preempted":p["ignored"]["preempted"]},allow_nan=False),flush=True)
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=MODES,required=True)
    parser.add_argument("--gate",choices=GATES,required=True)
    a=parser.parse_args()
    run(a.mode,a.gate)
