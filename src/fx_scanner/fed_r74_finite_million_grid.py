"""R7.4: FINITE, PRE-REGISTERED base-5 Fed/COT/XAU grid.

Exactly 390,624 nonzero 8-axis weights x 4 threshold choices x
2 predetermined regime policies x 3 horizons = 9,374,976
DISTINCT predeclared configurations, not an endless optimization loop.

This is a retrospective development research diagnostic using
pre-2025 nested folds that have been seen in earlier R7 research;
NOT fresh untouched validation and NOT evidence of live alpha.
"""
from __future__ import annotations
from math import comb,sqrt
import hashlib,json
import numpy as np
import pandas as pd
from .fed_r71_nested_regime import (
    HORIZONS,_ridge,_predict_fit,_windows,_take_train,_take_test,STATES)
from .fed_r71_regime_map import map_regimes
from .fed_r73_nested_matched_ablation import ALL_FEATURES,PRICE

CONTRACT="RIZAN_R74_FINITE_9374976_BASE5_NESTED_MACRO_RESEARCH_V1"
WEIGHT_VALUES=(-2,-1,0,1,2)
THRESHOLDS=(0.0,0.15,0.30,0.45)
POLICIES=("GLOBAL","REGIME_GATED")
HORIZON_LIST=("D1","W1","M1")
OUTER_YEARS=(2023,2024)
INNER_POOL=(2021,2022,2023)
FROZEN_DATA_END_YEAR=2024
COST_USD_OZ=.40
BATCH_SIZE=2048
GROUPS={
    "XAU_SHORT_MOMENTUM":("xau_mom5_pct",),
    "XAU_MEDIUM_TREND":("xau_mom21_pct",),
    "XAU_PRICE_RISK":("xau_rvol21_pct","xau_range5_pct"),
    "FED_TARGET_AND_PATH_PROXY":(
        "fed_target_change_14d_bps",
        "fed_path_spread_proxy_bp",
        "fed_path_repricing_proxy_5d_bps"),
    "TREASURY_REAL_NOMINAL":(
        "tips10y_delta5_bps","ust2y_delta5_bps"),
    "USD_BROKER_INDEX":("duka_dollaridx_5d_pct",),
    "CFTC_GOLD_POSITIONING":(
        "cot_gold_mmanaged_net_oi_pct",
        "cot_gold_mmanaged_net_week_change_pct",
        "cot_gold_open_interest_week_pct"),
    "VIX_RISK":("vix_level_lagged","vix_5obs_change_pct"),
}
AXES=tuple(GROUPS.keys())
if len(AXES)!=8 or set(z for v in GROUPS.values() for z in v)!=set(ALL_FEATURES):
    raise RuntimeError("R74_PREDECLARED_8_AXES_DO_NOT_MATCH_REAL_SOURCE_FEATURES")
POLICY_MULTIPLIERS={
    "BULLISH":(1.15,1.25,0.75,1.00,1.00,1.00,1.00,0.85),
    "BEARISH":(1.15,1.25,1.15,1.00,1.00,1.00,1.00,1.00),
    "LIQUIDITY_STRESS":(.60,.60,1.20,1.10,1.20,1.10,.75,1.40),
    "NEUTRAL":(.80,.80,1.00,1.15,1.15,1.00,1.00,1.10),
}
MIN_COUNTS={
    "D1":{"inner_total":140,"per_side":30,"per_fold":45,
          "per_fold_side":4,"outer_min":60},
    "W1":{"inner_total":26,"per_side":6,"per_fold":8,
          "per_fold_side":1,"outer_min":12},
    "M1":{"inner_total":10,"per_side":2,"per_fold":3,
          "per_fold_side":0,"outer_min":5},
}
# >=20 BUY and >=20 SELL on development outer before any promotion
MIN_NEW_FORWARD_PER_SIDE=20


