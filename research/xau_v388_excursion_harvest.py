from __future__ import annotations
"""V388 research-only excursion-harvest challenger.

Uses only frozen V387 accepted trades. Challenger selection is performed on
2025 calibration only. The chosen policy is frozen before 2026 is evaluated.
No C4 selector, entry admission, structural SL, terminal TP, or execution
authority is changed.

The challenger addresses the observed V387 failure mode: favorable excursion
was frequently surrendered before the structural terminal target was reached.
A causal trigger at +R moves the remaining risk to cost-adjusted breakeven and
realizes a fixed partial. This is deliberately a small predeclared family, not
an optimizer.
"""
import argparse, json
from pathlib import Path
from statistics import median

POLICIES = [
    {"name":"BASELINE_TERMINAL","trigger_r":None,"partial":0.0},
    {"name":"EH075_P50_BE","trigger_r":0.75,"partial":0.50},
    {"name":"EH100_P50_BE","trigger_r":1.00,"partial":0.50},
    {"name":"EH075_P33_BE","trigger_r":0.75,"partial":0.33},
]
MIN_CAL_TRADES=8

def dd(xs):
    eq=peak=worst=0.0
    for x in xs:
        eq+=x; peak=max(peak,eq); worst=max(worst,peak-eq)
    return worst

def outcome(t,p):
    base=float(t["r_multiple"])
    trig=p["trigger_r"]
    if trig is None: return base
    mfe=float(t.get("mfe_r") or 0.0)
    # If terminal TP occurred before any later stop, preserve baseline realized R.
    if str(t.get("exit_reason"))=="TP_OPPOSING_HTF": return base
    if mfe + 1e-12 < trig: return base
    # Trigger was reached before the later recorded SL/timeout. At trigger:
    # realize partial at trigger R and move remainder to cost-adjusted BE (0R).
    return float(p["partial"])*float(trig)

def metrics(trades,p):
    xs=[outcome(t,p) for t in trades]
    wins=[x for x in xs if x>0]; losses=[x for x in xs if x<0]
    gp=sum(wins); gl=abs(sum(losses))
    return {
      "trades":len(xs),"win_rate":len(wins)/len(xs) if xs else None,
      "profit_factor_r":None if gl<=1e-12 else gp/gl,
      "expectancy_r":sum(xs)/len(xs) if xs else None,
      "total_r":sum(xs),"max_drawdown_r":dd(xs),
      "median_realized_r":median(xs) if xs else None,
      "protected_trade_count":sum(1 for t in trades if p["trigger_r"] is not None and str(t.get("exit_reason"))!="TP_OPPOSING_HTF" and float(t.get("mfe_r") or 0)>=p["trigger_r"]),
    }

def choose(rows):
    eligible=[r for r in rows if r["metrics"]["trades"]>=MIN_CAL_TRADES]
    # Robustness-first: positive expectancy required; then PF, expectancy, lower DD.
    positive=[r for r in eligible if (r["metrics"]["expectancy_r"] or -999)>0]
    pool=positive or eligible
    return max(pool, key=lambda r: ((r["metrics"]["profit_factor_r"] if r["metrics"]["profit_factor_r"] is not None else 999.0), r["metrics"]["expectancy_r"], -r["metrics"]["max_drawdown_r"]))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--cal",type=Path,required=True); ap.add_argument("--holdout",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); a=ap.parse_args()
    cal=json.loads(a.cal.read_text()); hold=json.loads(a.holdout.read_text())
    ct=list(cal.get("trades") or []); ht=list(hold.get("trades") or [])
    rows=[{"policy":p,"metrics":metrics(ct,p)} for p in POLICIES]
    champ=choose(rows); frozen=dict(champ["policy"])
    hm=metrics(ht,frozen)
    cm=champ["metrics"]
    payload={"schema":"XAU_V388_EXCURSION_HARVEST_V1","research_only":True,
      "execution_authority":False,"live_execution_enabled":False,
      "c4_selector":"M15_LB12_B020_FROZEN","selection_data":"2025_ONLY",
      "calibration_candidates":rows,"frozen_challenger":frozen,
      "calibration_2025":cm,"holdout_2026":hm,
      "degradation":{"expectancy_r":None if cm["expectancy_r"] is None or hm["expectancy_r"] is None else hm["expectancy_r"]-cm["expectancy_r"],
                     "profit_factor_r":None if cm["profit_factor_r"] is None or hm["profit_factor_r"] is None else hm["profit_factor_r"]-cm["profit_factor_r"],
                     "max_drawdown_r":hm["max_drawdown_r"]-cm["max_drawdown_r"]},
      "limitations":["Derived from V387 accepted trades; does not alter admission frequency.",
        "MFE trigger ordering is causal relative to a later SL, but exact intrabar trigger fills require a full M1 re-replay before promotion.",
        "Historical high-impact news gating remains unavailable in V387 source data."],
      "promotion_gate":{"requires_positive_calibration_expectancy":True,"requires_positive_holdout_expectancy":True,
        "requires_pf_gt_1_both":True,"requires_full_m1_rereplay_before_demo":True}}
    ok=(cm["expectancy_r"] or -1)>0 and (hm["expectancy_r"] or -1)>0 and (cm["profit_factor_r"] or 0)>1 and (hm["profit_factor_r"] or 0)>1
    payload["provisional_holdout_conclusion"]="PASS_TO_FULL_M1_REPLAY" if ok else "REJECT"
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print("V388_SUMMARY="+json.dumps(payload,sort_keys=True))
if __name__=="__main__": main()
