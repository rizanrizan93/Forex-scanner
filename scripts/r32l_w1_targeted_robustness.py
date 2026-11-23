"""R32L targeted W1 robustness receipt for 2 overlapping retrospective survivors.

Fixed W1 proxy models 138/142, zone config 0, RR=.60, hold=3 source weeks,
selected previously using 2021-23. No reselection on any tested period.
Retrospective across 2012-26 is NOT forward proof; two variants overlap.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import research_r31_high_coverage_precision as r31
import research_r32l_source_tf_sweep as r32

OUT=Path("artifacts/r32l")


def evaluate():
    d,source=r31.r30.load("W1")
    f=r31.r30.prepare(d)
    events=r32.liquidity_sweep_events(d,f,"W1")
    votes=r31.direction_votes(d,f,events)
    axis=r32.liquidity_axes(events)
    pnl,exits=r32.liquidity_outcomes(d,events)
    rows=[]
    for modelid in (138,142):
        # cfg=0 means every source-zone axis uses its first, baseline choice
        sel=votes[modelid].copy()
        for group in axis:
            sel &= group[0]
        # W1 outcome v=0: target 0.60R, hold 3 closed W1 source bars.
        row={"model_id":modelid,"zone_config":0,"rr":0.6,"holding_weeks":3,
             "formation_bars":len(events),
             "selection_2021_2023":r31.report_metrics(
                events,sel,"W1",d,pnl,exits,0,2021,2023),
             "development_2012_2020":r31.report_metrics(
                events,sel,"W1",d,pnl,exits,0,2012,2020),
             "retrospective_2024_2026":r31.report_metrics(
                events,sel,"W1",d,pnl,exits,0,2024,2026),
             "cost_stress_2024_2026":r31.report_metrics(
                events,sel,"W1",d,pnl,exits,0,2024,2026,stress=.8),
             "subperiods":[
                 {"period":f"{a}-{b}","metrics":r31.report_metrics(
                     events,sel,"W1",d,pnl,exits,0,a,b)}
                 for a,b in ((2012,2014),(2015,2017),(2018,2020),
                             (2021,2023),(2024,2026))]
        }
        rows.append(row)
    out={"contract":"RIZAN_R32L_W1_TARGETED_2012_2026_DIAGNOSTIC_V1",
         "source_sha256_by_year":source,
         "source_tf":"W1","m5_backtest":False,
         "model_parity_with_live_frozen":False,
         "research_only":True,"execution_authority":False,
         "execution_influence":False,
         "warning":"One family found after 33.55M multiple tests; two W1 models highly correlated; not external validation",
         "candidates":rows}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"r32l-w1-targeted-2012-2026.json").write_text(
        json.dumps(out,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R32L_W1_TARGETED_DONE",
        "rows":[{"model":x["model_id"],
                 "2012_2020":{k:x["development_2012_2020"].get(k) for k in
                       ("n","win_rate","profit_factor","net_usd_oz")},
                 "2021_2023":{k:x["selection_2021_2023"].get(k) for k in
                       ("n","win_rate","profit_factor","net_usd_oz")},
                 "2024_2026":{k:x["retrospective_2024_2026"].get(k) for k in
                       ("n","win_rate","profit_factor","net_usd_oz")}}
                for x in rows]}),flush=True)
    return out

if __name__=="__main__":
    evaluate()