def weights_full(values=WEIGHT_VALUES):
    values=tuple(values)
    if len(set(values))!=len(values) or 0 not in values:
        raise ValueError("WEIGHTS_REQUIRE_UNIQUE_VALUES_AND_ZERO")
    n=len(values)**8
    indices=np.arange(n,dtype=np.int64)
    weight_digits=np.empty((n,8),dtype=np.int8)
    for j in range(8):
        weight_digits[:,j]=(indices//len(values)**j)%len(values)
    v=np.asarray(values,dtype=np.int8)
    w=v[weight_digits]
    w=w[np.any(w!=0,axis=1)]
    return w


def configured_count(values=WEIGHT_VALUES,thresholds=THRESHOLDS,
                     policies=POLICIES,horizons=HORIZON_LIST):
    return (len(values)**len(AXES)-1)*len(thresholds)*len(policies)*len(horizons)


def _ready(d):
    if (not isinstance(d,pd.DataFrame) or
        not isinstance(d.index,pd.DatetimeIndex) or
        d.index.tz is None or d.index.has_duplicates or
        not d.index.is_monotonic_increasing):
        raise ValueError("R74_UNIQUE_SORTED_TZAWARE_DAILY_REQUIRED")
    # This slices out 2025+ BEFORE ever constructing eligible labels,
    # regime metrics, normalization or tuning.
    x=d.loc[d.index.year<=FROZEN_DATA_END_YEAR].copy()
    if len(x)<1200 or x.index.max().year!=2024:
        raise ValueError("R74_TRAIN_DEVELOPMENT_DATA_REQUIRED")
    necessary={"open","high","low","close",*ALL_FEATURES}
    if not necessary.issubset(x.columns):
        raise ValueError("R74_ALL_15_REAL_FEATURES_REQUIRED")
    for col in necessary:
        x[col]=pd.to_numeric(x[col],errors="coerce")
    if not np.isfinite(x[["open","high","low","close"]].to_numpy()).all():
        raise ValueError("R74_INVALID_OHLC")
    if (x[["open","high","low","close"]]<=0).any().any():
        raise ValueError("R74_NONPOSITIVE_PRICE")
    x["regime"]=map_regimes(x[["open","high","low","close"]])
    return x


def _axes_for_fold(d,feature_matrix,regimes,train_ix,test_ix):
    train=feature_matrix[train_ix].astype(np.float64)
    test=feature_matrix[test_ix].astype(np.float64)
    mu=train.mean(axis=0)
    sd=train.std(axis=0)
    sd[sd<1.e-10]=1.
    a=np.clip((train-mu)/sd,-4.,4.)
    b=np.clip((test-mu)/sd,-4.,4.)
    train_axes=[]
    test_axes=[]
    for name,columns in GROUPS.items():
        cols=[ALL_FEATURES.index(z) for z in columns]
        ga=a[:,cols].mean(axis=1)
        gb=b[:,cols].mean(axis=1)
        avg=float(ga.mean())
        scale=float(ga.std())
        scale=max(scale,1.e-8)
        train_axes.append(np.clip((ga-avg)/scale,-4.,4.))
        test_axes.append(np.clip((gb-avg)/scale,-4.,4.))
    axes=np.asarray(test_axes,dtype=np.float32).T
    if axes.shape!=(len(test_ix),8) or not np.isfinite(axes).all():
        raise ValueError("R74_INVALID_NORMALIZED_AXES")
    mul=np.asarray(
        [POLICY_MULTIPLIERS[z] for z in regimes[test_ix]],dtype=np.float32)
    if mul.shape!=axes.shape:raise ValueError("R74_INVALID_REGIME_MASK")
    return {
        "GLOBAL":np.ascontiguousarray(axes,dtype=np.float32),
        "REGIME_GATED":np.ascontiguousarray(axes*mul,dtype=np.float32),
    }


def _wilson_lower(correct,n,z=1.645):
    nn=np.maximum(n,1)
    p=correct/nn
    sq=np.sqrt(np.maximum(0,p*(1-p)/nn+z*z/(4*nn*nn)))
    val=(p+z*z/(2*nn)-z*sq)/(1+z*z/nn)
    return np.where(n>0,val,0)


def _wilson95(k,n):
    if n<=0:return None
    z=1.96
    p=k/n
    den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    span=z*sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round(100*(mid-span),3),round(100*(mid+span),3)]


