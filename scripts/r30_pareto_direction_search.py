"""RIZAN R30 — selective directional accuracy-versus-frequency Pareto study.

XAUUSD completed H1/H4/D1/W1 -> NEXT completed candle CLOSE-to-CLOSE sign.
Track true n, precision, coverage, cost-adjusted mean and stability by year.
Evaluate fixed 3 OBJECTIVES chosen on PREVIOUS YEAR only:
 - precision: high prior-year Wilson lower bound, positive mean net
 - balanced: 60%-leaning score with a sizeable prior-year sample
 - frequency: highest prior-year number of signals subject to prior-year
              precision >=58%, positive mean net and half-year support.
Examination of prior 2023–26 results means this is NOT an untouched blind OOS.
Do not claim signal-count increase from high frequency before actual forward
results. No orders, model replacement, or cTrader trading code.

Historical completeness:
 - D1/W1 require original R9.8 full 2012–26 daily provenance
 - H1/H4 2019–26 R10 if --scope archived; NEVER call full 2012–26
 - H1/H4 only use --scope full if every year 2012–26 is present with per-year
   SHA-provenance for 2012–2018 from r30 backfill.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from r10_million import ohlc_indicators,wilson
from r102_calibrated import context as causal_context
from r14_multitimeframe_direction import load_tf
import r29_direction60_walkforward as base
import r292_magnitude_regime_expansion as model_source

VERSIONS={"precision":"Precision","balanced":"Balanced","frequency":"High Frequency"}
THRESHOLDS=(.50,.53,.56,.60,.65,.70)
MODEL_TYPES=("ridge","hgb")
TIMEFRAMES=("1h","4h","1D","1W")
GATES=(
    "all","trend_follow","countertrend","vol_high","vol_low",
    "trend_highvol","trend_impulse","bos_displacement",
    "sweep_reversal","trend_strong","trend_pullback",
    "break_hold","high_vol_trend",
    "london_trend","ny_breakout","london_sweep",
)
MIN_VALID={"1h":100,"4h":40,"1D":25,"1W":10}
MIN_AGG={"1h":150,"4h":65,"1D":60,"1W":22}
COST=0.70
ROOT=Path("artifacts/r30_pareto")
CONTRACT="RIZAN_R30_XAU_PARETO_OOSLIKE_2012_2026_V1"


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def load_intraday(tf,scope):
    if tf not in ("1h","4h"):raise ValueError("R30_INTRADAY_TF_INVALID")
    files={}
    for path in glob.glob(f"/tmp/r10/r10-{tf}-*.csv"):
        files[int(Path(path).stem.rsplit("-",1)[-1])]=Path(path)
    if scope=="full":
        for path in glob.glob(f"/tmp/r30_early/r10-{tf}-*.csv"):
            yr=int(Path(path).stem.rsplit("-",1)[-1])
            if yr in files:raise ValueError("R30_DUPLICATE_SOURCE_YEAR")
            files[yr]=Path(path)
        years=set(range(2012,2027))
        if set(files)!=years:
            raise ValueError(f"R30_FULL_2012_2026_NOT_AVAILABLE_{tf}:missing={sorted(years-set(files))}")
        for yr in range(2012,2019):
            manifest=Path(f"/tmp/r30_early/r30-backfill-provenance-{yr}.json")
            if not manifest.is_file():
                raise ValueError(f"R30_MISSING_EARLY_PROVENANCE_{yr}")
            proof=json.loads(manifest.read_text())
            ref=proof.get("shards",{}).get(tf,{})
            if (proof.get("contract")!="R30_XAUUSD_HISTDATA_H1_H4_UTC_2012_2018_SHARD_V1"
                or proof.get("year")!=yr
                or ref.get("sha256")!=sha(files[yr])
                or proof.get("execution_authority") is not False):
                raise ValueError("R30_OLD_INTRADAY_SHA_MISMATCH")
    else:
        years=set(range(2019,2027))
        if set(files)!=years:
            raise ValueError(f"R30_2019_2026_NOT_AVAILABLE_{tf}:missing={sorted(years-set(files))}")
    a=[]
    manifest={}
    for year in sorted(years):
        f=files[year]
        df=pd.read_csv(f,index_col=0,parse_dates=True)
        if (df.index.tz is None or df.index.year.min()!=year
                or df.index.year.max()!=year
                or not df.index.is_unique
                or not df.index.is_monotonic_increasing
                or not set(("o","h","l","c")).issubset(df.columns)):
            raise ValueError("R30_BAD_INTRADAY_SHARD_"+str(year))
        if ((df.h<df[["o","c"]].max(axis=1)) |
                (df.l>df[["o","c"]].min(axis=1))).any():
            raise ValueError("R30_INTRADAY_PRICE_CANDLE_INVALID")
        a.append(df)
        manifest[year]={"rows":len(df),"sha256":sha(f)}
    d=pd.concat(a).sort_index()
    if not d.index.is_unique or d.index.tz is None:
        raise ValueError("R30_COMBINED_CANDLE_DUPLICATION")
    return d,manifest


def read_data(tf,scope):
    if tf in ("1D","1W"):
        d,z,x,y,valid,times=load_tf(tf)
        years=set(d.index.year)
        if not set(range(2012,2027)).issubset(years):
            raise ValueError("R30_DAILY_SOURCE_NOT_2012_2026")
        return d,z,y,valid,times,{
            "source":"ORIGINAL_R98_2012_2026_HISTDATA",
            "actual_years":sorted(years),
            "scope":"FULL_D1_W1_FROM_2012",
            "data_provenance":"GitHub R9.8 shards original run 44886465487"}
    d,manifest=load_intraday(tf,scope)
    h1,_=load_intraday("1h",scope)
    hours=1 if tf=="1h" else 4
    z=ohlc_indicators(d)
    causal_context(z,h1,hours)
    old=d.c.to_numpy(float)
    nxt=d.c.shift(-1).to_numpy(float)
    times=d.index+pd.Timedelta(hours=hours)
    gaps=(d.index.to_series().shift(-1)-d.index.to_series()).to_numpy()
    valid=(gaps==np.timedelta64(hours,'h'))&np.isfinite(old)&np.isfinite(nxt)&(old!=nxt)
    y=(nxt>old).astype(np.int8)
    cols=["d1_mom","d1_trend","w1_mom","w1_trend"]
    valid &= np.isfinite(z[cols].to_numpy(float)).all(axis=1)
    return d,z,y,valid,times,{
        "source":"R30_FULL_HISTDATA_2012_2026" if scope=="full"
                   else "ORIGINAL_R10_2019_2026",
        "actual_years":sorted(manifest),
        "shard_sha256_rows":manifest,
        "scope":scope,
    }


def selection_metrics(y,activated,side,delta,period):
    active=np.asarray(activated,bool)
    n=int(active.sum())
    if n==0:return None
    want=1 if side=="BUY" else 0
    correct=int(np.sum(y[active]==want))
    sign=1 if side=="BUY" else -1
    pnl=sign*delta[active]-COST
    half1=int(np.sum(active & (period<=6)))
    half2=n-half1
    return {
        "n":n,"correct":correct,"accuracy":correct/n,
        "wilson":float(wilson(correct,n)),
        "coverage":n/len(active),
        "net_mean_usd_oz":float(np.mean(pnl)),
        "net_p10_usd_oz":float(np.quantile(pnl,.1)),
        "half_year":[half1,half2],
    }


def choose(entries,mode,tf):
    """Return selected candidate using PREVIOUS CALENDAR YEAR outcomes only."""
    minimum=MIN_VALID[tf]
    eligible=[]
    for e in entries:
        q=e["validation"]
        if (q["n"]<minimum or min(q["half_year"])<max(2,int(.07*minimum))
                or q["net_mean_usd_oz"]<=0):
            continue
        if mode=="frequency":
            if q["accuracy"]<.58:continue
            rank=(q["n"],q["wilson"],q["net_mean_usd_oz"])
        elif mode=="precision":
            rank=(q["wilson"],q["accuracy"],q["n"])
        else:
            if q["accuracy"]<.56:continue
            rank=(q["wilson"]+.09*q["coverage"],q["n"],q["net_mean_usd_oz"])
        eligible.append((rank,e))
    if not eligible:return None
    return max(eligible,key=lambda a:(a[0],a[1]["key"]))[1]


def annual_fold(tf,year,d,z,y,valid,times,groups,gates):
    # No leakage: targets on train and selection period mature before boundary.
    original_close=d.c.to_numpy(float)
    delta=d.c.shift(-1).to_numpy(float)-original_close
    month=np.asarray(times.month)
    scores={}
    for group,frame in groups.items():
        X=frame.to_numpy(float)
        usable=valid & np.isfinite(X).all(axis=1)
        tr,va,te=base.split_masks(times,usable,year,window=6)
        minv=MIN_VALID[tf]
        if (tr.sum()<(850 if tf=="1h" else 300 if tf=="4h" else 200 if tf=="1D" else 70)
            or va.sum()<minv*2 or te.sum()<minv):
            continue
        for family in MODEL_TYPES:
            model=model_source.model_factory(family)
            model.fit(X[tr],y[tr])
            pval=model.predict_proba(X[va])[:,1]
            ptest=model.predict_proba(X[te])[:,1]
            scores[(group,family)]=(pval,ptest,va,te)
    by_side={}
    for side in ("BUY","SELL"):
        sign=1 if side=="BUY" else -1
        candidate=[]
        for (group,family),(pval,ptest,va,te) in scores.items():
            side_prob=pval if side=="BUY" else 1-pval
            for gate in GATES:
                if gate not in gates[side]:continue
                g=np.asarray(gates[side][gate],bool)
                for threshold in THRESHOLDS:
                    mask=(side_prob>=threshold)&g[va]
                    if mask.sum()<MIN_VALID[tf]:continue
                    met=selection_metrics(y[va],mask,side,delta[va],month[va])
                    if met is None:continue
                    candidate.append({
                        "key":(group,family,gate,threshold),
                        "group":group,"model":family,
                        "gate":gate,"threshold":threshold,
                        "validation":met,
                    })
        by_side[side]={}
        for mode in VERSIONS:
            best=choose(candidate,mode,tf)
            if best is None:
                by_side[side][mode]={"selected":None,"reason":"NO_VALIDATION_APPROVED_CANDIDATE"}
                continue
            pval,ptest,va,te=scores[(best["group"],best["model"])]
            prob=ptest if side=="BUY" else 1-ptest
            active=(prob>=best["threshold"])&np.asarray(
                gates[side][best["gate"]],bool)[te]
            by_side[side][mode]={
                "selected":{k:best[k] for k in ("group","model","gate","threshold","validation")},
                "ids":np.flatnonzero(te),"mask":active,
            }
    outcomes={}
    for mode in VERSIONS:
        buy=np.zeros(len(d),bool)
        sell=np.zeros(len(d),bool)
        raw_b=by_side["BUY"][mode];raw_s=by_side["SELL"][mode]
        for row,mask in ((raw_b,buy),(raw_s,sell)):
            if row.get("selected"):mask[row["ids"]]=row["mask"]
        both=buy&sell
        buy &= ~both
        sell &= ~both
        annual_valid=valid & (times.year==year)
        ids=np.flatnonzero(annual_valid)
        out={
            "year":year,"eligible":int(len(ids)),
            "conflicts":int(both.sum()),"total_signals":int((buy|sell)[ids].sum()),
            "coverage":float((buy|sell)[ids].mean()) if len(ids) else 0.,
            "sides":{},
        }
        for side,mask,entry in (("BUY",buy,raw_b),("SELL",sell,raw_s)):
            met=selection_metrics(y[ids],mask[ids],side,delta[ids],month[ids])
            out["sides"][side]={
                "selected":entry.get("selected"),
                "actual":met,
                "reason":entry.get("reason"),
            }
        outcomes[mode]=out
    return outcomes


def aggregate(tf,mode,annual):
    sides={}
    for side in ("BUY","SELL"):
        rows=[r["sides"][side]["actual"] for r in annual if r["sides"][side]["actual"]]
        n=sum(r["n"] for r in rows)
        k=sum(r["correct"] for r in rows)
        if n:
            # Weighted mean: sum per-signal hypothetical net dollars across years.
            mean=sum(r["net_mean_usd_oz"]*r["n"] for r in rows)/n
            sides[side]={
                "n":n,"correct":k,"accuracy":k/n,
                "wilson_lower95":float(wilson(k,n)),
                "net_mean_after_assumed_cost_usd_oz":mean,
                "years_with_signals":len(rows),
                "min_annual_accuracy":min(r["accuracy"] for r in rows),
                "max_annual_accuracy":max(r["accuracy"] for r in rows),
                "positive_net_annual_years":int(sum(r["net_mean_usd_oz"]>0 for r in rows)),
            }
        else:
            sides[side]={"n":0,"correct":0,"accuracy":None,
                         "net_mean_after_assumed_cost_usd_oz":None,
                         "years_with_signals":0}
    e=sum(q["eligible"] for q in annual)
    total=sum(q["total_signals"] for q in annual)
    return {
        "mode":mode,"tf":base.NAME[tf],
        "eligible":e,"signals":total,"coverage":total/max(1,e),
        "BUY":sides["BUY"],"SELL":sides["SELL"],
        "all_required_gates":all(
            sides[side]["n"]>=MIN_AGG[tf] and
            sides[side]["accuracy"] is not None and
            sides[side]["accuracy"]>.60 and
            sides[side]["net_mean_after_assumed_cost_usd_oz"]>0 and
            sides[side]["years_with_signals"]>=3
            for side in ("BUY","SELL")
        ),
    }


def frontier(variants):
    """Points not dominated on each side's joint n, precision and net mean."""
    out={}
    for side in ("BUY","SELL"):
        valid=[
            q for q in variants if q[side]["n"]>0
            and q[side]["net_mean_after_assumed_cost_usd_oz"]>0
        ]
        un=[]
        for a in valid:
            if not any(
                b["mode"]!=a["mode"] and
                b[side]["n"]>=a[side]["n"] and
                b[side]["accuracy"]>=a[side]["accuracy"] and
                b[side]["net_mean_after_assumed_cost_usd_oz"]>=a[side]["net_mean_after_assumed_cost_usd_oz"] and
                (b[side]["n"]>a[side]["n"] or
                 b[side]["accuracy"]>a[side]["accuracy"] or
                 b[side]["net_mean_after_assumed_cost_usd_oz"]>a[side]["net_mean_after_assumed_cost_usd_oz"])
                for b in valid
            ):
                un.append(a["mode"])
        out[side]=un
    return out


