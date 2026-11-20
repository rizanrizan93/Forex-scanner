"""R7: causal, read-only XAU multi-horizon macro/flow factor research.

This does not ship vendor data, historical fitted weights, win probabilities
or a production trading instruction. Training requires independently captured
point-in-time features with each feature's ingestion timestamp. Incomplete
inputs are NOT silently backfilled with ex-post revised data.

Ridge on standardized features predicts LOG return over 1, 5, 21 or 252
future XAU trading sessions; model importance is relative absolute
standardized coefficient magnitude, NOT causal attribution. Separate
out-of-sample walk-forward audit is required for all skill claims.
"""
from __future__ import annotations

from math import exp, isfinite, log, sqrt
from typing import Any
import numpy as np
import pandas as pd

CONTRACT="RIZAN_XAU_R7_MULTIHORIZON_CAUSAL_RESEARCH_V1"
HORIZONS={"D1":1,"W1":5,"M1":21,"Y1":252}
TRAIN_MIN={"D1":300,"W1":500,"M1":900,"Y1":2000}
MIN_OOS={"D1":60,"W1":40,"M1":24,"Y1":15}
GROUPS={
    "REAL_RATES":{
        "real_yield_10y_change_bps","breakeven_10y_change_bps","us2y_change_bps"},
    "USD":{"dxy_change_pct"},
    "FED_POLICY":{"fed_path_revision_bps","fed_surprise_bps"},
    "RISK_LIQUIDITY":{"vix_change_pct","credit_spread_change_bps",
                      "liquidity_stress_z"},
    "FUTURES_FLOW":{"comex_oi_change_pct","cot_net_change_contracts",
                    "futures_orderflow_z"},
    "PHYSICAL_ETF":{"etf_flow_tonnes","central_bank_net_tonnes"},
    "GROWTH":{"global_pmi_surprise","global_gdp_revision_pct"},
    "PRICE_STRUCTURE":{"price_momentum_5d_pct","price_momentum_21d_pct",
                       "price_momentum_252d_pct","smc_structure_score"},
}
FEATURE_GROUP={name:group for group, names in GROUPS.items() for name in names}
FEATURES={
    "D1":("real_yield_10y_change_bps","us2y_change_bps",
          "dxy_change_pct","fed_surprise_bps",
          "vix_change_pct","futures_orderflow_z",
          "liquidity_stress_z","price_momentum_5d_pct","smc_structure_score"),
    "W1":("real_yield_10y_change_bps","us2y_change_bps",
          "dxy_change_pct","fed_path_revision_bps",
          "vix_change_pct","comex_oi_change_pct",
          "cot_net_change_contracts","etf_flow_tonnes",
          "price_momentum_21d_pct"),
    "M1":("real_yield_10y_change_bps","breakeven_10y_change_bps",
          "dxy_change_pct","fed_path_revision_bps",
          "vix_change_pct","comex_oi_change_pct",
          "cot_net_change_contracts","etf_flow_tonnes",
          "central_bank_net_tonnes","price_momentum_21d_pct",
          "global_pmi_surprise"),
    "Y1":("real_yield_10y_change_bps","breakeven_10y_change_bps",
          "dxy_change_pct","fed_path_revision_bps",
          "etf_flow_tonnes","central_bank_net_tonnes",
          "global_pmi_surprise","global_gdp_revision_pct",
          "price_momentum_252d_pct"),
}


def _out(horizon: str,reason: str):
    return {
        "contract":CONTRACT,"horizon":horizon,
        "trading_sessions":HORIZONS[horizon],
        "status":"WAIT","reason":reason,"search_side":"WAIT",
        "implied_research_direction":"WAIT",
        "estimated_return_pct":None,"estimated_price":None,
        "feature_weight_pct":None,"group_weight_pct":None,
        "evidence_rows":0,"training_last_target_at":None,
        "research_only":True,"point_in_time_history_verified":False,
        "out_of_sample_validated":False,"calibrated_probability":None,
        "weights_are_causal_effects":False,
        "execution_authority":False,"entry_permission":False,
        "cbot_influence":False,"frozen_v1_influence":False,
    }