def _exact_p(gain,loss):
    n=gain+loss
    if not n:return 1.
    return min(1.,2*sum(comb(n,j) for j in range(min(gain,loss)+1))/2**n)


def _fold_inputs(d,feature_matrix,regimes,valid,y,moves,h,year):
    train_idx=_take_train(d,valid,h,year)
    eval_idx=_take_test(d,valid,h,year)
    if len(train_idx)<350 or len(eval_idx)==0:
        return None
    axes=_axes_for_fold(d,feature_matrix,regimes,train_idx,eval_idx)
    return {
        "year":year,"train_idx":train_idx,"eval_idx":eval_idx,
        "axes":axes,"move":moves[eval_idx],
        "log_return":y[eval_idx],
        "regimes":regimes[eval_idx],
    }


def _search_batch(folds,W,l1,thresholds,policy,horizon):
    n_w=len(W)
    n_thr=len(thresholds)
    bn=np.zeros((n_thr,n_w),dtype=np.int32)
    sn=bn.copy();bc=bn.copy();sc=bn.copy()
    sum_net=np.zeros((n_thr,n_w),dtype=np.float64)
    min_fold_accuracy=np.ones((n_thr,n_w),dtype=np.float32)
    eligible=np.ones((n_thr,n_w),dtype=bool)
    c=MIN_COUNTS[horizon]
    for fold in folds:
        z=fold["axes"][policy]
        move=fold["move"].astype(np.float32)
        # Apply pre-registered weights only to validation-year features
        # trained on STRICTLY EARLIER years. Every score is batch-computed.
        scores=(z@W.T)/l1[None,:]
        bullish=(move>COST_USD_OZ)
        bearish=(move< -COST_USD_OZ)
        for i,t in enumerate(thresholds):
            buy=scores>t
            sell=scores< -t
            buy_n=buy.sum(axis=0,dtype=np.int32)
            sell_n=sell.sum(axis=0,dtype=np.int32)
            b_correct=(buy&bullish[:,None]).sum(axis=0,dtype=np.int32)
            s_correct=(sell&bearish[:,None]).sum(axis=0,dtype=np.int32)
            n=buy_n+sell_n
            eligibility=(
                (n>=c["per_fold"])&
                (buy_n>=c["per_fold_side"])&
                (sell_n>=c["per_fold_side"]))
            eligible[i]&=eligibility
            bn[i]+=buy_n;sn[i]+=sell_n
            bc[i]+=b_correct;sc[i]+=s_correct
            min_fold_accuracy[i]=np.minimum(min_fold_accuracy[i],
                (b_correct+s_correct)/np.maximum(n,1))
            # Gross spot DOLLAR move, minus assumed $0.40 per event.
            # Not real FP Markets bid/ask trade return.
            sum_net[i]+=(
                (move[:,None]*buy).sum(axis=0,dtype=np.float64)-
                (move[:,None]*sell).sum(axis=0,dtype=np.float64)-
                COST_USD_OZ*n)
    act=bn+sn
    lower_buy=_wilson_lower(bc,bn)
    lower_sell=_wilson_lower(sc,sn)
    score=(
        np.minimum(lower_buy,lower_sell)+
        .08*min_fold_accuracy+
        .03*act/sum(len(fold["eval_idx"]) for fold in folds))
    eligible &= (act>=c["inner_total"]) & (
        bn>=c["per_side"]) & (sn>=c["per_side"])
    eligible &= sum_net>0
    # To discourage candidates that only win one period while collapsing
    # in the other; this is a PREDECLARED, not learned, consistency gate.
    eligible &= min_fold_accuracy>=.35
    score=np.where(eligible,score,-np.inf)
    flat=int(np.argmax(score))
    i,j=np.unravel_index(flat,score.shape)
    if not np.isfinite(score[i,j]):
        return None
    weight=W[j].astype(int).tolist()
    return {
        "selection_objective":float(score[i,j]),
        "policy":policy,"threshold":float(thresholds[i]),
        "weights":weight,
        "inner_buy_n":int(bn[i,j]),"inner_sell_n":int(sn[i,j]),
        "inner_buy_correct":int(bc[i,j]),
        "inner_sell_correct":int(sc[i,j]),
        "inner_mean_net_move_usd_oz":round(float(sum_net[i,j]/act[i,j]),5),
        "inner_worst_fold_accuracy_pct":round(
            float(min_fold_accuracy[i,j])*100,3),
        "total_inner_selected":int(act[i,j]),
        "nonzero_axes":int(sum(x!=0 for x in weight)),
    }