def run(tf,scope):
    if tf not in TIMEFRAMES or scope not in ("archived","full"):
        raise ValueError("R30_INVALID_TF_SCOPE")
    d,z,y,valid,times,source=read_data(tf,scope)
    groups=model_source.feature_groups(tf,d,z)
    allowed={
        side:model_source.gates(tf,z,times,side) for side in ("BUY","SELL")
    }
    # Full history 2012-26: first six calendar years are for training,
    # and 2018 is a first diagnostic; primary comparison 2019-26.
    years=list(range(2019,2027)) if tf in ("1D","1W") or scope=="full"
          else [2024,2025,2026]
    permode={mode:[] for mode in VERSIONS}
    for year in years:
        outcomes=annual_fold(tf,year,d,z,y,valid,times,groups,allowed)
        for mode,detail in outcomes.items():
            permode[mode].append(detail)
        print(json.dumps({
            "tf":base.NAME[tf],"scope":source["scope"],"year":year,
            "modes":{k:{"coverage":v["coverage"],
                        "signals":v["total_signals"],
                        "buy":v["sides"]["BUY"]["actual"],
                        "sell":v["sides"]["SELL"]["actual"]}
                     for k,v in outcomes.items()}
        },allow_nan=False),flush=True)
    reports=[aggregate(tf,mode,permode[mode]) for mode in VERSIONS]
    output={
        "contract":CONTRACT,"research_only":True,
        "execution_authority":False,"execution_influence":False,
        "timeframe":base.NAME[tf],
        "historical_scope_requested":"2012-2026",
        "historical_scope_actual":source,
        "eval_years":years,
        "target":"direction of next fully completed candle close-minus-previous close",
        "objective":"max accuracy AND signal count, net-positive prior-year selection",
        "selection_only_on_previous_year":True,
        "pareto_candidate_models":list(VERSIONS),
        "fixed_thresholds":list(THRESHOLDS),"fixed_gate_candidates":list(GATES),
        "cost_scenario_usd_oz":COST,
        "variants":reports,"pareto_frontier":frontier(reports),
        "annual_results":permode,
        "limitations":[
            "2019–2026 H1/H4 is NOT full intraday 2012–2026; full run requires all 2012–2018 SHA-audited shards",
            "Test years 2019–2026 already examined in earlier studies; NOT an untouched holdout",
            "Yearly selection from previous year reduces direct label leakage but DOES NOT remove research-process multiple testing",
            "Close-to-close signed returns after assumed 0.70 USD/oz cost are NOT executable fills",
            "No evidence of institutional smart money flow; OHLC-derived SMC/ICT-style gates are proxies",
            "No live model promotion unless independent fresh forward observation passes",
        ],
    }
    ROOT.mkdir(parents=True,exist_ok=True)
    filename=ROOT/f"r30-pareto-{tf}-{scope}.json"
    filename.write_text(json.dumps(output,indent=2,allow_nan=False)+"\n")
    print(json.dumps({
        "file":str(filename),"scope":source["scope"],
        "tf":base.NAME[tf],
        "results":reports,"pareto_frontier":output["pareto_frontier"]
    },allow_nan=False),flush=True)
    return output


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=TIMEFRAMES,required=True)
    p.add_argument("--scope",choices=("archived","full"),default="archived")
    a=p.parse_args()
    run(a.tf,a.scope)
