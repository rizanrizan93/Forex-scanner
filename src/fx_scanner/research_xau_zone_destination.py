"""Causal hourly zone census, destination labels and paired entry experiments.

Research only. Features and future labels are separate; no runtime consumer.
M1 timestamps are opens and close-derived evidence is available one minute later.
"""
from __future__ import annotations
from bisect import bisect_left, bisect_right
from collections import Counter
from typing import Any
import numpy as np
import pandas as pd
from .research_xau_zone_reversal_depth_v225 import (
    build_zones, causal_superseded_at, OBSERVATION_HOURS,
)
from .research_xau_v229_historical_v242 import price_arrays
from .research_xau_entry_cycle import replay

VERSION = "XAU_CAUSAL_ZONE_DESTINATION_1"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
HORIZONS = (30,120,240)
CLASSES = ("SUPPLY_FIRST","DEMAND_FIRST","NEITHER","AMBIGUOUS")
KEYS = tuple(f"{side}_D{depth}" for side in ("LONG","SHORT") for depth in (25,50,75))
MINUTE = pd.Timedelta(minutes=1)


def validate_frame(frame):
    frame=frame.copy()
    frame["timestamp"]=pd.to_datetime(frame["timestamp"],utc=True)
    if frame.empty or frame.timestamp.duplicated().any() or not frame.timestamp.is_monotonic_increasing:
        raise ValueError("prices must be nonempty, sorted and unique")
    for col in ("open","high","low","close"):
        frame[col]=pd.to_numeric(frame[col],errors="raise")
    values=frame[["open","high","low","close"]]
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("nonfinite OHLC")
    if ((frame.high < values.max(axis=1)) | (frame.low > values.min(axis=1))).any():
        raise ValueError("invalid OHLC")
    if any(t.second or t.microsecond for t in frame.timestamp):
        raise ValueError("M1 bar timestamps must be minute aligned")
    return frame


def causal_build_zones(frame):
    """Exclude detections backdated before the detector's 20-bar warmup.

    The shared imbalance detector starts scanning at bar 17 once 20 bars
    exist. Retrospective output from those first three bars was not available
    in an actual prefix replay. Keep its runtime behavior untouched here.
    """
    thresholds={}
    for tf,rule in (("M15","15min"),("H1","1h"),("H4","4h")):
        counts=frame.set_index("timestamp").resample(rule).size()
        opens=counts[counts>0].index
        thresholds[tf]=opens[19]+pd.Timedelta(rule) if len(opens)>=20 else None
    return tuple(z for z in build_zones(frame) if z.zone_class=="STRUCTURAL" or
                 (thresholds[z.timeframe] is not None and pd.Timestamp(z.available_at)>=thresholds[z.timeframe]))


def zone_catalog(zones, px):
    """Precompute outcomes for replay, never expose future death in features."""
    superseded=causal_superseded_at(zones)
    output={}
    for z in zones:
        available=pd.Timestamp(z.available_at)
        expiry=available+pd.Timedelta(hours=OBSERVATION_HOURS[z.timeframe])
        replacement=superseded.get(z.zone_id)
        end=min(expiry,pd.Timestamp(replacement)) if replacement else expiry
        start_i,end_i=bisect_left(px.timestamps,available),bisect_left(px.timestamps,end)
        closes=px.closes[start_i:end_i]
        broken=np.flatnonzero(closes < z.distal if z.direction=="LONG" else closes > z.distal)
        invalidated=px.timestamps[start_i+int(broken[0])]+MINUTE if len(broken) else None
        if invalidated is not None:
            end=min(end,invalidated)
        stop_i=bisect_left(px.timestamps,end)
        touches=(px.highs[start_i:stop_i]>=z.low)&(px.lows[start_i:stop_i]<=z.high)
        starts=np.flatnonzero(touches & ~np.r_[False,touches[:-1]]) if len(touches) else []
        touch_times=tuple(px.timestamps[start_i+int(i)]+MINUTE for i in starts)
        output[z.zone_id]=dict(zone=z,available=available,end=end,touches=touch_times,
                               expiry=expiry,invalidated=invalidated,replacement=replacement)
    return output