def _features(horizon, features):
    if horizon not in HORIZONS:
        raise ValueError("UNSUPPORTED_HORIZON")
    names=FEATURES[horizon] if features is None else tuple(features)
    if (not names or len(set(names))!=len(names)
        or any(x not in FEATURE_GROUP or x not in FEATURES[horizon] for x in names)):
        raise ValueError("UNRECOGNIZED_OR_DUPLICATE_FEATURE")
    return names


def _clean_data(data: pd.DataFrame, names):
    if not isinstance(data,pd.DataFrame):
        raise ValueError("DATAFRAME_REQUIRED")
    required={"gold_close","gold_close_received_at","vintage_verified"}
    for name in names:
        required.update((name,name+"_received_at"))
    if not required.issubset(data.columns):
        raise ValueError("MISSING_POINT_IN_TIME_FEATURES:"+",".join(sorted(required-set(data.columns))))
    if (not isinstance(data.index,pd.DatetimeIndex)
        or data.index.tz is None or data.index.has_duplicates
        or not data.index.is_monotonic_increasing):
        raise ValueError("TZ_AWARE_SORTED_UNIQUE_ASOF_REQUIRED")
    df=data.copy()
    df.index=df.index.tz_convert("UTC")
    df["gold_close"]=pd.to_numeric(df["gold_close"],errors="coerce")
    if (df["gold_close"].isna().any() or
        not np.isfinite(df["gold_close"]).all() or
        (df["gold_close"]<=0).any()):
        raise ValueError("INVALID_XAU_CLOSE")
    for f in names:
        df[f]=pd.to_numeric(df[f],errors="coerce")
        if not np.isfinite(df[f]).all():
            raise ValueError("INVALID_OR_UNRECORDED_FACTOR:"+f)
    if not (df["vintage_verified"]==True).all():
        raise ValueError("UNVERIFIED_DATA_VINTAGE")
    for name in ["gold_close",*names]:
        col=name+"_received_at"
        received=pd.to_datetime(df[col],utc=True,errors="coerce")
        if received.isna().any():
            raise ValueError("MISSING_RECEIPT_TIMESTAMP:"+name)
        if (received.array.asi8>df.index.asi8).any():
            raise ValueError("LOOKAHEAD_SOURCE_RECEIPT:"+name)
        if (received.array.asi8<0).any():
            raise ValueError("INVALID_SOURCE_RECEIPT:"+name)
    return df


