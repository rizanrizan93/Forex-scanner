"""R31 context controls: never compare filtered search with no-trade / drift.

Fixed one-oz, exactly same next-open/hold-close backtest and cost scenarios
as R31. No refitting or test-year ranking; signals from previous bar only.
"""
import argparse,json
from pathlib import Path
import numpy as np
import r30_pareto_direction_search as source
from r31_profit_grid import exit_frames,choose_indices,metrics,COST_SCENARIOS,HOLD

OUT=Path("artifacts/r31_baseline")

def baseline(tf):
    scope="spliced" if tf in ("1h","4h") else "archived"
    d,z,_,valid,times,manifest=source.read_data(tf,scope)
    y=times.year.to_numpy()
    report={"contract":"R31_XAU_ONE_OUNCE_NO_SELECTION_BASELINES_V1",
            "symbol":"XAUUSD","tf":tf,"actual_source":manifest,
            "eval_years":list(range(2019,2027)),
            "execution_authority":False,"research_only":True,
            "baselines":{}}
    trend=np.asarray((z.ema8-z.ema21).to_numpy(float))
    adx=np.asarray(z.adx14.to_numpy(float))
    base_signals={
        "always_buy":(np.ones(len(d),bool),"BUY"),
        "always_sell":(np.ones(len(d),bool),"SELL"),
        "ema_buy":(trend>0,"BUY"),
        "ema_sell":(trend<0,"SELL"),
        "ema_adx_buy":((trend>0)&(adx>18),"BUY"),
        "ema_adx_sell":((trend<0)&(adx>18),"SELL"),
    }
    for h in HOLD[tf]:
        eligible_h,gross,finish,_=exit_frames(d,tf,h)
        eligible=valid&eligible_h&(y>=2019)&(y<=2026)
        k=f"h{h}"
        report["baselines"][k]={}
        for name,(active,side) in base_signals.items():
            picked=choose_indices(active,eligible,h)
            metrics2=metrics(picked,side,gross,cost=2.)
            year_net={}
            for yr in range(2019,2027):
                idx=picked[y[picked]==yr]
                year_net[str(yr)]=metrics(idx,side,gross,cost=2.)["net_usd_oz"]
            report["baselines"][k][name]={
                "n":len(picked),"net_usd_per_1oz_cost2":metrics2["net_usd_oz"],
                "profit_factor_cost2":metrics2["profit_factor"],
                "max_realized_dd_cost2":metrics2["max_drawdown_usd_oz"],
                "positive_years":sum(v>0 for v in year_net.values()),
                "yearly":year_net,
                "cost_scenarios":{
                    str(c):metrics(picked,side,gross,cost=c)["net_usd_oz"]
                    for c in COST_SCENARIOS
                },
            }
    OUT.mkdir(parents=True,exist_ok=True)
    dest=OUT/f"r31-baselines-{tf}.json"
    dest.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"tf":tf,"baseline":[{
        "hold":h,"max":max(((k,v["net_usd_per_1oz_cost2"]) for k,v in q.items()),key=lambda p:p[1])
    } for h,q in report["baselines"].items()]}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=tuple(HOLD),required=True)
    a=p.parse_args()
    baseline(a.tf)