def feature_snapshot(px, at, active):
    """Uses only the contiguous sixty minutes ending at the decision time."""
    at=pd.Timestamp(at)
    i=bisect_left(px.timestamps,at)
    if i<60 or px.timestamps[i-1]!=at-MINUTE or px.timestamps[i-60]!=at-pd.Timedelta(hours=1):
        return dict(state="MISSING_PAST_HOUR",at=at.isoformat())
    price=float(px.closes[i-1])
    hour_range=max(float(np.max(px.highs[i-60:i])-np.min(px.lows[i-60:i])),.01)
    move=(price-float(px.opens[i-60]))/hour_range
    motion="UP" if move>.2 else "DOWN" if move<-.2 else "FLAT"
    records=[]
    for rec in active:
        z=rec["zone"]
        if not rec["available"]<=at<rec["end"]:
            continue
        records.append(dict(zone_id=z.zone_id,timeframe=z.timeframe,direction=z.direction,
                            low=z.low,high=z.high,proximal=z.proximal,distal=z.distal,
                            atr_points=z.atr_points,available_at=rec["available"].isoformat(),
                            age_minutes=(at-rec["available"]).total_seconds()/60,
                            past_touch_episodes=bisect_right(rec["touches"],at)))
    inside=[z["zone_id"] for z in records if z["low"]<=price<=z["high"]]
    demand=min((z for z in records if z["direction"]=="LONG" and z["high"]<price),
               key=lambda z:(price-z["high"],z["zone_id"]),default=None)
    supply=min((z for z in records if z["direction"]=="SHORT" and z["low"]>price),
               key=lambda z:(z["low"]-price,z["zone_id"]),default=None)
    d=(price-demand["high"])/hour_range if demand else None
    s=(supply["low"]-price)/hour_range if supply else None
    proximity=("DEMAND_NEARER" if d<s*.8 else "SUPPLY_NEARER" if s<d*.8 else "SIMILAR") if d is not None and s is not None else "UNPAIRED"
    return dict(at=at.isoformat(),state="PAIRED" if demand and supply else "UNPAIRED",price=price,
                hour_range=hour_range,momentum_60m=move,momentum_bucket=motion,
                proximity_bucket=proximity,demand_distance_hour_range=d,supply_distance_hour_range=s,
                active_zones=records,inside_zone_ids=inside,demand=demand,supply=supply)


def destination_label(px, feature, horizon):
    """Frozen outer edges; simultaneous touches stay ambiguous, never guessed."""
    if feature.get("state")!="PAIRED":
        return dict(state="UNAVAILABLE")
    at=pd.Timestamp(feature["at"])
    deadline=at+pd.Timedelta(minutes=horizon)
    start,end=bisect_left(px.timestamps,at),bisect_left(px.timestamps,deadline)
    # Reject gaps for this fixed-clock label, including closed-market windows.
    if end-start!=horizon or start>=len(px.timestamps) or px.timestamps[start]!=at or px.timestamps[end-1]!=deadline-MINUTE:
        return dict(state="CENSORED",reason="INCOMPLETE_CONTIGUOUS_HORIZON")
    for i in range(start,end):
        up=px.highs[i]>=feature["supply"]["low"]
        down=px.lows[i]<=feature["demand"]["high"]
        if up or down:
            return dict(state="AMBIGUOUS" if up and down else "SUPPLY_FIRST" if up else "DEMAND_FIRST",
                        known_at=(px.timestamps[i]+MINUTE).isoformat())
    return dict(state="NEITHER",known_at=deadline.isoformat())


