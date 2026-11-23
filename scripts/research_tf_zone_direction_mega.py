"""RIZAN R30: causal independent-TF direction x supply/demand replay, 2012-2026.

Research challenger models, NOT exact frozen R25/R11/R29.2/R18/R27/R24
parity or broker fills. 128 deterministic direction configurations and up to
16,384 zone configurations per TF = 2,097,152 rule evaluations. Historical
bar resolution cannot prove M1/M5 first touch or intrabar sequencing.
Conservative stop-first tie; entry NEXT bar OPEN after closed rejection.

Selection: 2012-2020 development, 2021-2023 selection, 2024-2026
retrospective evaluation (previously researched, NOT pristine holdout).
No trading APIs, write permissions, cBot state or deployment pathways.
"""
from __future__ import annotations
import argparse, glob, hashlib, heapq, json, math, os
from pathlib import Path
import numpy as np
import pandas as pd

TF = {"H1":"1h", "H4":"4h", "D1":"1D", "W1":"1W"}
SOURCE = {"H1":"HISTDATA_R10_M1_DERIVED", "H4":"HISTDATA_R10_M1_DERIVED",
          "D1":"HISTDATA_R98_M1_DERIVED", "W1":"HISTDATA_R98_M1_DERIVED_W1"}
MODEL_COUNT = 128
ZONE_COUNT = 4**7
OUT = Path("artifacts/r30")
OUT.mkdir(parents=True, exist_ok=True)


def load(tf):
    if tf in ("H1","H4"):
        paths=sorted(glob.glob(f"/tmp/r30/r10-{TF[tf]}-*.csv"))
    else:
        paths=sorted(glob.glob("/tmp/r30/daily-*.csv"))
    if len(paths)!=15:
        raise RuntimeError(f"INCOMPLETE_2012_2026_SHARDS:{tf}:found={len(paths)}")
    years=[int(Path(p).stem.split("-")[-1]) for p in paths]
    if sorted(years)!=list(range(2012,2027)):
        raise RuntimeError(f"MISSING_OR_DUPLICATE_YEARS:{tf}:{years}")
    frames=[]
    digests={}
    for p,yr in zip(paths,years):
        data=Path(p).read_bytes()
        digests[str(yr)]=hashlib.sha256(data).hexdigest()
        z=pd.read_csv(p,index_col=0,parse_dates=True)
        if z.index.tz is None or z.index.has_duplicates or not z.index.is_monotonic_increasing:
            raise ValueError(f"INVALID_SHARD_INDEX:{tf}:{yr}")
        if not {"o","h","l","c"}.issubset(z):
            raise ValueError(f"OHLC_FIELDS_MISSING:{tf}:{yr}")
        if z.empty or not (z.index.year==yr).all():
            raise ValueError(f"SHARD_YEAR_MISMATCH:{tf}:{yr}")
        if not np.isfinite(z[["o","h","l","c"]].to_numpy(float)).all():
            raise ValueError(f"NONFINITE_OHLC:{tf}:{yr}")
        if ((z.l<=0)|(z.h<z[["o","c","l"]].max(axis=1))
               |(z.l>z[["o","c"]].min(axis=1))).any():
            raise ValueError(f"BROKEN_OHLC:{tf}:{yr}")
        frames.append(z[["o","h","l","c"]].astype(float))
    daily=pd.concat(frames).sort_index()
    if daily.index.has_duplicates or daily.index.year.min()!=2012 or daily.index.year.max()!=2026:
        raise ValueError("DATA_SHARD_CONCAT_INVALID")
    if tf=="W1":
        group=daily.index.floor("D")-pd.to_timedelta(daily.index.dayofweek,unit="D")
        daily=daily.groupby(group).agg(
            o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),
            days=("c","size"))
        daily=daily.loc[daily.days>=3].drop(columns="days")
    return daily,digests


def rsi(c,n=14):
    delta=c.diff()
    up=delta.clip(lower=0).ewm(alpha=1/n,adjust=False).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/down.replace(0,np.nan))


