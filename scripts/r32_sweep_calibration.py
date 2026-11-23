"""R32 causal liquidity sweep x independent TF direction x M5 entry calibration.

128 proxy directional model variants x 4096 zone/session filters x 12
stops/targets per TF = 6,291,456 replays, four TF = 25,165,824
*evaluated parameter combinations* conditional on audited M5 source shards.
Model variants are new research proxies; no historical frozen R25/R11/R29.2/
R18/R27/R24 parity is implied. No future candles at signal or entry.
"""
from __future__ import annotations
import argparse,glob,hashlib,heapq,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from r32_liquidity_sweep_m5_events import TARGET_R,HOLD_M5,N_OUT,CONTRACT

TFS=("H1","H4","D1","W1")
MODEL_COUNT=128
ZONE_COUNT=4096
OUT=Path("artifacts/r32")
MINDEV={"H1":70,"H4":25,"D1":8,"W1":3}
MINVAL={"H1":45,"H4":16,"D1":6,"W1":3}


def wilson(k,n):
    if n<=0:return 0.
    p=k/n;z=1.96
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def pack(x):
    return np.packbits(np.asarray(x,dtype=bool),bitorder="little")


def load(tf,folder="/tmp/r32-events"):
    if tf not in TFS:raise ValueError("R32_UNKNOWN_SOURCE_TF")
    root=Path(folder)
    years=list(range(2012,2027))
    frames=[]
    sums={}
    required={"tf","year","side","entry_at","exit_at_0","pnl_0"}
    for year in years:
        path=root/f"r32-events-{tf}-{year}.csv.gz"
        meta=root/f"r32-events-receipt-{year}.json"
        if not path.is_file() or not meta.is_file():
            raise FileNotFoundError(f"R32_UNVERIFIED_2012_2026_YEAR:{tf}:{year}")
        receipt=json.loads(meta.read_text())
        if (receipt.get("contract")!=CONTRACT or receipt.get("year")!=year
             or receipt.get("source")!="R32_VERIFIED_DUKASCOPY_XAUUSD_M5_BID"
             or receipt.get("execution_authority") is not False
             or receipt.get("execution_influence") is not False):
            raise ValueError(f"R32_SOURCE_RECEIPT_INVALID:{tf}:{year}")
        z=pd.read_csv(path,low_memory=False)
        if int(receipt["counts"][tf])!=len(z):
            raise ValueError(f"R32_YEAR_EVENT_COUNT_MISMATCH:{tf}:{year}")
        if len(z):
            if not required.issubset(z.columns) or z.tf.ne(tf).any() or z.year.ne(year).any():
                raise ValueError(f"R32_SOURCE_EVENT_COLUMNS_INVALID:{tf}:{year}")
            frames.append(z)
        sums[str(year)]={"events":len(z),"source_sha256":receipt["source_sha256"]}
    if not frames:
        return pd.DataFrame(),sums
    data=pd.concat(frames,ignore_index=True)
    data["entry_at"]=pd.to_datetime(data.entry_at,utc=True)
    for j in range(N_OUT):
        data[f"exit_at_{j}"]=pd.to_datetime(data[f"exit_at_{j}"],utc=True,errors="coerce")
        data[f"pnl_{j}"]=pd.to_numeric(data[f"pnl_{j}"],errors="coerce")
    if data.entry_at.isna().any() or not data.entry_at.is_monotonic_increasing:
        # Raw event order by sweep-lookback is NOT chronological; sort by entry.
        data=data.sort_values(["entry_at","year","side"],kind="stable").reset_index(drop=True)
    if data.entry_at.dt.year.ne(data.year).any():
        raise ValueError("R32_ENTRY_CALENDAR_YEAR_MISMATCH")
    return data,sums


def model_votes(e):
    """Each side's prediction is derived at the LAST CLOSED SOURCE-TF bar."""
    if e.empty:return [np.zeros(0,dtype=bool)]*MODEL_COUNT
    s=e.side.to_numpy(int)
    c=e.direction_close.to_numpy(float)
    out=[]
    for lag in (3,5,8,13):
        mom=e[f"mom_{lag}"].to_numpy(float)*s>0
        for length in (8,21,34,55):
            trend=(c-e[f"ema_{length}"].to_numpy(float))*s>0
            for cut in (45,50,55,60):
                rel=(e.rsi.to_numpy(float)-50)*s>(cut-50)
                votes=mom.astype(np.int8)+trend.astype(np.int8)+rel.astype(np.int8)
                for need in (2,3):
                    out.append(votes>=need)
    assert len(out)==MODEL_COUNT
    return out