def entry_labels(px, feature, catalog):
    """All six candidates share an observation, including no-fill/invalid RR."""
    if feature.get("state")!="PAIRED":
        return {}
    at=pd.Timestamp(feature["at"])
    result={}
    for side,source,opposing in (("LONG","demand","supply"),("SHORT","supply","demand")):
        z,other=feature[source],feature[opposing]
        sign=1 if side=="LONG" else -1
        stop=z["distal"]-sign*.15*z["atr_points"]
        target=(other["low"]-min(1.,.1*(other["high"]-other["low"])) if sign==1
                else other["high"]+min(1.,.1*(other["high"]-other["low"])))
        # The earlier lifecycle end is an event-driven cancellation label, not
        # a future feature or a reason to exclude this initial opportunity.
        expiry=min(at+pd.Timedelta(hours=4),catalog[z["zone_id"]]["end"])
        plan=dict(direction=side,stop=stop,plan_at=at.isoformat(),signal_expires_at=expiry.isoformat())
        for depth in (25,50,75):
            entry=z["high"]-(z["high"]-z["low"])*depth/100 if sign==1 else z["low"]+(z["high"]-z["low"])*depth/100
            risk,reward=sign*(entry-stop),sign*(target-entry)
            pair={}
            for mode,spread,slip in (("base",.37,.002),("stress",.4625,.003)):
                if expiry<=at or risk<=0 or reward/risk<1.5:
                    outcome=dict(state="MISSED",reason="INVALID_GEOMETRY_OR_EXPIRY",net_r=0.,precision_5_and_tp=False,fast_precision_tp=False)
                else:
                    outcome=replay(px=px,plan=plan,candidate=dict(entry=entry,target=target,mode="LIMIT"),
                                   spread_usd=spread,slippage_usd=slip,hold_minutes=240)
                pair[mode]=outcome
            result[f"{side}_D{depth}"]=dict(entry=entry,stop=stop,target=target,zone_id=z["zone_id"],costs=pair)
    return result


def reaction_after_destination(px, feature, destination):
    """Reaction from the frozen proximal vs close acceptance beyond distal.

    No credit for a reaction on the first-touch candle. Breaking wins ties.
    This is a price-path label, not an order fill or a fitted entry level.
    """
    side=destination.get("state")
    if side not in ("SUPPLY_FIRST","DEMAND_FIRST"):
        return dict(state="NO_UNAMBIGUOUS_TOUCH")
    z=feature["supply" if side=="SUPPLY_FIRST" else "demand"]
    sign=1 if z["direction"]=="LONG" else -1
    start_at=pd.Timestamp(destination["known_at"])-MINUTE
    start=bisect_left(px.timestamps,start_at)
    deadline=start_at+pd.Timedelta(hours=4)
    end=bisect_left(px.timestamps,deadline)
    if end-start!=240 or px.timestamps[end-1]!=deadline-MINUTE:
        return dict(state="CENSORED")
    proximal=z["high"] if sign==1 else z["low"]
    target=proximal+sign*.5*z["atr_points"]
    max_depth=0.
    for i in range(start,end):
        extreme=float(px.lows[i]) if sign==1 else float(px.highs[i])
        max_depth=max(max_depth,sign*(proximal-extreme)/(z["high"]-z["low"]))
        broken=sign*(float(px.closes[i])-z["distal"])<0
        reacted=i>start and (px.highs[i]>=target if sign==1 else px.lows[i]<=target)
        if broken or reacted:
            return dict(state="BREAK_FIRST" if broken else "REACTION_FIRST",zone_id=z["zone_id"],
                        max_depth_through_outcome=max_depth,ambiguous=bool(broken and reacted),
                        minutes_to_outcome=i-start+1,known_at=(px.timestamps[i]+MINUTE).isoformat())
    return dict(state="NEITHER",zone_id=z["zone_id"],max_depth_through_outcome=max_depth,
                known_at=deadline.isoformat())


def build_dataset(frame, *, target_year, zones=None):
    frame=validate_frame(frame)
    px=price_arrays(frame)
    zones=causal_build_zones(frame) if zones is None else zones
    catalog=zone_catalog(zones,px)
    ordered=sorted(catalog.values(),key=lambda r:(r["available"],r["zone"].zone_id))
    active=[]; cursor=0; rows=[]
    anchors=[t for t in px.timestamps if t.year==target_year and t.minute==0]
    for at in anchors:
        while cursor<len(ordered) and ordered[cursor]["available"]<=at:
            active.append(ordered[cursor]);cursor+=1
        active=[r for r in active if r["end"]>at]
        features=feature_snapshot(px,at,active)
        destinations={str(h):destination_label(px,features,h) for h in HORIZONS}
        entries=entry_labels(px,features,catalog)
        # Conservative maturity includes all pending+holding windows and gaps.
        maturity=at+pd.Timedelta(hours=8)
        for candidate in entries.values():
            for cost in candidate["costs"].values():
                if cost.get("exit_at"):
                    maturity=max(maturity,pd.Timestamp(cost["exit_at"]))
        rows.append(dict(year=target_year,features=features,labels=dict(destinations=destinations,entries=entries,
                                      reaction=reaction_after_destination(px,features,destinations["240"])),
                         mature_at=maturity.isoformat()))
    census=[]
    for rec in ordered:
        z=rec["zone"]
        if rec["available"].year>target_year:
            continue
        census.append(dict(zone_id=z.zone_id,timeframe=z.timeframe,direction=z.direction,low=z.low,high=z.high,
                           available_at=rec["available"].isoformat(),expires_at=rec["expiry"].isoformat(),
                           invalidated_known_at=rec["invalidated"].isoformat() if rec["invalidated"] is not None else None,
                           superseded_at=pd.Timestamp(rec["replacement"]).isoformat() if rec["replacement"] else None,
                           touch_episode_count=len(rec["touches"])))
    return dict(research_version=VERSION,execution_authority=False,execution_influence=False,year=target_year,
                price_end=px.timestamps[-1].isoformat(),rows=rows,zone_outcome_catalog=census)