def prepare(d):
    high,low,open_,close=(d[k] for k in ("h","l","o","c"))
    tr=pd.concat([high-low,(high-close.shift()).abs(),
                  (low-close.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean().replace(0,np.nan)
    vol=(atr/close).rolling(80,min_periods=25).rank(pct=True).fillna(.5)
    r=rsi(close).fillna(50)
    ema={span:close.ewm(span=span,adjust=False).mean().to_numpy()
         for span in (5,8,13,21)}
    momentum={span:(close-close.shift(span)).to_numpy()
              for span in (2,3,5,8,13,21,34,55)}
    return {"atr":atr.to_numpy(float),"vol":vol.to_numpy(float),
            "rsi":r.to_numpy(float),"ema":ema,"mom":momentum}


def raw_events(d,f,tf):
    """Events appear only after closed source-TF displacement/BOS candles.

    Each event stores an immutable feature snapshot at formation. Touch,
    rejection, entry and outcome are calculated strictly AFTER formation.
    """
    a=d[["o","h","l","c"]].to_numpy(float)
    oo,hh,ll,cc=a.T
    atr=f["atr"]
    n=len(d)
    prior4h=pd.Series(hh).shift(1).rolling(4).max().to_numpy()
    prior4l=pd.Series(ll).shift(1).rolling(4).min().to_numpy()
    events=[]
    for base in (1,2,3):
        for i in range(65,n-18):
            v=atr[i];span=hh[i]-ll[i]
            if not np.isfinite(v) or v<=0 or span<.35*v:
                continue
            body=abs(cc[i]-oo[i])/max(span,1e-8)
            if body<.18:continue
            side=1 if cc[i]>oo[i] else -1
            bl=float(ll[i-base:i].min());bh=float(hh[i-base:i].max())
            width=bh-bl
            if width<=0 or width>2.2*v:continue
            if side==1:
                if cc[i]<=bh:continue
                bos=(cc[i]-prior4h[i])/v
            else:
                if cc[i]>=bl:continue
                bos=(prior4l[i]-cc[i])/v
            if not np.isfinite(bos) or bos<-.02:continue
            # Find first retest after source candle closes, never same bar.
            first=None
            for j in range(i+1,min(n-17,i+13)):
                if (hh[j]>=bl and ll[j]<=bh):
                    first=j
                    break
                if (side==1 and cc[j]<bl-.25*v) or (side==-1 and cc[j]>bh+.25*v):
                    break
            if first is None:continue
            # Completed touch/rejection only. Next-bar open is earliest proxy
            # entry; do not enter at the future-selected touch close.
            j=first
            confirmed=(cc[j]>bh and cc[j]>oo[j] if side==1
                       else cc[j]<bl and cc[j]<oo[j])
            if not confirmed or j+1>=n:continue
            entry_index=j+1
            # fixed reference stop = zone distal +/- 0.10 ATR; target 1.5R.
            entry=float(oo[entry_index])
            stop=(bl-.10*v if side==1 else bh+.10*v)
            risk=(entry-stop)*side
            if risk<.08*v or risk>3*v:continue
            tp=entry+side*1.5*risk
            completed=entry_index
            exit_price=float(cc[entry_index])
            for k in range(entry_index,min(n,entry_index+8)):
                stop_hit=ll[k]<=stop if side==1 else hh[k]>=stop
                tp_hit=hh[k]>=tp if side==1 else ll[k]<=tp
                completed=k
                if stop_hit: # pessimistic when both occur in one bar
                    exit_price=stop
                    break
                if tp_hit:
                    exit_price=tp
                    break
                exit_price=float(cc[k])
            net=(exit_price-entry)*side-.70
            # Cases crossing annual partition boundaries are purged later.
            event={
                "formation":i, "entry_index":entry_index, "exit_index":completed,
                "year":int(d.index[i].year),"side":side,
                "base":base,"displacement":span/v,"body":body,
                "bos":bos,"width":width/v,"vol":float(f["vol"][i]),
                "retest_lag":first-i,"net":net,"risk":risk,
                "cost_scenario":.70, "entry":entry, "exit":exit_price,
            }
            events.append(event)
    if not events:raise RuntimeError(f"NO_REPLAY_ZONE_EVENTS:{tf}")
    return events


def model_votes(d,f,events):
    idx=np.asarray([e["formation"] for e in events],int)
    c=d.c.to_numpy(float)
    sides=np.asarray([e["side"] for e in events],dtype=np.int8)
    out=[]
    for m in (2,3,5,8,13,21,34,55):
        for span in (5,8,13,21):
            for cut in (50,53,56,60):
                mom=f["mom"][m][idx]*sides>0
                trend=(c[idx]-f["ema"][span][idx])*sides>0
                r=(f["rsi"][idx]-50)*sides>(cut-50)
                # Side-specific technical direction, known at zone formation.
                out.append((mom.astype(np.int8)+trend.astype(np.int8)
                            +r.astype(np.int8))>=2)
    assert len(out)==MODEL_COUNT
    return out


def zone_axes(events):
    x=lambda col: np.asarray([e[col] for e in events])
    base=x("base");disp=x("displacement");body=x("body")
    bos=x("bos");width=x("width");vol=x("vol");lag=x("retest_lag")
    return [
        [np.ones(len(events),bool),base==1,base==2,base==3],
        [disp>=v for v in (.35,.6,.9,1.2)],
        [body>=v for v in (.18,.30,.45,.60)],
        [bos>=v for v in (-.02,.00,.10,.25)],
        [width<=v for v in (2.2,1.5,1.0,.6)],
        [np.ones(len(events),bool),vol>=.25,vol>=.50,vol<=.50],
        [lag<=v for v in (12,6,3,1)],
    ]


def wilson(k,n):
    if n<=0:return 0.0
    q=k/n;z=1.96
    return (q+z*z/(2*n)-z*math.sqrt(q*(1-q)/n+z*z/(4*n*n)))/(1+z*z/n)


def pack(a):
    return np.packbits(np.asarray(a,bool),bitorder="little")


def candidate_mask(axis,model,cfg):
    mask=model.copy()
    for i in range(7):mask &= axis[i][(cfg>>(2*i))&3]
    return mask


def metrics(events,selected,year_begin,year_end, *, overlap_guard=False,cost_extra=0):
    selected=selected & np.asarray([year_begin<=e["year"]<=year_end
                    and year_begin<=int(e["year"])<=year_end
                    and year_begin<=int(e["year"])<=year_end
                    for e in events],bool)
    # Drop targets maturing after the final calendar year of a fold.
    selected &= np.asarray([int(e["exit_year"])<=year_end for e in events],bool)
    indices=np.flatnonzero(selected)
    if overlap_guard:
        keep=[];last_exit=-1
        for i in sorted(indices,key=lambda k:events[k]["entry_index"]):
            if events[i]["entry_index"]<=last_exit:continue
            keep.append(i);last_exit=events[i]["exit_index"]
        indices=np.asarray(keep,int)
    nets=np.asarray([events[i]["net"]-cost_extra for i in indices],float)
    n=len(indices);wins=int((nets>0).sum())
    gains=float(nets[nets>0].sum()) if n else 0.
    losses=float(-nets[nets<0].sum()) if n else 0.
    equity=np.cumsum(nets) if n else np.array([])
    dd=float(np.max(np.maximum.accumulate(np.r_[0,equity])[1:]-equity)) if n else 0.
    annual={str(y):{"n":int(sum(events[i]["year"]==y for i in indices)),
                    "net_usd_oz":round(float(sum(events[i]["net"]-cost_extra for i in indices
                                                if events[i]["year"]==y)),4)}
            for y in range(year_begin,year_end+1)}
    return {
        "n":n,"wins":wins,"win_rate":round(wins/n,6) if n else None,
        "wilson_lower95":round(wilson(wins,n),6) if n else None,
        "net_usd_oz":round(float(nets.sum()),4),
        "expectancy_usd_oz":round(float(nets.mean()),4) if n else None,
        "profit_factor":round(gains/losses,5) if losses else None,
        "max_additive_drawdown_usd_oz":round(dd,4),
        "annual":annual,
    }


def sweep(tf,cap=ZONE_COUNT,models=MODEL_COUNT):
    d,source_hash=load(tf)
    features=prepare(d)
    events=raw_events(d,features,tf)
    for event in events:
        event["exit_year"]=int(d.index[event["exit_index"]].year)
    z=zone_axes(events)
    mv=model_votes(d,features,events)
    base_year=np.asarray([e["year"] for e in events])
    mature_year=np.asarray([e["exit_year"] for e in events])
    good=np.asarray([e["net"]>0 for e in events],bool)
    dev=(base_year>=2012)&(base_year<=2020)&(mature_year<=2020)
    val=(base_year>=2021)&(base_year<=2023)&(mature_year<=2023)
    evl=(base_year>=2024)&(base_year<=2026)&(mature_year<=2026)
    min_dev={"H1":70,"H4":35,"D1":15,"W1":5}[tf]
    min_val={"H1":35,"H4":20,"D1":9,"W1":3}[tf]
    if not (dev.sum()>=2*min_dev and val.sum()>=min_val and evl.sum()>0):
        raise RuntimeError(f"INSUFFICIENT_CAUSAL_RETEST_TRADES:{tf}:"
                           f"{int(dev.sum())}/{int(val.sum())}/{int(evl.sum())}")
    axis=np.asarray([[pack(q) for q in a] for a in z],dtype=np.uint8)
    devb,winb=pack(dev),pack(dev&good)
    heap=[];tested=eligible=0
    for model_id in range(min(models,MODEL_COUNT)):
        pred=pack(mv[model_id])
        for start in range(0,min(cap,ZONE_COUNT),256):
            ids=np.arange(start,min(start+256,cap,ZONE_COUNT),dtype=np.uint32)
            masks=np.broadcast_to(pred,(len(ids),len(pred))).copy()
            for a in range(7):
                np.bitwise_and(masks,axis[a,(ids>>(2*a))&3],out=masks)
            n=np.bitwise_count(np.bitwise_and(masks,devb)).sum(axis=1)
            k=np.bitwise_count(np.bitwise_and(masks,winb)).sum(axis=1)
            tested+=len(ids)
            good_idx=np.flatnonzero(n>=min_dev)
            eligible+=len(good_idx)
            if len(good_idx):
                p=k[good_idx]/n[good_idx]
                # Wilson approximation for fast screening; exact before selection.
                score=p-1.96*np.sqrt(p*(1-p)/n[good_idx])
                best=good_idx[np.argsort(score)[-min(8,len(good_idx)):]]
                for j in best:
                    q=(wilson(int(k[j]),int(n[j])),int(n[j]),model_id,int(ids[j]))
                    if len(heap)<192:heapq.heappush(heap,q)
                    elif q>heap[0]:heapq.heapreplace(heap,q)
        if model_id%16==15:
            print(json.dumps({"stage":"SCREENING","tf":tf,"models":model_id+1,
                              "combinations":tested,"eligible":eligible}),flush=True)
    finalists=[];seen=set()
    for _,_,model_id,cfg in sorted(heap,reverse=True):
        mask=candidate_mask(z,mv[model_id],cfg)
        signature=hashlib.sha256(pack(mask&val)).hexdigest()
        if signature in seen:continue
        seen.add(signature)
        valid_metrics=metrics(events,mask,2021,2023)
        if valid_metrics["n"]<min_val:continue
        if valid_metrics["expectancy_usd_oz"] is None:continue
        finalists.append((valid_metrics["wilson_lower95"],
                          valid_metrics["expectancy_usd_oz"],
                          valid_metrics["n"],model_id,cfg,valid_metrics,mask))
    finalists.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
    top=[]
    for _,_,_,model_id,cfg,vm,mask in finalists[:8]:
        # Annual and no-overlap costs evaluated only AFTER all selection.
        top.append({
            "model_id":model_id,"zone_config":cfg,
            "zone_axis_choices":[int((cfg>>(2*a))&3) for a in range(7)],
            "development":metrics(events,mask,2012,2020),
            "selection":vm,
            "retrospective_evaluation":metrics(events,mask,2024,2026,overlap_guard=True),
            "stress_cost_plus_0_8_usd_oz":metrics(
                events,mask,2024,2026,overlap_guard=True,cost_extra=.8),
            "signal_mask_sha256":hashlib.sha256(pack(mask)).hexdigest(),
        })
    report={
        "contract":"RIZAN_R30_CAUSAL_PER_TF_ZONE_REPLAY_V1",
        "timeframe":tf,"source":SOURCE[tf],"source_shard_sha256":source_hash,
        "first_candle":d.index[0].isoformat(),"last_candle":d.index[-1].isoformat(),
        "candle_count":len(d),"zone_events_rejected_or_wait":None,
        "valid_zone_retest_events":len(events),
        "event_counts":{"development":int(dev.sum()),"selection":int(val.sum()),
                        "retrospective_evaluation":int(evl.sum())},
        "direction_model_variants":min(models,MODEL_COUNT),
        "zone_config_variants":min(cap,ZONE_COUNT),
        "parameter_combinations_actually_evaluated":tested,
        "parameter_combinations_full_space":MODEL_COUNT*ZONE_COUNT,
        "eligible_development_combinations":eligible,
        "evaluation_selection":"MAX_WILSON_LOWER95_ON_2021_2023_ONLY",
        "top_candidates":top,
        "research_only":True,"execution_authority":False,"execution_influence":False,
        "not_original_frozen_model_parity":True,
        "no_intrabar_sequence_proof":True,
        "cost_assumption_usd_oz":0.7,
        "stress_extra_cost_usd_oz":0.8,
        "limitations":[
            "Research challengers are deterministic own-TF technical direction models, NOT faithful frozen R25/R11/R29.2/R18/R27/R24 reconstructions",
            "All zone events formed after closed candle; retest/rejection confirmed on later closed candle; entry at following open",
            "H1/H4/D1/W1 OHLC cannot resolve first intrabar stop/target or M15->M5 confirmation; stop-first tie is conservative",
            "Selection performed on 2021-2023; 2024-2026 already studied, not pristine holdout; model-selection multiplicity remains",
            "Historical HistData secondary feed may not match cTrader FP Markets trading sessions/spread/rollover",
            "Fixed $0.70/oz cost scenario and $0.80 stress surcharge are NOT verified broker costs",
            "Overlapping development signals can inflate screening; final out-of-sample estimates exclude overlapping positions",
            "No split-second timing, liquidity execution, realized P&L, leverage, cBot integration or order authority",
        ]
    }
    file=OUT/f"r30-{tf}.json"
    file.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R30_DONE","tf":tf,
                      "candles":len(d),"events":len(events),
                      "models":min(models,MODEL_COUNT),"tested":tested,
                      "top":top[:1]}),flush=True)
    return report


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--tf",choices=list(TF),required=True)
    ap.add_argument("--zone-configs",type=int,default=ZONE_COUNT)
    ap.add_argument("--direction-models",type=int,default=MODEL_COUNT)
    args=ap.parse_args()
    if not 1<=args.zone_configs<=ZONE_COUNT or not 1<=args.direction_models<=MODEL_COUNT:
        raise SystemExit("CONFIG_CAP_OUT_OF_RANGE")
    sweep(args.tf,args.zone_configs,args.direction_models)