def fit_asof(data: pd.DataFrame, *, horizon: str,
             feature_names=None, min_train_rows=None,
             ridge_penalty=30.0, min_edge_pct=0.05):
    """Fit using ONLY outcome windows completed BEFORE this decision.

    D1=1, W1=5, M1=21, Y1=252 distinct observed XAU sessions,
    not arbitrary calendar days. Enforce a further full-horizon
    embargo so heavily overlapping recent target windows do not
    leak evaluation-path information into the fit.
    """
    names=_features(horizon,feature_names)
    if (not isinstance(ridge_penalty,(int,float)) or ridge_penalty<=0
        or not isfinite(ridge_penalty) or
        not isinstance(min_edge_pct,(int,float)) or
        not 0<=min_edge_pct<10):
        raise ValueError("INVALID_FITTING_PARAMETERS")
    df=_clean_data(data,names)
    h=HORIZONS[horizon]
    req=TRAIN_MIN[horizon] if min_train_rows is None else min_train_rows
    if isinstance(req,bool) or not isinstance(req,int) or req<60:
        raise ValueError("MIN_TRAIN_TOO_LOW")
    result=_out(horizon,"INSUFFICIENT_CAUSAL_TRAINING_HISTORY")
    # Row j provides X at j; y target is close at j+h,
    # but fitting samples stop at j <= decision-2*h.
    last_train=len(df)-1-2*h
    if last_train+1<req:
        result["evidence_rows"]=max(0,last_train+1)
        return result
    x=df[list(names)].to_numpy(dtype=float)
    prices=df["gold_close"].to_numpy(dtype=float)
    y=np.log(prices[h:]/prices[:-h])
    train_x=x[:last_train+1]
    train_y=y[:last_train+1]
    center=train_x.mean(axis=0)
    scale=train_x.std(axis=0)
    scale=np.where(scale<1e-12,1.0,scale)
    z=np.clip((train_x-center)/scale,-4,4)
    current=np.clip((x[-1]-center)/scale,-4,4)
    # Centred ridge: the intercept is unpenalised.
    yy=train_y-train_y.mean()
    zz=z-z.mean(axis=0)
    gram=zz.T@zz + float(ridge_penalty)*np.eye(len(names))
    beta=np.linalg.solve(gram,zz.T@yy)
    intercept=float(train_y.mean()-z.mean(axis=0)@beta)
    pred_log=float(intercept+current@beta)
    forecast_return=(exp(float(np.clip(pred_log,-0.5,0.5)))-1)*100
    absolute=np.abs(beta)
    denom=float(absolute.sum())
    weights={name:round(float(100*absolute[i]/denom),4)
             if denom>1e-15 else 0.0 for i,name in enumerate(names)}
    gweights={group:round(sum(weights[n] for n in names
                                   if FEATURE_GROUP[n]==group),4)
              for group in GROUPS}
    contrib={name:round(float(beta[i]*current[i]*100),5)
             for i,name in enumerate(names)}
    result.update(
        status="RESEARCH_ESTIMATE",reason="UNVALIDATED_IN_SAMPLE_FIT",
        as_of=df.index[-1].isoformat(),
        latest_gold_close=round(float(prices[-1]),5),
        estimated_return_pct=round(forecast_return,5),
        estimated_price=round(float(prices[-1])*(1+forecast_return/100),5),
        implied_research_direction=("BUY" if forecast_return>0 else
                                    "SELL" if forecast_return<0 else "WAIT"),
        feature_weight_pct=weights,group_weight_pct=gweights,
        contributions_log_pct=contrib,
        evidence_rows=last_train+1,
        training_last_target_at=df.index[last_train+h].isoformat(),
        point_in_time_history_verified=True,
        admitted_features=list(names),
        missing_canonical_features=sorted(set(FEATURES[horizon])-set(names)),
        full_factor_universe=len(names)==len(FEATURES[horizon]),
        min_edge_pct=min_edge_pct,
        # WATCH is only a direction for *research*, never a trade bias.
        search_side=("RESEARCH_SEARCH_BUY" if forecast_return>min_edge_pct
                     else "RESEARCH_SEARCH_SELL" if forecast_return < -min_edge_pct
                     else "WAIT"),
        independent_holdout_accuracy_pct=None,
        relative_weight_interpretation="ABS_STANDARDIZED_RIDGE_COEFFICIENT_NONCAUSAL",
    )
    return result


def audit_walk_forward(data: pd.DataFrame, *, horizon: str,
                       first_test_at,feature_names=None,
                       min_train_rows=None,ridge_penalty=30.0,
                       min_edge_pct=0.05):
    """Non-overlap OOS 1/5/21/252-session outcome test, no refitting on future.

    Picks *actual* forecast endpoints only when the dataset contains
    the horizon's eventual close. The fitting subset ends at decision
    time, never includes later features or a later-vintage revision.
    """
    names=_features(horizon,feature_names)
    df=_clean_data(data,names)
    start=pd.Timestamp(first_test_at)
    if start.tzinfo is None:
        raise ValueError("TZ_AWARE_TEST_START_REQUIRED")
    start=start.tz_convert("UTC")
    h=HORIZONS[horizon]
    idx=int(df.index.searchsorted(start))
    if idx>=len(df)-h:
        raise ValueError("NO_FULL_OUT_OF_SAMPLE_OUTCOMES")
    rows=[]
    for j in range(idx,len(df)-h,h):
        report=fit_asof(df.iloc[:j+1],horizon=horizon,feature_names=names,
                        min_train_rows=min_train_rows,
                        ridge_penalty=ridge_penalty,min_edge_pct=min_edge_pct)
        if report["status"]!="RESEARCH_ESTIMATE":
            continue
        predicted=report["estimated_return_pct"]
        realised=100*float(df["gold_close"].iloc[j+h]/df["gold_close"].iloc[j]-1)
        side=report["search_side"]
        if side=="WAIT":
            continue
        rows.append({
            "at":df.index[j].isoformat(),"horizon_end":df.index[j+h].isoformat(),
            "side":"BUY" if side=="RESEARCH_SEARCH_BUY" else "SELL",
            "predicted_return_pct":predicted,"realised_return_pct":round(realised,6),
            "correct":(realised>0 if side=="RESEARCH_SEARCH_BUY" else realised<0),
        })
    total=len(rows)
    wins=sum(r["correct"] for r in rows)
    effective_min=MIN_OOS[horizon]
    return {
        "contract":"RIZAN_XAU_R7_WALK_FORWARD_AUDIT_V1",
        "horizon":horizon,"horizon_sessions":h,
        "status":"MEASURED_RESEARCH_ONLY" if total>=effective_min
                 else "INSUFFICIENT_EFFECTIVE_OOS_SAMPLES",
        "n_tested_nonoverlap":total,"wins":wins,
        "correct_pct":round(100*wins/total,2) if total else None,
        "min_effective_oos":effective_min,
        "buy_n":sum(r["side"]=="BUY" for r in rows),
        "sell_n":sum(r["side"]=="SELL" for r in rows),
        "test_started_at":start.isoformat(),
        "fully_out_of_sample_for_selected_parameters":False,
        "caveat":"No nested tuning or freeze provenance; observational evidence only",
        "model_calibrated_probability":None,
        "production_validated":False,
        "execution_authority":False,"cbot_influence":False,
        "events":rows,
    }