def _stats(pred,move,regimes):
    side=np.asarray(pred,dtype=np.int8)
    buy=side>0;sell=side<0;active=side!=0
    signed=side[active]*move[active]-COST_USD_OZ
    correct=signed>0
    out={
        "matched_n":len(side),
        "active_n":int(active.sum()),
        "buy_n":int(buy.sum()),"sell_n":int(sell.sum()),
        "correct_n":int(correct.sum()),
        "direction_accuracy_pct":round(100*float(correct.mean()),3)
                                  if len(correct) else None,
        "wilson95_accuracy_pct":_wilson95(int(correct.sum()),len(correct)),
        "mean_signed_move_after_assumed_cost_usd_oz":
            round(float(signed.mean()),4) if len(signed) else None,
        "coverage_pct":round(100*float(active.mean()),3)
                       if len(side) else None,
        "per_regime":{
            state:{
                "n":int(((regimes==state)&active).sum()),
                "correct":int((
                    (side[(regimes==state)&active]*
                     move[(regimes==state)&active]-COST_USD_OZ)>0).sum()),
            } for state in STATES},
    }
    return out


def _evaluate_outer(fold,candidate,feature_matrix,y,moves,regimes):
    policy=candidate["policy"];threshold=candidate["threshold"]
    w=np.asarray(candidate["weights"],dtype=np.float32)
    l1=float(np.abs(w).sum())
    score=fold["axes"][policy]@w/l1
    pred=np.where(score>threshold,1,
                  np.where(score< -threshold,-1,0)).astype(np.int8)
    candidates={"R74_SELECTED":pred}
    # BASELINES: explicit FIXED ridge penalty, as-of-year fit only.
    # Never use 2024 frozen R7.2 coefficients to test years 2023-24.
    train=fold["train_idx"];test=fold["eval_idx"]
    for name,columns in (
        ("R72_PRICE_ONLY_FIXED_RIDGE_500",PRICE),
        ("R73_FULL_MACRO_FIXED_RIDGE_500",ALL_FEATURES),
    ):
        cols=[ALL_FEATURES.index(z) for z in columns]
        mod=_ridge(feature_matrix[train][:,cols],
                   y[train],500.)
        estimate=_predict_fit(mod,feature_matrix[test][:,cols])
        candidates[name]=np.where(estimate>0,1,np.where(estimate<0,-1,0))
    out={
        "outer_year":fold["year"],"first_evaluation_day_utc":(
            fold["eval_idx"][0].item()),
        "selection_prior_only":True,
        "source_latest_vintage_no_original_PIT":True,
        "regime_weighting_is_predeclared_heuristic":True,
        "source_trade_execution_verified":False,
        "model_results":{},
        "comparisons":{},
    }
    truth={}
    for name,side in candidates.items():
        out["model_results"][name]=_stats(side,fold["move"],
                                           fold["regimes"])
        truth[name]=np.where(
            side==0,False,
            side*fold["move"]-COST_USD_OZ>0)
    selected=pred!=0
    for name in ("R72_PRICE_ONLY_FIXED_RIDGE_500",
                 "R73_FULL_MACRO_FIXED_RIDGE_500"):
        # PRIMARY PAIRED CHECK: evaluate BOTH directional engines on
        # IDENTICAL R74-ACTIVE dates; do not misinterpret R74 WAIT
        # dates as losing trades against baseline FULL-coverage calls.
        both=selected
        candidate_correct=truth["R74_SELECTED"][both]
        baseline_correct=truth[name][both]
        gain=int((candidate_correct&~baseline_correct).sum())
        loss=int((~candidate_correct&baseline_correct).sum())
        baseline_conditional=_stats(
            candidates[name][both],fold["move"][both],
            fold["regimes"][both])
        missed_baseline_correct=int((truth[name]&~selected).sum())
        out["comparisons"][name]={
            "r74_active_paired_dates_n":int(selected.sum()),
            "both_models_evaluated_only_on_r74_active_dates":True,
            "r74_right_baseline_wrong_on_same_selected_dates":gain,
            "r74_wrong_baseline_right_on_same_selected_dates":loss,
            "baseline_on_identical_r74_active_dates":baseline_conditional,
            "exact_discordant_p_unadjusted":round(_exact_p(gain,loss),8),
            "r74_wait_opportunities":int((~selected).sum()),
            "baseline_correct_on_r74_wait_dates":missed_baseline_correct,
            "all_market_decision_dates":len(truth[name]),
            "full_coverage_baseline_accuracy_is_not_conditional":True,
            "p_value_corrected_for_prior_research_or_many_searches":False,
        }
    return out


