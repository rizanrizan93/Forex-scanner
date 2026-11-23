"""R29.1 predeclared SMC/ICT-inspired event-gated direction hypotheses.

Extends R29's independent BUY/SELL training, leakage embargo, matched annual
evaluation, evidence and cost guards. The only changes are candidate
OHLC-derived feature sets and predeclared causal regime gates. Terms like
"sweep" and "BOS" describe candle geometry, NOT verified institutional flow.

No test-year or live price is consulted to choose filters; these folds have
previously been inspected in R1-R29 and are not a pristine holdout.
"""
from __future__ import annotations
import argparse

import numpy as np
import pandas as pd

import r29_direction60_walkforward as base
from r16_direction_complexity import features as technical_features
from r21_horizon_specialists import price_specialist

ORIGINAL_GATES=base.gates


def structure_features(tf,d,z):
    c=d.c.astype(float);o=d.o.astype(float)
    h=d.h.astype(float);l=d.l.astype(float)
    atr=z.atr14.replace(0,np.nan)
    rng=(h-l).replace(0,np.nan)
    prevhi=h.shift(1).rolling(12).max()
    prevlo=l.shift(1).rolling(12).min()
    vol=z.atr_rank
    body=(c-o)/atr
    e=(z.ema8-z.ema21)/atr
    f=pd.DataFrame({
        "body_atr":body,
        "close_location":z.clv,
        "ema_atr":e,
        "di14":z.di,
        "adx14":z.adx14,
        "atr_rank":vol,
        "range_atr":rng/atr,
        "vol_expansion":rng/rng.shift(1).rolling(12).median().replace(0,np.nan),
        "high_break_12":(c>prevhi).astype(float),
        "low_break_12":(c<prevlo).astype(float),
        "high_sweep_12":((h>prevhi)&(c<prevhi)).astype(float),
        "low_sweep_12":((l<prevlo)&(c>prevlo)).astype(float),
        "distance_high_atr":(prevhi-c)/atr,
        "distance_low_atr":(c-prevlo)/atr,
        "signed_body_accel":body-body.shift(1).rolling(3).mean(),
        "atr_slope":atr.pct_change(3),
        "momentum_1":c.pct_change(1),
        "momentum_3":c.pct_change(3),
        "wick_top":(h-c.where(c>o,o))/rng,
        "wick_bottom":(c.where(c<o,o)-l)/rng,
        "squeeze_ratio":z.bbwidth/z.bbmedian.replace(0,np.nan),
        "impulse3":z.eff3,
        "breakout8":z.break8,
        "sweep5":z.sweep5,
    },index=d.index)
    if tf in ("1h","4h"):
        for col in ("d1_mom","d1_trend","w1_mom","w1_trend"):
            if col in z:f[col]=z[col]
    return f.replace([np.inf,-np.inf],np.nan)


def feature_groups(tf,d,z):
    event=structure_features(tf,d,z)
    technical=technical_features(z)
    if tf in ("1D","1W"):
        technical=technical.drop(columns=["hour_sin","hour_cos"],errors="ignore")
    if tf=="1h":
        f,sets=price_specialist(d,z,tf)
        return {
            "event_geometry":event,
            "event_session_context":pd.concat([
                event,f[["london_active","ny_active","asia_active",
                         "ny_open","london_open","hour_sin","hour_cos"]]],axis=1),
        }
    if tf=="4h":
        f,sets=price_specialist(d,z,tf)
        compact=f[sets["compact_structure"]]
        return {"event_geometry":event,
                "event_bos_context":pd.concat([event,compact],axis=1)
                                     .loc[:,lambda x:~x.columns.duplicated()]}
    return {
        "event_geometry":event,
        "event_technical_context":pd.concat([event,technical],axis=1)
                                    .loc[:,lambda x:~x.columns.duplicated()],
    }


def gates(tf,z,times,side):
    """All event gates depend on present/past completed candles only."""
    orig=ORIGINAL_GATES(tf,z,times,side)
    s=1 if side=="BUY" else -1
    t=(z.ema8-z.ema21)/z.atr14.replace(0,np.nan)
    g={
        "bos_displacement":(s*z.break8>0)&(s*z.body>.30)&(z.adx14>=18),
        "sweep_reversal":(s*z.sweep5>0)&(s*z.clv>.25),
        "displacement":(s*z.body>.55)&(z.rangeratio>=1.20),
        "trend_pullback":(s*t>0)&(s*z.roc3<0)&(s*z.clv>.15),
        "trend_impulse":(s*z.roc3>0)&(s*z.eff3>.25)&(z.adx14>=20),
        "range_rejection":(s*z.sweep5>0)&(z.atr_rank<=.65),
        "compression_release":(z.bbwidth.shift(1)<z.bbmedian.shift(1))
                               &(z.rangeratio>=1.25)&(s*z.body>.25),
        "strong_directional_pressure":(s*z.di>10)&(s*z.clv>.5)
                                       &(z.adx14>=22),
    }
    for k,v in g.items():
        orig[k]=np.asarray(v.fillna(False),dtype=bool)
    if tf=="1h":
        local=times.tz_convert("Europe/London").hour
        in_open=(local>=8)&(local<12)
        orig["london_open_bos"]=np.asarray(g["bos_displacement"]&in_open,bool)
        orig["london_open_sweep"]=np.asarray(g["sweep_reversal"]&in_open,bool)
    if tf=="4h":
        local=times.tz_convert("Europe/London").hour
        in_session=(local>=8)&(local<18)
        orig["london_bos"]=np.asarray(g["bos_displacement"]&in_session,bool)
        orig["london_sweep"]=np.asarray(g["sweep_reversal"]&in_session,bool)
    return orig


def run(tf):
    orig_features=base.feature_groups
    orig_gates=base.gates
    orig_version=base.STRATEGY
    orig_cuts=base.CUTS
    orig_minval=base.MINVAL
    try:
        base.feature_groups=feature_groups
        base.gates=gates
        # Keep minimum aggregate support identical; lower validation support
        # only enough to admit predeclared rarer liquidity events.
        base.MINVAL={**orig_minval,"1h":75,"4h":35,"1D":18,"1W":7}
        base.CUTS=(0.50,0.53,0.56,0.60,0.64,0.68,0.74,0.80)
        base.STRATEGY="R29_1_EVENT_STRUCTURE_PREDECLARED_20261123"
        result=base.run(tf)
        result["variant"]="R29.1 event-structure, BOS/sweep and session hypotheses"
        result["reference_baseline"]="R29_V1_PREDECLARED_20261123"
        result["limitations"].append(
            "Adding event gates after seeing R29 results is an adaptive research step; "
            "R29.1 must not be called a genuinely independent blind test."
        )
        target=base.ROOT/f"r291-event-{tf}.json"
        target.write_text(base.json.dumps(result,indent=2,allow_nan=False)+"\n")
        print(base.json.dumps({
            "variant":"R29.1","tf":base.NAME[tf],
            "passed":result["passes_all_predeclared_gates"],
            "aggregate":result["aggregate"],"coverage":result["coverage"],
            "file":str(target),
        }),flush=True)
        return result
    finally:
        base.feature_groups=orig_features
        base.gates=orig_gates
        base.STRATEGY=orig_version
        base.CUTS=orig_cuts
        base.MINVAL=orig_minval


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",required=True,choices=list(base.NAME))
    run(p.parse_args().tf)
