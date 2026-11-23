"""RIZAN R31.1 extended HOLD study after R31 results were inspected.

PREDECLARED follow-up horizons only. NOT independent blind confirmation.
Never promotes a system or touches Frozen V1, ForexScanner or cTrader LIVE.
"""
import argparse,json
from pathlib import Path
import r31_profit_grid as r31

EXTRA={
    "1W":(3,4,6,8),
    "1D":(3,5),
    "4h":(4,6),
}
STUDY="RIZAN_R311_EXTENDED_HOLDS_20261123"
OUTPUT=Path("artifacts/r311")

def run(tf,hold,mode):
    if tf not in EXTRA or hold not in EXTRA[tf]:
        raise ValueError("R311_HORIZON_NOT_PREDECLARED")
    if mode not in r31.MODES:
        raise ValueError("R311_UNKNOWN_MODE")
    # Supply only the checked extension, preserving R31 frozen originals.
    old=r31.HOLD
    try:
        r31.HOLD={**old,tf:EXTRA[tf]}
        result=r31.runner(tf,hold,mode)
    finally:
        r31.HOLD=old
    result["exploratory_extension_id"]=STUDY
    result["research_after_inspecting_r31"]=True
    result["limitations"].append(
        "R31.1 holding periods chosen AFTER viewing R31 and its W1 2025 spike; "
        "these are discovery folds, not independent forward validation"
    )
    OUTPUT.mkdir(parents=True,exist_ok=True)
    path=OUTPUT/f"r311-{tf}-h{hold}-{mode}.json"
    path.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R311_COMPLETE",
        "tf":tf,"hold":hold,"mode":mode,
        "net":result["hypothetical_net_profit_usd_per_1oz"],
        "dd":result["hypothetical_max_realized_drawdown_usd_per_1oz"],
        "trades":result["total_trades"],
        "year_positive":result["positive_eval_years"],
        "cost5":result["cost_sensitivity_net_profit"]["5.0"]
    }),flush=True)
    return result

def baseline(tf):
    if tf not in EXTRA:raise ValueError("R311_BASELINE_TF_UNKNOWN")
    import r31_baselines
    old=r31.HOLD
    try:
        r31.HOLD={**old,tf:EXTRA[tf]}
        report=r31_baselines.baseline(tf)
    finally:
        r31.HOLD=old
    report["exploratory_extension_id"]=STUDY
    report["research_after_inspecting_r31"]=True
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/f"r311-baseline-{tf}.json").write_text(
        json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R311_BASELINE_COMPLETE","tf":tf,
                      "holding_periods":list(report["baselines"])}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",required=True,choices=tuple(EXTRA))
    p.add_argument("--hold",type=int)
    p.add_argument("--mode",required=True,choices=(*r31.MODES,"baseline"))
    a=p.parse_args()
    if a.mode=="baseline":
        if a.hold is not None:raise ValueError("R311_BASELINE_HOLD_MUST_BE_OMITTED")
        baseline(a.tf)
    else:
        if a.hold is None:raise ValueError("R311_HOLD_REQUIRED")
        run(a.tf,a.hold,a.mode)