def finite_nested_search(panel,*,horizon,
                         outer_years=OUTER_YEARS,
                         weight_values=WEIGHT_VALUES,
                         thresholds=THRESHOLDS,
                         policies=POLICIES,
                         batch_size=BATCH_SIZE):
    if horizon not in HORIZON_LIST:
        raise ValueError("R74_NO_Y1_OR_UNKNOWN_HORIZON")
    if any(yr not in OUTER_YEARS for yr in outer_years):
        raise ValueError("R74_OUTER_YEAR_CANNOT_USE_2025_2026")
    if not 1<=batch_size<=8192:
        raise ValueError("R74_BATCH_SIZE_CAP_REQUIRED")
    values=tuple(weight_values)
    ts=tuple(thresholds); pol=tuple(policies)
    if not ts or not pol or any(x not in POLICIES for x in pol):
        raise ValueError("R74_UNREGISTERED_SEARCH_SPACE")
    d=_ready(panel)
    feature_matrix=d[list(ALL_FEATURES)].to_numpy(dtype=np.float64)
    y,moves=_windows(d,HORIZONS[horizon])
    regime=d.regime.to_numpy(dtype=object)
    admitted=(np.isfinite(feature_matrix).all(axis=1)&np.isfinite(y)&
              np.isin(regime,STATES))
    W=weights_full(values)
    norm=np.abs(W.astype(np.float32)).sum(axis=1)
    unique_configs=len(W)*len(ts)*len(pol)
    result={
        "contract":CONTRACT,"horizon":horizon,
        "status":"WAIT_NO_STABLE_NESTED_CANDIDATE",
        "source_years":"2018-2024_ONLY",
        "all_2025_2026_rows_removed_before_any_model_fit_or_label":True,
        "previously_exposed_2023_24_outer_is_not_untouched_holdout":True,
        "no_original_FOMC_surprise_CME_or_ICE_DXY":True,
        "source_publication_lags_are_assumptions":True,
        "weight_values":list(values),"thresholds":list(ts),
        "regime_policies":list(pol),
        "raw_features_count":len(ALL_FEATURES),
        "composite_axes":{k:list(v) for k,v in GROUPS.items()},
        "unique_nonzero_weight_vectors":len(W),
        "unique_configs_each_horizon":unique_configs,
        "intended_total_full_design_all_three_horizons":
            configured_count(),
        "real_configs_evaluated_this_horizon_per_searched_outer":unique_configs,
        "search_objective":"min_buy_sell_Wilson_90pct_lower_plus_fold_consistency",
        "selection_excludes_outer_year_prices_and_outcomes":True,
        "cBot_trade_authority":False,"frozen_v1_influence":False,
        "r72_frozen_model_unchanged":True,
        "outer_development_folds":[],
        "source_latest_vintage_not_original_PIT":True,
    }
    total_actual_candidate_evaluations=0
    for outer_year in outer_years:
        inner_years=[z for z in INNER_POOL if z<outer_year]
        inner_folds=[]
        for year in inner_years:
            q=_fold_inputs(d,feature_matrix,regime,admitted,y,moves,
                           HORIZONS[horizon],year)
            if q is not None:
                inner_folds.append(q)
        outer=_fold_inputs(d,feature_matrix,regime,admitted,y,moves,
                           HORIZONS[horizon],outer_year)
        min_inner=2 if outer_year>=2023 else 1
        if (len(inner_folds)<min_inner or outer is None or
            len(outer["eval_idx"])<MIN_COUNTS[horizon]["outer_min"]):
            result["outer_development_folds"].append({
                "year":outer_year,
                "status":"WAIT_NO_QUALIFIED_INNER_OR_OUTER_PERIOD",
                "inner_qualified_years":[f["year"] for f in inner_folds],
                "outer_n":len(outer["eval_idx"]) if outer else 0,
                "searched_unique_configs":0})
            continue
        best=None
        for start in range(0,len(W),batch_size):
            chunk=W[start:start+batch_size].astype(np.float32)
            nrm=norm[start:start+batch_size]
            for policy in pol:
                candidate=_search_batch(inner_folds,chunk,nrm,ts,policy,horizon)
                if candidate:
                    candidate["base5_vector_index"]=start+int(
                        np.flatnonzero(np.all(chunk==candidate["weights"],
                                              axis=1))[0])
                    tie=(candidate["selection_objective"],
                         candidate["total_inner_selected"],
                         -candidate["nonzero_axes"],
                         -candidate["base5_vector_index"])
                    if best is None or tie>best["rank"]:
                        best={"rank":tie,"candidate":candidate}
        total_actual_candidate_evaluations+=unique_configs
        if best is None:
            result["outer_development_folds"].append({
                "year":outer_year,
                "status":"WAIT_NO_CANDIDATE_CLEARED_BOTH_SIDES_AND_COST_GATES",
                "inner_qualified_years":[f["year"] for f in inner_folds],
                "outer_n":len(outer["eval_idx"]),
                "searched_unique_configs":unique_configs})
            print("R74_OUTER_SEARCH "+json.dumps({
                "horizon":horizon,"outer_year":outer_year,
                "status":"WAIT_NO_CANDIDATE",
                "configs":unique_configs},sort_keys=True),flush=True)
            continue
        selected=best["candidate"]
        out=_evaluate_outer(outer,selected,feature_matrix,y,moves,regime)
        # Output index only as integer row position; day ISO is provided
        # by d.index mapping rather than it being an integer timestamp.
        out["first_evaluation_day_utc"]=d.index[outer["eval_idx"][0]].isoformat()
        out["last_evaluation_day_utc"]=d.index[outer["eval_idx"][-1]].isoformat()
        out.update({
            "status":"NESTED_DEVELOPMENT_ONLY_NO_FRESH_HOLDOUT",
            "inner_years":[f["year"] for f in inner_folds],
            "inner_evaluation_n":sum(len(f["eval_idx"]) for f in inner_folds),
            "outer_evaluation_n":len(outer["eval_idx"]),
            "selected_inner_candidate":selected,
            "searched_unique_configs":unique_configs,
            "model_is_ready_for_live_execution":False,
        })
        result["outer_development_folds"].append(out)
        print("R74_OUTER_SEARCH "+json.dumps({
            "horizon":horizon,"outer_year":outer_year,
            "inner_years":out["inner_years"],"configs":unique_configs,
            "selected":selected,
            "outer_r74":out["model_results"]["R74_SELECTED"],
            "outer_r72":out["model_results"]["R72_PRICE_ONLY_FIXED_RIDGE_500"],
            "paired":out["comparisons"]["R72_PRICE_ONLY_FIXED_RIDGE_500"],
            "new_holdout":False,
        },sort_keys=True),flush=True)
    result["total_fold_config_scoring_evaluations"]=total_actual_candidate_evaluations
    result["status"]="COMPLETE_DEVELOPMENT_NO_FRESH_HOLDOUT" if any(
        p.get("status")=="NESTED_DEVELOPMENT_ONLY_NO_FRESH_HOLDOUT"
        for p in result["outer_development_folds"]) else result["status"]
    result["input_dates_min_utc"]=d.index.min().isoformat()
    result["input_dates_max_utc"]=d.index.max().isoformat()
    result["input_gold_rows"]=len(d)
    result["valid_actual_macro_feature_and_outcome_rows"]=int(admitted.sum())
    result["production_promotion_status"]="REJECTED_UNTIL_FUTURE_SHADOW"
    return result