def audit_group_ablation(data: pd.DataFrame, *, horizon: str,
                         first_test_at,feature_names=None,
                         min_train_rows=None,ridge_penalty=30.0):
    """Out-of-sample loss delta by removing one factor *GROUP* and refitting.

    If drop raises OOS MSE, that group helped this evaluation cohort.
    A negative delta means the group hurt. These are observational,
    *not* causal importance or proof of stable future relationships.
    Comparison dates must match across models; never use separate
    groups with different test rows.
    """
    names=_features(horizon,feature_names)
    full=audit_walk_forward(
        data,horizon=horizon,first_test_at=first_test_at,
        feature_names=names,min_train_rows=min_train_rows,
        ridge_penalty=ridge_penalty,min_edge_pct=0.0)
    reference={x["at"]:x for x in full["events"]}
    out={
        "contract":"RIZAN_XAU_R7_OOS_GROUP_ABLATION_V1",
        "horizon":horizon,"status":full["status"],
        "groups":{},"reference_n":len(reference),
        "causal_importance_verified":False,
        "out_of_sample_tuning_freeze_verified":False,
        "entry_permission":False,"execution_authority":False,
    }
    for group in GROUPS:
        subset=tuple(x for x in names if FEATURE_GROUP[x]!=group)
        if len(subset)==len(names) or not subset:
            continue
        partial=audit_walk_forward(
            data,horizon=horizon,first_test_at=first_test_at,
            feature_names=subset,min_train_rows=min_train_rows,
            ridge_penalty=ridge_penalty,min_edge_pct=0.0)
        alternative={x["at"]:x for x in partial["events"]}
        shared=sorted(set(reference)&set(alternative))
        if len(shared)<MIN_OOS[horizon]:
            out["groups"][group]={
                "status":"INSUFFICIENT_PAIRED_OOS_SAMPLES","paired_n":len(shared),
                "loss_increase_when_removed":None}
            continue
        full_sq=sum(
            (reference[t]["predicted_return_pct"]-
             reference[t]["realised_return_pct"])**2 for t in shared)/len(shared)
        reduced_sq=sum(
            (alternative[t]["predicted_return_pct"]-
             reference[t]["realised_return_pct"])**2 for t in shared)/len(shared)
        out["groups"][group]={
            "status":"DESCRIPTIVE_OOS_LOSS_DIFFERENCE","paired_n":len(shared),
            "full_rmse_pct":round(sqrt(full_sq),5),
            "without_group_rmse_pct":round(sqrt(reduced_sq),5),
            "rmse_increase_when_removed_pct_points":
                round(sqrt(reduced_sq)-sqrt(full_sq),5),
            "positive_means_group_helped_this_holdout":True,
            "causal_effect":False,
        }
    return out
