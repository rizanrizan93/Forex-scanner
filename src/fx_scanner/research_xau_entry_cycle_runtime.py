"""Reproducible year replay and walk-forward report for the cycle experiment."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from statistics import median
import pandas as pd
from .research_xau_entry_cycle import candidate_grid, replay, next_cycle, RESEARCH_VERSION
from .research_xau_entry_tp_precision_v284 import metrics, _wilson_lower
from .research_xau_v229_historical_v242 import price_arrays, simulate_year
from .research_xau_v229_historical_v242_year_runtime import _download

KEYS = ["E1_T1"] + [f"D{depth}_T{slot}_B{buffer:g}_{mode}"
    for depth in (25,50,75) for slot in (1,2) for buffer in (0.,.5) for mode in ("LIMIT","RECLAIM")]
# Both baseline and candidates share this shorter research hold.
HOLD_MINUTES = 240


def score(rows, key, mode):
    result = metrics(rows,key,mode)
    sample=[r["pairs"][key][mode] for r in rows]
    fast=sum(bool(r.get("fast_precision_tp")) for r in sample)
    times=[r["holding_minutes"] for r in sample if r["state"]=="TP"]
    reaction=[r["reaction_minutes"] for r in sample if r.get("reaction_minutes") is not None]
    cycles=[r["cycle"] for r in sample if r.get("cycle",{}).get("state") != "CENSORED"]
    result.update(fast_precision_tp=fast, fast_joint_rate=fast/len(sample) if sample else None,
                  fast_wilson_lower=_wilson_lower(fast,len(sample)),
                  median_tp_minutes=median(times) if times else None,
                  median_reaction_minutes=median(reaction) if reaction else None,
                  cycle_evaluable_opportunities=len(cycles),
                  cycle_successes=sum(bool(r.get("cycle_success")) for r in cycles),
                  next_opposite_candidates=sum(r.get("state")=="SELECTED" for r in cycles))
    return result


def aggregate(shards):
    if not shards or any(s["research_version"] != RESEARCH_VERSION for s in shards):
        raise ValueError("missing or mismatched shards")
    years=[s["year"] for s in shards]
    if len(set(years)) != len(years):
        raise ValueError("duplicate years")
    rows=[r for s in shards for r in s["rows"] if not r.get("censored")]
    folds=[]
    for year in sorted(years):
        cutoff=pd.Timestamp(year=year,month=1,day=1,tz="UTC")
        train=[r for r in rows if r["year"]<year and pd.Timestamp(r["mature_at"])<cutoff]
        test=[r for r in rows if r["year"]==year]
        fold=dict(test_year=year,train_plans=len(train),test_plans=len(test),eligible=False)
        if len(train)<30 or len(test)<30:
            fold["reason"]="INSUFFICIENT_PAIRED_HISTORY"
        else:
            baseline=score(train,"E1_T1","base")
            eligible=[]
            for key in KEYS:
                base,stress=score(train,key,"base"),score(train,key,"stress")
                if (base["fill_rate"] >= baseline["fill_rate"]-.05
                    and base["tp_per_opportunity"] >= baseline["tp_per_opportunity"]
                    and stress["expectancy_r_per_opportunity"]>0):
                    eligible.append((base["fast_wilson_lower"],stress["expectancy_r_per_opportunity"],key))
            if eligible:
                chosen=max(eligible)[2]
                fold.update(eligible=True,selected_candidate=chosen,
                            baseline={m:score(test,"E1_T1",m) for m in ("base","stress")},
                            selected={m:score(test,chosen,m) for m in ("base","stress")})
            else:
                fold["reason"]="NO_CANDIDATE_MEETS_FILL_TP_STRESS_GATES"
        folds.append(fold)
    return dict(research_version=RESEARCH_VERSION,execution_authority=False,execution_influence=False,
                years=sorted(years),mature_plans=len(rows),folds=folds,
                hold_minutes=HOLD_MINUTES,
                descriptive_only={key:score(rows,key,"base") for key in KEYS} if rows else {},
                limitations=["RETROSPECTIVE_V242_PARENT_TOUCH_CONDITIONED_UNIVERSE_NOT_PROSPECTIVE_OOS",
                             "FIXED_SPREAD_M1_PROXY_NOT_BROKER_FILL",
                             "FOUR_HOUR_HOLD_DIFFERS_FROM_V284_THIRTY_DAYS",
                             "NEW_OPPOSITE_PUBLICATIONS_ONLY_NO_AUTOMATIC_REVERSE",
                             "MULTIPLE_CANDIDATES_REQUIRE_FORWARD_DEMO_VALIDATION"],
                sources=[dict(year=s["year"],price_end=s["price_end"],provenance=s["price_provenance"]) for s in shards])


def year_replay(year, frame, provenance):
    frame=frame.copy()
    frame["timestamp"]=pd.to_datetime(frame["timestamp"],utc=True)
    if not frame["timestamp"].is_monotonic_increasing or frame["timestamp"].duplicated().any():
        raise ValueError("timestamps must be sorted and unique")
    values=frame[["open","high","low","close"]].apply(pd.to_numeric,errors="raise")
    if values.isna().any().any() or not values.map(lambda x: float('-inf') < x < float('inf')).all().all():
        raise ValueError("nonfinite OHLC")
    if ((values.high < values[["open","close","low"]].max(axis=1)) | (values.low > values[["open","close","high"]].min(axis=1))).any():
        raise ValueError("invalid OHLC")
    frame[["open","high","low","close"]]=values
    if provenance.get("failed_periods"):
        raise ValueError("incomplete provider download")
    plans=simulate_year(frame,target_year=year)["plans"]
    px=price_arrays(frame)
    rows=[]
    for plan in plans:
        mature=pd.Timestamp(plan["signal_expires_at"])+pd.Timedelta(minutes=2*HOLD_MINUTES+30)
        row=dict(plan_id=plan["plan_id"],year=year,mature_at=mature.isoformat(),censored=px.timestamps[-1]+pd.Timedelta(minutes=1)<mature)
        if row["censored"]:
            rows.append(row)
            continue
        grid=candidate_grid(plan)
        pairs={}
        for key in KEYS:
            pairs[key]={}
            for mode,spread,slip in (("base",.37,.002),("stress",.37*1.25,.002*1.5)):
                if key not in grid:
                    result=dict(state="MISSED",reason="NO_VALID_GEOMETRY",net_r=0.,precision_5_and_tp=False,fast_precision_tp=False)
                else:
                    result=replay(px=px,plan=plan,candidate=grid[key],spread_usd=spread,slippage_usd=slip,hold_minutes=HOLD_MINUTES)
                # Opposite plan catalog ends at this calendar year's boundary.
                if result["state"]=="TP" and (pd.Timestamp(result["exit_at"])+pd.Timedelta(minutes=30)).year != year:
                    result["cycle"]=dict(state="CENSORED",reason="NEXT_YEAR_PLAN_CATALOG_UNAVAILABLE")
                else:
                    result["cycle"]=next_cycle(first=result,first_plan=plan,plans=plans,px=px,key=key,spread_usd=spread,slippage_usd=slip,hold_minutes=HOLD_MINUTES)
                pairs[key][mode]=result
        if any(v["state"]=="CENSORED" for pair in pairs.values() for v in pair.values()):
            row["censored"]=True
        else:
            row["pairs"]=pairs
        rows.append(row)
    return dict(research_version=RESEARCH_VERSION,year=year,price_provenance=provenance,
                price_end=px.timestamps[-1].isoformat(),rows=rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int)
    parser.add_argument("--shards",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if bool(args.year)==bool(args.shards):
        parser.error("provide exactly one of --year or --shards")
    if args.year:
        csv=Path(f"/tmp/histdata/xau-entry-cycle-{args.year}.csv")
        provenance=_download(args.year,csv,args.output.with_suffix(".provenance.json"))
        result=year_replay(args.year,pd.read_csv(csv),provenance)
    else:
        paths=sorted(args.shards.rglob("xau-entry-cycle-20*.json"))
        shards=[json.loads(p.read_text()) for p in paths if not p.name.endswith(".provenance.json")]
        result=aggregate(shards)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(f"ENTRY_CYCLE output={args.output}")

if __name__=="__main__": main()