def _bucket(features):
    return features["proximity_bucket"]+"|"+features["momentum_bucket"]


def fit_destination(rows,horizon):
    global_counts=Counter({c:1 for c in CLASSES}); groups={}
    for r in rows:
        outcome=r["labels"]["destinations"][str(horizon)]["state"]
        if outcome not in CLASSES:
            continue
        global_counts[outcome]+=1
        groups.setdefault(_bucket(r["features"]),Counter())[outcome]+=1
    total=sum(global_counts.values())
    prior={c:global_counts[c]/total for c in CLASSES}
    return dict(prior=prior,groups=groups,training_n=total-len(CLASSES))


def predict_destination(model,features):
    counts=model["groups"].get(_bucket(features),{})
    n=sum(counts.values())
    # A sparse cell backs off to the training prior; no claimed confidence.
    p={c:(counts.get(c,0)+20*model["prior"][c])/(n+20) for c in CLASSES} if n>=100 else dict(model["prior"])
    return dict(probabilities=p,training_cell_n=n,backoff=n<100)


def evaluate_destination(train,test,horizon):
    model=fit_destination(train,horizon)
    rows=[r for r in test if r["labels"]["destinations"][str(horizon)]["state"] in CLASSES]
    if not rows or model["training_n"]<100:
        return dict(n=len(rows),training_n=model["training_n"],state="INSUFFICIENT_PAIRED_HISTORY")
    brier=base_brier=correct=base_correct=0
    predictions=[]
    daily_deltas={}
    for r in rows:
        label=r["labels"]["destinations"][str(horizon)]["state"]
        forecast=predict_destination(model,r["features"])
        p=forecast["probabilities"];prior=model["prior"]
        brier+=sum((p[c]-(c==label))**2 for c in CLASSES)
        baseline_loss=sum((prior[c]-(c==label))**2 for c in CLASSES)
        model_loss=sum((p[c]-(c==label))**2 for c in CLASSES)
        base_brier+=baseline_loss
        daily_deltas.setdefault(r["features"]["at"][:10],[]).append(baseline_loss-model_loss)
        chosen=max(CLASSES,key=lambda c:p[c])
        correct+=chosen==label; base_correct+=max(CLASSES,key=lambda c:prior[c])==label
        predictions.append(dict(at=r["features"]["at"],observed=label,predicted=chosen,**forecast))
    bins=[]
    for lo,hi in ((0,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        group=[p for p in predictions if lo<=max(p["probabilities"].values())<hi]
        if group:
            bins.append(dict(lower=lo,upper=min(hi,1),n=len(group),mean_probability=sum(max(p["probabilities"].values()) for p in group)/len(group),
                             observed_frequency=sum(p["observed"]==p["predicted"] for p in group)/len(group)))
    sums=np.array([sum(v) for v in daily_deltas.values()])
    counts=np.array([len(v) for v in daily_deltas.values()])
    rng=np.random.default_rng(307)
    boot=[]
    for _ in range(1000):
        idx=rng.integers(0,len(sums),len(sums))
        boot.append(float(sums[idx].sum()/counts[idx].sum()))
    return dict(n=len(rows),training_n=model["training_n"],daily_block_brier_improvement_ci95=list(np.quantile(boot,[.025,.975])),
                accuracy=correct/len(rows),prior_accuracy=base_correct/len(rows),
                multiclass_brier=brier/len(rows),prior_multiclass_brier=base_brier/len(rows),
                calibration_bins=bins,backoff_rows=sum(p["backoff"] for p in predictions),
                outcomes=dict(Counter(p["observed"] for p in predictions)))


def entry_summary(rows,key,mode="base"):
    paired=[r for r in rows if r["labels"]["entries"] and all(
        v["state"]!="CENSORED" for c in r["labels"]["entries"].values() for v in c["costs"].values())]
    values=[r["labels"]["entries"][key]["costs"][mode] for r in paired]
    n=len(values);filled=sum(v["state"]!="MISSED" for v in values)
    return dict(opportunities=n,filled=filled,fill_rate=filled/n if n else 0,
                tp=sum(v["state"]=="TP" for v in values),
                fast_precise_tp=sum(bool(v.get("fast_precision_tp")) for v in values),
                expectancy_r=sum(v["net_r"] for v in values)/n if n else 0)


def aggregate(shards):
    if not shards or any(s["research_version"]!=VERSION for s in shards):
        raise ValueError("missing/mismatched shards")
    years=sorted(s["year"] for s in shards)
    if len(years)!=len(set(years)):
        raise ValueError("duplicate years")
    rows=[r for s in shards for r in s["rows"]]
    folds=[]
    for year in years:
        cutoff=pd.Timestamp(year=year,month=1,day=1,tz="UTC")
        train=[r for r in rows if r["year"]<year and pd.Timestamp(r["mature_at"])<cutoff]
        test=[r for r in rows if r["year"]==year]
        fold=dict(year=year,train_snapshots=len(train),test_snapshots=len(test))
        if len(train)<100:
            fold["state"]="INSUFFICIENT_TRAINING"
        else:
            fold.update(state="EVALUATED",destination={str(h):evaluate_destination(train,test,h) for h in HORIZONS})
            selected={}
            for side in ("LONG","SHORT"):
                baseline=entry_summary(train,f"{side}_D50")
                eligible=[]
                for d in (25,50,75):
                    key=f"{side}_D{d}"; base=entry_summary(train,key);stress=entry_summary(train,key,"stress")
                    if base["opportunities"]>=100 and base["fill_rate"]>=baseline["fill_rate"]-.05 and base["tp"]>=baseline["tp"] and stress["expectancy_r"]>0:
                        eligible.append((base["fast_precise_tp"],stress["expectancy_r"],key))
                key=max(eligible)[2] if eligible else None
                selected[side]=dict(candidate=key,baseline=entry_summary(test,f"{side}_D50"),
                                    selected=entry_summary(test,key) if key else None,
                                    selected_stress=entry_summary(test,key,"stress") if key else None)
            fold["entry_depth_selection"]=selected
        folds.append(fold)
    return dict(research_version=VERSION,execution_authority=False,execution_influence=False,
                years=years,total_hourly_snapshots=len(rows),snapshot_states=dict(Counter(r["features"]["state"] for r in rows)),
                zone_count=sum(len(s["zone_outcome_catalog"]) for s in shards),
                reaction_after_destination_counts=dict(Counter(r["labels"]["reaction"]["state"] for r in rows)),
                folds=folds,descriptive_entries={k:entry_summary(rows,k) for k in KEYS},
                limitations=["RETROSPECTIVE_FROZEN_ZONE_DETECTOR_NOT_PROSPECTIVE_VALIDATION",
                             "HOURLY_OBSERVATIONS_AND_TRADES_OVERLAP_NOT_INDEPENDENT_PORTFOLIO_RETURNS",
                             "DESTINATION_LABELS_ARE_MID_PRICE_BARRIERS_NOT_BROKER_FILLS",
                             "CANDLE_FILL_FIXED_SPREAD_PROXY_NO_DOM_HISTORY",
                             "DESTINATION_AND_ENTRY_MODELS_NOT_YET_A_VALIDATED_JOINT_EXECUTION_POLICY"],
                sources=[dict(year=s["year"],price_end=s["price_end"],provenance=s.get("price_provenance")) for s in shards])
