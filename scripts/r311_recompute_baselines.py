"""Fix source-evidence R31.1 baseline horizon binding and recompute in seal job.

The initial R31.1 benchmark jobs accidentally imported R31's default HOLD
dictionary before overriding it. Recompute the genuinely extended holding
periods against their independently SHA-validated source bars. Model runs
were not affected; they correctly overrode R31.HOLD prior to runner().
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import r31_baselines as baseline
import r31_profit_grid as r31

EXTRA={"1W":(3,4,6,8),"1D":(3,5),"4h":(4,6)}
CONTRACT="RIZAN_R311_EXTENDED_HOLDS_20261123"
OUT=Path("artifacts/r311")

def run(tf):
    if tf not in EXTRA:raise ValueError("R311_UNKNOWN_BASELINE")
    old_r31,old_base=r31.HOLD,baseline.HOLD
    try:
        r31.HOLD={**old_r31,tf:EXTRA[tf]}
        baseline.HOLD=r31.HOLD
        packet=baseline.baseline(tf)
    finally:
        r31.HOLD,baseline.HOLD=old_r31,old_base
    if set(packet["baselines"])!=set(f"h{x}" for x in EXTRA[tf]):
        raise ValueError("R311_CORRECTED_BASELINES_NOT_EXTENDED")
    packet["exploratory_extension_id"]=CONTRACT
    packet["research_after_inspecting_r31"]=True
    packet["correction"]="R311_INITIAL_BASELINE_JOBS_USED_ORIGINAL_SHORT_HOLDS_SUPERSEDED"
    packet["recomputed_with_correct_extended_hold_binding"]=True
    packet["execution_authority"]=False
    OUT.mkdir(parents=True,exist_ok=True)
    target=OUT/f"r311-baseline-{tf}.json"
    target.write_text(json.dumps(packet,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R311_CORRECTED_EXTENDED_BASELINES",
      "tf":tf,"horizons":list(packet["baselines"]),
      "top":{h:max(((k,v["net_usd_per_1oz_cost2"]) for k,v in obj.items()),
                     key=lambda p:p[1])
            for h,obj in packet["baselines"].items()}}),flush=True)
    return packet

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=tuple(EXTRA),required=True)
    a=p.parse_args()
    run(a.tf)
