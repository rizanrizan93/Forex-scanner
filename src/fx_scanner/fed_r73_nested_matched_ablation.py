"""R7.3 nested, pairwise DATE-MATCHED Fed/COT/VIX factor ablation.

2018-2024 development ONLY. R7 and R7.1 previously inspected those
years; the experiment is NOT a new untouched backtest. Already viewed
2025/2026 held-out results are NEVER loaded for an outer fold or
used in any feature/parameter selection.
- Inner fold selects ridge lambda entirely in earlier years.
- Purged h-step training label embargo, disjoint outer h-step events.
- Compare identical outer decision dates across ALL model families,
  not cherry-picked subsets.
- No direct FOMC rate SURPRISE or CME FedWatch probabilities.
- No native FP Markets bid/ask, intraday order book, forced liquidation.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .fed_r71_regime_map import map_regimes
from .fed_r71_nested_regime import (
    _ridge,_predict_fit,_fit_regime,_predict,
    _windows,_take_train,_take_test,HORIZONS,STATES)
from .fed_r72_frozen_candidate import PARAMS as R72_FROZEN_PARAMS

CONTRACT="RIZAN_R73_NESTED_PAIRED_FACTOR_ABLATION_DEVELOPMENT_V1"
PRICE=("xau_range5_pct","xau_mom5_pct",
       "xau_mom21_pct","xau_rvol21_pct")
FED=("fed_target_change_14d_bps","fed_path_spread_proxy_bp",
     "fed_path_repricing_proxy_5d_bps")
YIELD_USD=("tips10y_delta5_bps","ust2y_delta5_bps",
           "duka_dollaridx_5d_pct")
LIQUIDITY=("cot_gold_mmanaged_net_oi_pct",
           "cot_gold_mmanaged_net_week_change_pct",
           "cot_gold_open_interest_week_pct",
           "vix_level_lagged","vix_5obs_change_pct")
MODELS={
    "R72_METHOD_PRICE_ONLY":PRICE,
    "R73_PRICE_FED_POLICY_AND_PATH_PROXY":PRICE+FED,
    "R73_PRICE_FED_TREASURY_BROKER_USD":PRICE+FED+YIELD_USD,
    "R73_PRICE_FED_COT_VIX":PRICE+FED+LIQUIDITY,
    "R73_FULL_GLOBAL":PRICE+FED+YIELD_USD+LIQUIDITY,
    "R73_FULL_REGIME_BLEND_HALF":PRICE+FED+YIELD_USD+LIQUIDITY,
}
ALL_FEATURES=tuple(dict.fromkeys(z for cols in MODELS.values() for z in cols))
LAMBDAS=(100.0,500.0,1500.0)
INNER_YEARS=(2021,2022,2023)
OUTER_YEARS=(2022,2023,2024)
SPREAD_USD_OZ=.40
MIN_TRAIN=350


def _panel_validate(panel):
    if not isinstance(panel,pd.DataFrame):
        raise ValueError("R73_PRICE_FACTOR_PANEL_REQUIRED")
    if (not isinstance(panel.index,pd.DatetimeIndex) or
        panel.index.tz is None or panel.index.has_duplicates or
        not panel.index.is_monotonic_increasing):
        raise ValueError("R73_TZ_SORTED_UNIQUE_DAILY_INDEX_REQUIRED")
    d=panel.loc[panel.index.year<=2024].copy()
    required={"open","high","low","close",*ALL_FEATURES}
    if not required.issubset(d.columns):
        raise ValueError("MISSING_R73_REAL_FACTOR_SOURCE")
    for col in required:
        d[col]=pd.to_numeric(d[col],errors="coerce")
    if len(d)<1400 or not (d.index.min().year<=2018 and
                         d.index.max().year==2024):
        raise ValueError("R73_2018_24_HISTORY_REQUIRED")
    if (d[["open","high","low","close"]].isna().any().any() or
        (d[["open","high","low","close"]]<=0).any().any()):
        raise ValueError("R73_BAD_MARKET_SOURCE")
    d["regime"]=map_regimes(d[["open","high","low","close"]])
    return d


def _fit_predict(features,model_label,train_ix,test_ix,
                 all_x,y,regimes,lam):
    columns=[ALL_FEATURES.index(z) for z in features]
    xx=all_x[:,columns]
    local_mode=(model_label=="R73_FULL_REGIME_BLEND_HALF")
    if local_mode:
        fitted=_fit_regime(xx[train_ix],y[train_ix],regimes[train_ix],lam)
        pred=_predict(fitted,xx[test_ix],regimes[test_ix],.5)
        beta=fitted["global"]["beta"]
        local_count=len(fitted["local"])
    else:
        fitted=_ridge(xx[train_ix],y[train_ix],lam)
        pred=_predict_fit(fitted,xx[test_ix])
        beta=fitted["beta"]
        local_count=0
    return pred,beta,local_count


def _stats(pred,y,move,regimes):
    side=np.where(pred>0,1,np.where(pred<0,-1,0))
    active=side!=0
    if len(pred)==0:raise ValueError("EMPTY_PREDICTIONS")
    net=side[active]*move[active]-SPREAD_USD_OZ
    wins=(net>0)
    by_regime={}
    for state in STATES:
        pick=(regimes==state)&active
        n=int(pick.sum())
        w=int(((side[pick]*move[pick]-SPREAD_USD_OZ)>0).sum()) if n else 0
        by_regime[state]={"n":n,"correct":w}
    return {
        "n":len(pred),
        "active_n":int(active.sum()),
        "buy_n":int((side>0).sum()),
        "sell_n":int((side<0).sum()),
        "correct":int(wins.sum()),
        "accuracy_pct":round(float(100*wins.mean()),3) if len(wins) else None,
        "mean_net_move_usd_oz":round(float(net.mean()),5) if len(net) else None,
        "rmse_log_return":float(np.sqrt(np.mean((pred-y)**2))),
        "by_regime":by_regime,
    }


def _inner_select(d,all_x,y,regimes,admitted,features,name,year,h):
    inner_years=[v for v in INNER_YEARS if v<year and v>=year-2]
    best=None
    for lam in LAMBDAS:
        errors=[]
        obs=0
        for v in inner_years:
            train=_take_train(d,admitted,h,v)
            test=_take_test(d,admitted,h,v)
            if len(train)<MIN_TRAIN or len(test)<3:
                continue
            pred,_,_=_fit_predict(features,name,train,test,
                                  all_x,y,regimes,lam)
            errors.append(np.square(pred-y[test]).sum())
            obs+=len(test)
        if obs==0:continue
        loss=float(sum(errors)/obs)
        rank=(loss,lam)
        if best is None or rank<best["rank"]:
            best={"lambda":lam,"rank":rank,
                  "inner_years":inner_years,
                  "inner_nonoverlap_n":obs}
    return best


def run_nested_matched_ablation(panel,*,horizon,
                               outer_years=OUTER_YEARS):
    if horizon not in HORIZONS:
        raise ValueError("R73_UNKNOWN_HORIZON")
    if any(z not in OUTER_YEARS for z in outer_years):
        raise ValueError("R73_OUTER_YEARS_MUST_BE_PRE_2025")
    d=_panel_validate(panel)
    h=HORIZONS[horizon]
    result={
        "contract":CONTRACT,"horizon":horizon,
        "status":"WAIT_INSUFFICIENT_PAIRWISE_DEVELOPMENT_DATA",
        "outer_years":list(outer_years),
        "used_2025_2026_market_features_or_labels":False,
        "score_is_fresh_untouched_holdout":False,
        "original_fomc_expectations_or_surprises_used":False,
        "futures_FedWatch_CME_used":False,
        "fomc_statement_dot_plot_or_powell_NLP_used":False,
        "cot_original_release_times_verified":False,
        "intraday_Treasury_publication_times_verified":False,
        "model_frozen_for_later_shadow":False,
        "execution_authority":False,
        "production_promotion_approved":False,
        "frozen_r72_parameters_used_as_2022_24_trained_forecast":False,
        "benchmark_is_R72_method_refit_without_future_data":True,
        "date_matched_comparison":True,
        "candidate_count":len(MODELS),
        "inner_lambda_grid":list(LAMBDAS),
        "per_year":[],
    }
    if h>=252:
        result["status"]="Y1_NOT_ENOUGH_INDEPENDENT_CYCLES"
        return result
    y,move=_windows(d,h)
    x=d[list(ALL_FEATURES)].to_numpy(dtype=float)
    regimes=d.regime.to_numpy(dtype=object)
    admitted=np.isfinite(x).all(axis=1)&np.isfinite(y)&(
        np.isin(regimes,STATES))
    model_accum={name:[] for name in MODELS}
    all_results=[]
    for year in outer_years:
        eval_idx=_take_test(d,admitted,h,year)
        if len(eval_idx)<({"D1":40,"W1":8,"M1":3}[horizon]):
            result["per_year"].append({
                "year":year,"status":"WAIT_FEW_ADMITTED_MATCHED_DATES",
                "matched_n":len(eval_idx)})
            continue
        year_rec={
            "year":year,
            "status":"NESTED_PRE_2025_DEVELOPMENT_FOLD",
            "matched_n":len(eval_idx),
            "first_eval_date":d.index[eval_idx[0]].isoformat(),
            "last_eval_date":d.index[eval_idx[-1]].isoformat(),
            "benchmark_always_buy_same_dates_pct":round(float(
                100*(move[eval_idx]>SPREAD_USD_OZ).mean()),3),
            "benchmark_momentum5_same_dates_pct":round(float(
                100*(((np.where(d.xau_mom5_pct.to_numpy()[eval_idx]>=0,1,-1)
                        *move[eval_idx]-SPREAD_USD_OZ)>0).mean()),3),
            "regime_counts":{
                z:int((regimes[eval_idx]==z).sum()) for z in STATES},
            "family":{},
        }
        fitted=[]
        for name,features in MODELS.items():
            selection=_inner_select(d,x,y,regimes,admitted,
                                    features,name,year,h)
            if selection is None:
                year_rec["status"]="WAIT_NO_PRIOR_INNER_FOLD"
                break
            train=_take_train(d,admitted,h,year)
            if len(train)<MIN_TRAIN:
                year_rec["status"]="WAIT_TOO_FEW_TRAIN_ROWS"
                break
            pred,beta,nlocal=_fit_predict(
                features,name,train,eval_idx,x,y,regimes,
                selection["lambda"])
            measured=_stats(pred,y[eval_idx],move[eval_idx],
                            regimes[eval_idx])
            if not np.isfinite(measured["rmse_log_return"]):
                raise ValueError("R73_MODEL_NONFINITE_LOSS")
            measured.update({
                "chosen_lambda_on_prior_inner_folds":selection["lambda"],
                "inner_years_before_outer_only":selection["inner_years"],
                "inner_nonoverlap_n":selection["inner_nonoverlap_n"],
                "train_rows":len(train),
                "local_regimes_with_fit":nlocal,
                "features":list(features),
                "beta_signed_std":[round(float(z),8) for z in beta],
                "no_trade_order":True,
            })
            fitted.append((name,measured))
        if len(fitted)!=len(MODELS):
            result["per_year"].append(year_rec)
            continue
        for name,measured in fitted:
            year_rec["family"][name]=measured
            model_accum[name].append(measured)
        base=year_rec["family"]["R72_METHOD_PRICE_ONLY"]
        for name,measured in year_rec["family"].items():
            measured["paired_rmse_change_vs_price_baseline"]=round(
                measured["rmse_log_return"]-base["rmse_log_return"],8)
            measured["paired_accuracy_pp_change_vs_price_baseline"]=round(
                measured["accuracy_pct"]-base["accuracy_pct"],3)
        all_results.append(year_rec)
        result["per_year"].append(year_rec)
    summary={}
    for name,folds in model_accum.items():
        n=sum(f["active_n"] for f in folds)
        correct=sum(f["correct"] for f in folds)
        buy=sum(f["buy_n"] for f in folds)
        sell=sum(f["sell_n"] for f in folds)
        weighted_mse=sum(f["n"]*f["rmse_log_return"]**2 for f in folds)
        total=sum(f["n"] for f in folds)
        summary[name]={
            "matched_outer_fold_count":len(folds),
            "matched_evaluation_n":total,
            "directional_n":n,
            "buy_n":buy,"sell_n":sell,"correct_n":correct,
            "direction_accuracy_pct":round(100*correct/n,3) if n else None,
            "pooled_oos_development_rmse_log_return":
                float(np.sqrt(weighted_mse/total)) if total else None,
            "min_bidirectional_samples_satisfied":
                buy>=20 and sell>=20,
            "fully_untouched_external_future":False,
        }
    base=summary["R72_METHOD_PRICE_ONLY"]
    for name,row in summary.items():
        if row["matched_evaluation_n"]!=base["matched_evaluation_n"]:
            raise RuntimeError("R73_MODEL_DATE_MATCHING_BROKEN")
        if row["pooled_oos_development_rmse_log_return"] is not None and (
            base["pooled_oos_development_rmse_log_return"] is not None):
            row["paired_rmse_delta_vs_r72_method"]=round(
                row["pooled_oos_development_rmse_log_return"]-
                base["pooled_oos_development_rmse_log_return"],8)
        else:
            row["paired_rmse_delta_vs_r72_method"]=None
    result["status"]=(
        "NESTED_PAIRED_DEVELOPMENT_COMPLETED_NO_PIT_ALPHA_CLAIM"
        if all_results else "WAIT_INSUFFICIENT_PAIRED_DEVELOPMENT")
    result["summary"]=summary
    result["evaluated_decision_dates_total"]=sum(
        q["matched_n"] for q in all_results)
    result["comparison_paired_n_same_for_every_model"]=True
    result["new_future_forward_shadow_results"]=0
    result["cme_fomc_surprise_unavailable_dont_invent"]=True
    result["training_note"]="Fixed_R72_lambda_method_refit_asof_year; NEVER use frozen_2024_R72_coefficients_in_2022_test"
    return result