def zone_axes(e):
    if e.empty:return [[np.zeros(0,dtype=bool)]*4 for _ in range(6)]
    x=lambda name:e[name].to_numpy()
    b=x("lookback");depth=x("sweep_depth_atr");wick=x("wick_fraction")
    width=x("zone_fraction");method=x("confirmation");hour=x("hour_wib")
    return [
        [np.ones(len(e),bool),b==4,b==8,b==16],
        [depth>=v for v in (.04,.10,.20,.35)],
        [wick>=v for v in (.12,.30,.48,.64)],
        [np.ones(len(e),bool),np.isclose(width,.25),
         np.isclose(width,.50),np.isclose(width,.75)],
        [np.ones(len(e),bool),method=="REJECTION",
         method=="MSS",method=="FVG"],
        [np.ones(len(e),bool),
         (hour>=8)&(hour<14),
         (hour>=14)&(hour<20),
         (hour>=20)|(hour<2)]
    ]


def exact_metrics(e,selected,variant,start,end,stress=0.):
    if e.empty:return {"n":0,"wins":0,"win_rate":None,"wilson_lower95":None,
                        "net_usd_oz":0.,"expectancy_usd_oz":None,
                        "profit_factor":None,"max_dd_usd_oz":0.,"annual":{}}
    # Entry and exit year must remain wholly INSIDE the fold.
    begin=pd.Timestamp(f"{start}-01-01",tz="UTC")
    until=pd.Timestamp(f"{end+1}-01-01",tz="UTC")
    candidates=np.flatnonzero(selected&
        (e.entry_at>=begin).to_numpy()&(e.entry_at<until).to_numpy()&
        (e[f"exit_at_{variant}"]<until).to_numpy()&
        e[f"pnl_{variant}"].notna().to_numpy())
    entries=e.entry_at.to_numpy()
    exits=e[f"exit_at_{variant}"].to_numpy()
    kept=[];last_end=np.datetime64("1900-01-01")
    for i in candidates:
        if entries[i]<=last_end:continue
        kept.append(int(i));last_end=exits[i]
    p=e[f"pnl_{variant}"].to_numpy(float)
    x=p[kept]-stress if kept else np.asarray([],float)
    n=len(x);wins=int((x>0).sum())
    positive=float(x[x>0].sum()) if n else 0.
    negative=float(-x[x<0].sum()) if n else 0.
    cum=np.r_[0,np.cumsum(x)]
    dd=float((np.maximum.accumulate(cum)-cum).max()) if n else 0.
    years=e.entry_at.dt.year.to_numpy(int)
    annual={str(y):{
        "n":int(sum(years[i]==y for i in kept)),
        "net_usd_oz":round(float(sum(p[i]-stress for i in kept if years[i]==y)),4)}
        for y in range(start,end+1)}
    return {
        "n":n,"wins":wins,
        "win_rate":round(wins/n,6) if n else None,
        "wilson_lower95":round(wilson(wins,n),6) if n else None,
        "net_usd_oz":round(float(x.sum()),4),
        "expectancy_usd_oz":round(float(x.mean()),5) if n else None,
        "profit_factor":round(positive/negative,5) if negative else None,
        "max_dd_usd_oz":round(dd,4),"annual":annual,
    }


def qualifies(dev,val,stress,tf,floor):
    if dev["n"]<MINDEV[tf] or val["n"]<MINVAL[tf]:
        return False
    if (val["win_rate"] is None or val["win_rate"]<floor
        or dev["expectancy_usd_oz"] is None or dev["expectancy_usd_oz"]<=0
        or val["expectancy_usd_oz"] is None or val["expectancy_usd_oz"]<=0
        or stress["expectancy_usd_oz"] is None or stress["expectancy_usd_oz"]<=0
        or dev["profit_factor"] is None or dev["profit_factor"]<1.08
        or val["profit_factor"] is None or val["profit_factor"]<1.15
        or stress["profit_factor"] is None or stress["profit_factor"]<1.02):
        return False
    return sum(val["annual"][str(y)]["net_usd_oz"]>0
               for y in range(2021,2024))>=2


def config_mask(axes,pred,conf):
    m=pred.copy()
    for axis in range(6):m&=axes[axis][(conf>>(2*axis))&3]
    return m


