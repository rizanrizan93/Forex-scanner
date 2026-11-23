"""RIZAN R29.5: weak-side extension with cost-tail and macro-lag strata.

H1 BUY/SELL, H4 SELL (and BUY comparator), D1 BUY/SELL. Objective unchanged:
predict sign of the NEXT completed candle close-to-close, with independent
BUY and SELL heads and conflict=>WAIT. All thresholds, regimes, and families
are selected on the prior year's validation only.

Hypotheses:
 * H1/H4: penalize large losing closes on prior-year validation; consider
   London/NY session and trend-continuation/reversal strata.
 * D1: add lagged U.S. 2Y/10Y/real yield and broad-dollar context (NOT DXY).
   FRED current-vintage observations are delayed >=2 weekdays; historical
   vintages were NOT captured. Therefore D1 is exploratory, NEVER live/PIT.

Research remains adaptive on previously inspected 2023-2026 periods; no
price target/SL, fills, execution API or alteration to Frozen V1/ForexScanner.
"""
from __future__ import annotations

import argparse
import json
import numpy as np
import pandas as pd

import r29_direction60_walkforward as base
import r292_magnitude_regime_expansion as r292
from r17_macro_pilot import daily_macro,align

ORIGINAL_GROUPS=r292.feature_groups
ORIGINAL_GATES=r292.gates
ORIGINAL_VALUATION=r292.valuation
ORIGINAL_RANK=r292.policy_rank

MODE="tail_guard"
MACRO=None
MACRO_MANIFEST=None
MODES={"tail_guard":"precision","coverage_guard":"balanced"}


def feature_groups(tf,d,z):
    global MACRO,MACRO_MANIFEST
    groups=ORIGINAL_GROUPS(tf,d,z)
    if tf!="1D":return groups
    # Identical to r14.load_tf('1D') completed-candle decision timestamp.
    times=d.index+pd.Timedelta(hours=24)
    parts,meta=daily_macro()
    macro=align(parts,times,d.index)
    if macro.empty or macro.notna().sum().sum()<500:
        raise ValueError("R295_MACRO_CONTEXT_NOT_AVAILABLE")
    MACRO,MACRO_MANIFEST=macro,meta
    # No default/zero-filling missing official observations; each model
    # receives actual released/lagged data or drops that sample.
    tech=groups["technical_plus_events"]
    groups["lagged_macro"]=macro
    groups["lagged_macro_structure"]=pd.concat([macro,tech],axis=1)
    return groups


def gates(tf,z,times,side):
    g=ORIGINAL_GATES(tf,z,times,side)
    sign=1 if side=="BUY" else -1
    trend=(z.ema8-z.ema21)/z.atr14.replace(0,np.nan)
    last=z.clv
    impulse=sign*z.body
    flow=sign*z.di
    buy_sell={
        "trend_clv":(sign*trend>.10)&(sign*last>.25),
        "sweep_and_structure":(sign*z.sweep5>0)&(sign*z.break8>=0),
        "displacement_after_squeeze":(
            (z.bbwidth.shift(1)<z.bbmedian.shift(1))
            &(z.rangeratio>1.15)&(impulse>.30)),
        "high_conviction":(sign*trend>.30)&(flow>8)&(z.adx14>20),
        "opposite_sweep_reclaim":(sign*z.sweep5>0)&(impulse>.20),
        "trend_early":(sign*trend>0)&(sign*z.roc3<0)&(sign*last>.2),
    }
    for key,mask in buy_sell.items():
        g[key]=np.asarray(mask.fillna(False),bool)
    if tf in ("1h","4h"):
        london=times.tz_convert("Europe/London").hour
        ny=times.tz_convert("America/New_York").hour
        if tf=="1h":
            g["london_sweep"]=g["sweep_and_structure"]&((london>=8)&(london<13))
            g["ny_open_displacement"]=g["displacement_after_squeeze"]&((ny>=8)&(ny<12))
            g["london_ny_trend"]=g["high_conviction"]&(
                ((london>=8)&(london<16))|((ny>=8)&(ny<13)))
        else:
            g["london_sell_structure"]=g["trend_clv"]&((london>=8)&(london<17))
            g["ny_sweep_reclaim"]=g["opposite_sweep_reclaim"]&((ny>=8)&(ny<16))
    if tf=="1D" and MACRO is not None:
        # Alignment index is the historical d.index, identical to z.index.
        macro=MACRO.reindex(z.index)
        a=macro.get("DGS2_5")
        b=macro.get("DGS10_5")
        c=macro.get("DFII10_5")
        dollar=macro.get("DTWEXBGS_5")
        # Gold commonly has inverse associations with yield/USD direction,
        # but this is only an empirical HYPOTHESIS, not a live claim.
        if a is not None and b is not None:
            g["yield_2y10y_confluence"]=np.asarray(
                ((-sign*a)>0)&((-sign*b)>0),bool)
        if c is not None:
            g["real_yield_confluence"]=np.asarray((-sign*c)>0,bool)
        if dollar is not None:
            g["broad_dollar_confluence"]=np.asarray((-sign*dollar)>0,bool)
        if a is not None and b is not None and dollar is not None:
            g["usd_yield_all"]=np.asarray(
                ((-sign*a)>0)&((-sign*b)>0)&((-sign*dollar)>0),bool)
    return g