def calibration(tf,model_start=0,models=16,caps=ZONE_COUNT):
    if tf not in TFS or model_start<0 or model_start+models>MODEL_COUNT:
        raise ValueError("R32_SWEEP_SCOPE_INVALID")
    if not 1<=caps<=ZONE_COUNT:raise ValueError("R32_ZONE_CONFIG_INVALID")
    e,coverage=load(tf)
    if e.empty:
        # Do NOT silently generate synthetic events or promote a zero-sample model.
        report={"contract":"RIZAN_R32_CALIBRATION_SHARD_V1","tf":tf,
                "model_start":model_start,"models":models,
                "zone_configs":caps,"exit_policies":N_OUT,
                "actual_evaluations":models*caps*N_OUT,
                "source_events":0,"source_years":coverage,
                "tiers":{"volume_55":{"pass":False,"qualified":0,"candidates":[]},
                         "precision_60":{"pass":False,"qualified":0,"candidates":[]}},
                "research_only":True,"execution_authority":False,
                "execution_influence":False,"frozen_model_parity":False}
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/f"r32-{tf}-models-{model_start}.json").write_text(json.dumps(report,indent=2)+"\n")
        return report
    model=model_votes(e);axes=zone_axes(e)
    packed_axes=np.asarray([[pack(x) for x in a] for a in axes],dtype=np.uint8)
    val_year=e.entry_at.dt.year.to_numpy(int)
    subsets={}
    for k in range(N_OUT):
        pp=e[f"pnl_{k}"].to_numpy(float)
        exit_year=e[f"exit_at_{k}"].dt.year.to_numpy(float)
        valid=np.isfinite(pp)&np.isfinite(exit_year)&(exit_year==val_year)
        dev=(val_year>=2012)&(val_year<=2020)&valid
        val=(val_year>=2021)&(val_year<=2023)&valid
        subsets[k]=(pack(dev),pack(dev&(pp>0)),pack(val),pack(val&(pp>0)))
    pools={(k,kind):[] for k in range(N_OUT) for kind in ("volume","precision")}
    actual=eligible=0
    for modelid in range(model_start,model_start+models):
        pred=pack(model[modelid])
        for start in range(0,caps,256):
            ids=np.arange(start,min(start+256,caps),dtype=np.uint32)
            masks=np.broadcast_to(pred,(len(ids),len(pred))).copy()
            for axis in range(6):
                np.bitwise_and(masks,packed_axes[axis,(ids>>(2*axis))&3],out=masks)
            for k in range(N_OUT):
                dv,dw,vv,vw=subsets[k]
                dn=np.bitwise_count(np.bitwise_and(masks,dv)).sum(axis=1)
                dk=np.bitwise_count(np.bitwise_and(masks,dw)).sum(axis=1)
                vn=np.bitwise_count(np.bitwise_and(masks,vv)).sum(axis=1)
                vk=np.bitwise_count(np.bitwise_and(masks,vw)).sum(axis=1)
                actual+=len(ids)
                good=np.flatnonzero((dn>=max(3,MINDEV[tf]//2))&
                                    (vn>=max(2,MINVAL[tf]//2)))
                if not len(good):continue
                dwr=dk[good]/dn[good];vwr=vk[good]/vn[good]
                good=good[(dwr>=.45)&(vwr>=.48)]
                eligible+=len(good)
                if not len(good):continue
                for kind in ("volume","precision"):
                    if kind=="volume":
                        score=vn[good]+.001*vk[good]/vn[good]
                    else:
                        pp=vk[good]/vn[good]
                        score=pp-1.96*np.sqrt(pp*(1-pp)/vn[good])
                    picks=good[np.argsort(score)[-min(5,len(good)):]]
                    heap=pools[(k,kind)]
                    for i in picks:
                        wr=vk[i]/vn[i]
                        lower=wr-1.96*np.sqrt(max(0.,wr*(1-wr))/vn[i])
                        key=(int(vn[i]),round(lower,6)) if kind=="volume" else (
                            round(lower,6),int(vn[i]))
                        obj=(key,modelid,int(ids[i]),k)
                        if len(heap)<128:heapq.heappush(heap,obj)
                        elif obj>heap[0]:heapq.heapreplace(heap,obj)
        print(json.dumps({"stage":"R32_SCREEN","tf":tf,"through_model":modelid,
                          "combinations":actual,"prequalified":eligible}),flush=True)

    ids=set()
    for heap in pools.values():
        ids.update((m,c,k) for _,m,c,k in heap)
    best={"volume_55":[],"precision_60":[]}
    diagnostics=[]
    for m,c,k in sorted(ids):
        mask=config_mask(axes,model[m],c)
        dev=exact_metrics(e,mask,k,2012,2020)
        val=exact_metrics(e,mask,k,2021,2023)
        stress=exact_metrics(e,mask,k,2021,2023,stress=.8)
        if val["n"]<max(3,MINVAL[tf]//2):continue
        row={
            "model_id":m,"zone_config":c,"outcome_variant":k,
            "rr":TARGET_R[k%4],"hold_m5":HOLD_M5[k//4],
            "zone_choices":[int((c>>(2*i))&3) for i in range(6)],
            "development":dev,"validation":val,"validation_stress":stress,
            "signal_mask_sha256":hashlib.sha256(pack(mask)).hexdigest()
        }
        diagnostics.append(row)
        for floor,label in ((.55,"volume_55"),(.60,"precision_60")):
            if qualifies(dev,val,stress,tf,floor):best[label].append((row,mask))
    # Rank by number of unique validation trades, then reliability, NOT 2024.
    tiers={}
    for label in best:
        rows=sorted(best[label],
            key=lambda pair:(pair[0]["validation"]["n"],
                             pair[0]["validation"]["wilson_lower95"] or 0,
                             pair[0]["validation"]["profit_factor"] or 0),reverse=True)
        finalists=[]
        for row,mask in rows[:5]:
            candidate={**row,
                "retrospective_2024_2026":exact_metrics(e,mask,row["outcome_variant"],2024,2026),
                "retrospective_2024_2026_cost_stress":exact_metrics(
                    e,mask,row["outcome_variant"],2024,2026,stress=.8)}
            finalists.append(candidate)
        tiers[label]={"pass":bool(rows),"qualified":len(rows),
                      "candidates":finalists}
    diagnostics.sort(key=lambda row:(row["validation"]["n"],
                                   row["validation"]["win_rate"] or 0),reverse=True)
    for row in diagnostics[:3]:
        mask=config_mask(axes,model[row["model_id"]],row["zone_config"])
        row["retrospective_2024_2026"]=exact_metrics(e,mask,row["outcome_variant"],2024,2026)
    result={
        "contract":"RIZAN_R32_CALIBRATION_SHARD_V1",
        "tf":tf,"model_start":model_start,"models":models,"zone_configs":caps,
        "exit_policies":N_OUT,"actual_evaluations":actual,
        "source_events":len(e),"source_years":coverage,
        "prequalified_packed_cases":eligible,"exact_evaluations":len(diagnostics),
        "tiers":tiers,"high_frequency_near_misses":diagnostics[:3],
        "selection_periods":{"development":"2012-2020","validation":"2021-2023",
                             "retrospective":"2024-2026_ALREADY_STUDIED"},
        "execution_authority":False,"execution_influence":False,
        "research_only":True,"frozen_model_parity":False,
        "limitations":[
            "Proxy direction models are NOT historical Frozen R25/R11/R29.2/R18/R27/R24 signals",
            "Dukascopy BID M5 is not FP Markets price/spread/commission parity",
            "No tick-level intrabar path; stop-first OHLC convention",
            "Censored gaps and year boundaries, no synthetic interpolation",
            "Cost USD0.70/oz and extra USD0.80 stress are assumptions",
            "Large multiple-hypothesis search and 2024-26 retrospective data previously studied",
            "NO auto-promotion, cBot changes, margin/leverage inference or live order authorization"
        ]
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/f"r32-{tf}-models-{model_start}.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R32_CALIBRATION_DONE","tf":tf,
                      "model_start":model_start,"actual":actual,
                      "source_events":len(e),"tiers":{
                          t:{"qualifying":v["qualified"],"best_val_n":
                            v["candidates"][0]["validation"]["n"] if v["candidates"] else None}
                          for t,v in tiers.items()}}),flush=True)
    return result

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--tf",choices=TFS,required=True)
    ap.add_argument("--model-start",type=int,default=0)
    ap.add_argument("--models",type=int,default=16)
    ap.add_argument("--zone-configs",type=int,default=ZONE_COUNT)
    a=ap.parse_args()
    calibration(a.tf,a.model_start,a.models,a.zone_configs)