def valuation(y,mask,side,delta,half,min_n):
    out=ORIGINAL_VALUATION(y,mask,side,delta,half,min_n)
    if out is None:return None
    signed=delta[np.asarray(mask,bool)]*(1 if side=="BUY" else -1)
    net=signed-base.COST_USD_OZ
    if not len(net) or not np.isfinite(net).all():
        return None
    q10=float(np.quantile(net,.10))
    q20=float(np.quantile(net,.20))
    tail=net[net<=q20]
    neg=net[net<0]
    out["p10_net_usd_oz"]=round(q10,5)
    out["expected_shortfall20_usd_oz"]=round(float(tail.mean()),5)
    out["average_losing_signal_net_usd_oz"]=(
        round(float(neg.mean()),5) if len(neg) else 0.)
    out["average_winning_signal_net_usd_oz"]=(
        round(float(net[net>0].mean()),5) if (net>0).any() else 0.)
    return out


def rank(metric):
    """Prior-year metrics only; 2026 evaluation NEVER inspected here."""
    if metric is None:return None
    pass_precision=metric["accuracy"]>=.60
    supported=metric["validation_half_year_supported"]
    net_positive=metric["val_net_usd_oz"]>0
    q=metric["expected_shortfall20_usd_oz"]
    if MODE=="tail_guard":
        return (
            pass_precision and supported and net_positive,
            net_positive,supported,
            metric["wilson_lower95"],
            q,metric["val_net_usd_oz"],metric["coverage"],
        )
    return (
        pass_precision and supported and net_positive,
        supported,metric["wilson_lower95"],
        net_positive,metric["coverage"],q,metric["val_net_usd_oz"],
    )


def run(tf,mode):
    global MODE,MACRO,MACRO_MANIFEST
    if tf not in ("1h","4h","1D") or mode not in MODES:
        raise ValueError("R295_INVALID_TF_OR_MODE")
    MODE=mode;MACRO=None;MACRO_MANIFEST=None
    old=(base.feature_groups,base.gates,base.fold,base.CUTS,
         base.ENGINES,base.MINVAL,base.STRATEGY,
         r292.valuation,r292.policy_rank,r292.PRESET)
    try:
        r292.PRESET=MODES[mode]
        r292.valuation=valuation
        r292.policy_rank=rank
        base.feature_groups=feature_groups
        base.gates=gates
        base.fold=r292.fold
        base.CUTS=r292.CONFIG[r292.PRESET]["cutoffs"]
        base.ENGINES=r292.CONFIG[r292.PRESET]["models"]
        base.MINVAL={**base.MINVAL,**r292.CONFIG[r292.PRESET]["minimum"]}
        base.STRATEGY="R29_5_TAILRISK_MACROLAG_"+mode.upper()+"_20261123"
        result=base.run(tf)
        result["variant"]="R29.5 "+mode
        result["strategy"]={
            "objective":"previous-year precision, Wilson and payoff tail-risk",
            "macro":"D1 two-weekday-lag current-vintage diagnostic only",
            "not_PIT_verified":tf=="1D",
        }
        if MACRO_MANIFEST is not None:result["macro_source_manifest"]=MACRO_MANIFEST
        result["limitations"].append(
            "Same 2023–26 histories were examined repeatedly across R1–R29. "
            "This R29.5 experiment is not an independent blind test."
        )
        if tf=="1D":
            result["limitations"].append(
                "D1 uses historical CURRENT-vintage FRED/Treasury after a "
                "conservative 2-weekday lag; NOT a verified point-in-time data vintage, "
                "and broad-dollar DTWEXBGS is NOT tradable DXY."
            )
        target=base.ROOT/f"r295-{mode}-{tf}.json"
        target.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
        print(json.dumps({
            "tf":base.NAME[tf],"variant":"R29.5 "+mode,
            "passes":result["passes_all_predeclared_gates"],
            "coverage":result["coverage"],"aggregate":result["aggregate"],
            "receipt":str(target),
        }),flush=True)
        return result
    finally:
        (base.feature_groups,base.gates,base.fold,base.CUTS,
         base.ENGINES,base.MINVAL,base.STRATEGY,
         r292.valuation,r292.policy_rank,r292.PRESET)=old
        MACRO=None;MACRO_MANIFEST=None


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",required=True,choices=("1h","4h","1D"))
    p.add_argument("--mode",required=True,choices=tuple(MODES))
    a=p.parse_args()
    run(a.tf,a.mode)
