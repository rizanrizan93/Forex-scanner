"""R7.1 nested (inner selection / outer evaluation) regime-weight research.

All outer folds are BEFORE 2025 and were historically exposed to other R7
research. They are DEVELOPMENT WALK-FORWARD DIAGNOSTICS, *never* a fresh,
untouched holdout. 2025-2026 are explicitly excluded from EVERY numerical
fit, normalization, model-selection decision, evaluation and calibration.

The forward untouched shadow can only begin on NEW observations captured
after the predeclared research freeze; no future data are fabricated.
"""
from __future__ import annotations
from math import exp, sqrt, isfinite
import numpy as np
import pandas as pd
from .fed_r71_regime_map import map_regimes,CONTRACT as REGIME_CONTRACT

CONTRACT="RIZAN_R71_NESTED_WALK_FORWARD_REGIME_RESEARCH_V1"
HORIZONS={"D1":1,"W1":5,"M1":21,"Y1":252}
MAX_DEV_YEAR=2024
QUARANTINED_YEARS=(2025,2026)
NEW_UNTOUCHED_START="2026-11-21T00:00:00+07:00"
GRID=tuple(
    (penalty,blend,edge)
    for penalty in (10.0,100.0,500.0)
    for blend in (0.0,0.5,0.9)
    for edge in (0.0,10.0,25.0)
)
MIN_TRAIN={"D1":300,"W1":350,"M1":450,"Y1":1500}
MIN_OUTER={"D1":30,"W1":8,"M1":3,"Y1":5}
PRICE_FEATURES=(
    "xau_range5_pct","xau_mom5_pct",
    "xau_mom21_pct","xau_rvol21_pct",
)
RETRO_MACRO_FEATURES=(
    "real10_delta_5_bps","nom2_delta_5_bps",
    "nom10_delta_5_bps","broad_usd_ret5_pct",
)
OFFICIAL_OBSERVATION_MACRO_FEATURES=(
    "tips10y_delta5_bps","ust2y_delta5_bps",
    "ust10y_delta5_bps","duka_dollaridx_5d_pct",
)
STATES=("BULLISH","BEARISH","LIQUIDITY_STRESS","NEUTRAL")
COST_USD_PER_OZ=0.4


def _valid_frame(frame, features):
    if not isinstance(frame,pd.DataFrame):
        raise ValueError("DATAFRAME_REQUIRED")
    if (not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None
        or frame.index.has_duplicates or
        not frame.index.is_monotonic_increasing):
        raise ValueError("TZ_AWARE_UNIQUE_SORTED_SESSIONS_REQUIRED")
    required={"open","high","low","close",*features}
    if not required.issubset(frame.columns):
        raise ValueError("MISSING_PRICE_OR_FEATURES:"+",".join(sorted(required-set(frame.columns))))
    # Keep 2025/2026 purely as excluded metadata; never read their
    # prices, regimes, factor values, return labels or future bars.
    excluded=int((frame.index.year>=2025).sum())
    d=frame.loc[frame.index.year<=MAX_DEV_YEAR].copy()
    d.index=d.index.tz_convert("UTC")
    for name in required:
        d[name]=pd.to_numeric(d[name],errors="coerce")
    if len(d)<500 or not np.isfinite(d[["open","high","low","close"]].to_numpy()).all():
        raise ValueError("INSUFFICIENT_OR_BAD_PRE_2025_PRICE_HISTORY")
    if (d[["open","high","low","close"]]<=0).any().any():
        raise ValueError("INVALID_GOLD_PRICE")
    d["regime"]=map_regimes(d[["open","high","low","close"]])
    return d,excluded


def _out(horizon,features,excluded):
    return {
        "contract":CONTRACT,"horizon":horizon,
        "sessions":HORIZONS[horizon],
        "status":"NO_QUALIFIED_NESTED_RESEARCH_FOLDS",
        "quality":"DEVELOPMENT_DIAGNOSTIC_ONLY",
        "factor_set":list(features),
        "uses_latest_vintage_macro_proxy":any(x in RETRO_MACRO_FEATURES for x in features),
        "uses_official_treasury_observation_and_broker_dollar_index_proxy":
            any(x in OFFICIAL_OBSERVATION_MACRO_FEATURES for x in features),
        "official_ICE_DXY_PIT_verified":False,
        "original_release_timestamp_pit_verified":False,
        "quarantined_2025_2026_rows_not_read":excluded,
        "historical_development_years_used":"2018-2024",
        "outer_test_years_allowlist":[2021,2022,2023,2024],
        "new_genuine_untouched_holdout_start_wib":NEW_UNTOUCHED_START,
        "new_untouched_holdout_available":False,
        "selection_parameters_per_fold":len(GRID),
        "selection_2025_or_2026_used":False,
        "oos_market_skill_claim":False,
        "regimes_are_actual_liquidations":False,
        "score_is_probability":False,
        "search_side":"WAIT",
        "execution_authority":False,"cbot_influence":False,
        "frozen_v1_influence":False,
        "folds":[],
    }


def _windows(d,h):
    n=len(d)
    i=np.arange(n)
    # A session outcome starts at next session's OPEN and ends after
    # h completed trading sessions. A hole >7 days kills that label.
    gap=(d.index.to_series().diff()>pd.Timedelta(days=7)).astype(int).to_numpy()
    cumulative=np.cumsum(gap)
    good=(i+h<n)
    j=np.minimum(i+h,n-1)
    good&=(cumulative[i]==cumulative[j])
    cols=d[["open","close"]].to_numpy(dtype=float)
    y=np.full(n,np.nan,dtype=float)
    dollars=np.full(n,np.nan,dtype=float)
    valid=np.flatnonzero(good)
    future_open=cols[valid+1,0]
    close_end=cols[valid+h,1]
    y[valid]=np.log(close_end/future_open)
    dollars[valid]=close_end-future_open
    return y,dollars


def _admitted(d, features, y):
    x=d[list(features)].to_numpy(dtype=float)
    state=d["regime"].to_numpy(dtype="object")
    return np.isfinite(x).all(axis=1)&np.isfinite(y)&np.isin(state,STATES)


def _take_train(d, admitted, h, prior_to_year):
    cutoff=int(d.index.searchsorted(pd.Timestamp(f"{prior_to_year}-01-01",tz="UTC")))
    # At test-year start, last admitted TRAIN outcome must end
    # at least h earlier, giving h-session embargo plus h target.
    ids=np.flatnonzero(admitted & (np.arange(len(d))+2*h<cutoff))
    return ids


def _take_test(d, admitted, h, year):
    ids=np.flatnonzero(admitted & (d.index.year==year))
    if len(ids)==0:
        return ids
    year_end=int(d.index.searchsorted(pd.Timestamp(f"{year+1}-01-01",tz="UTC")))
    ids=ids[ids+h<year_end]
    # Non-overlapping event windows. Chronological and deterministic.
    return ids[::h]


def _ridge(x,y,lam):
    n,m=x.shape
    if n<m+2:
        raise ValueError("INSUFFICIENT_RIDGE_ROWS")
    mu=x.mean(axis=0)
    sd=x.std(axis=0)
    sd=np.where(sd<1e-12,1,sd)
    z=np.clip((x-mu)/sd,-4.,4.)
    xm=z.mean(axis=0)
    ym=y.mean()
    centred=z-xm
    beta=np.linalg.solve(centred.T@centred+lam*np.eye(m),
                         centred.T@(y-ym))
    intercept=float(ym-xm@beta)
    return {"mu":mu,"sd":sd,"beta":beta,"intercept":intercept}


def _fit_regime(x,y,regimes,lam):
    global_fit=_ridge(x,y,lam)
    local={}
    for name in STATES:
        select=regimes==name
        # Prevent small regime samples from fitting incidental patterns.
        if int(select.sum())>=max(40,12*x.shape[1]):
            local[name]=_ridge(x[select],y[select],lam)
    return {"global":global_fit,"local":local}


def _predict_fit(fit,x):
    z=np.clip((x-fit["mu"])/fit["sd"],-4.,4.)
    return fit["intercept"]+z@fit["beta"]


def _predict(model,x,regimes,blend):
    global_pred=_predict_fit(model["global"],x)
    pred=global_pred.copy()
    if blend:
        for name,fit in model["local"].items():
            mask=regimes==name
            if mask.any():
                pred[mask]=(1-blend)*global_pred[mask]+blend*_predict_fit(fit,x[mask])
    return pred


def _measure(pred,y,dollars,opening,edge_bp):
    n=len(pred)
    if n==0:return None
    # Directional forecasts allowed only if return estimate exceeds
    # threshold; NO probability label or leverage instruction.
    sides=np.where(pred>edge_bp/10_000,1,
                   np.where(pred< -edge_bp/10_000,-1,0)).astype(np.int8)
    active=sides!=0
    buys=sides==1
    sells=sides==-1
    net=sides[active]*dollars[active]-COST_USD_PER_OZ
    win=net>0
    return {
        "all_n":n,"n":int(active.sum()),
        "buy_n":int(buys.sum()),"sell_n":int(sells.sum()),
        "coverage_pct":round(100*float(active.mean()),3),
        "accuracy_pct":round(100*float(win.mean()),3) if len(net) else None,
        "buy_accuracy_pct":round(100*float(
            (dollars[buys]-COST_USD_PER_OZ>0).mean()),3) if buys.any() else None,
        "sell_accuracy_pct":round(100*float(
            (-dollars[sells]-COST_USD_PER_OZ>0).mean()),3) if sells.any() else None,
        "mean_net_usd_oz":round(float(net.mean()),4) if len(net) else None,
        "all_rmse_log_return":round(float(np.sqrt(np.mean((pred-y)**2))),6),
        "baseline_always_buy_on_identical_dates_pct":round(
            100*float((dollars>COST_USD_PER_OZ).mean()),3),
        "events_after_holdout_freeze":False,
    }


def _one(d,features,year,h,params, y,dollars,admitted):
    train_idx=_take_train(d,admitted,h,year)
    val_idx=_take_test(d,admitted,h,year)
    if len(train_idx)<MIN_TRAIN[{v:k for k,v in HORIZONS.items()}[h]] or len(val_idx)==0:
        return None
    xx=d[list(features)].to_numpy(dtype=float)
    states=d["regime"].to_numpy(dtype="object")
    lam,blend,edge=params
    fitted=_fit_regime(xx[train_idx],y[train_idx],states[train_idx],lam)
    pred=_predict(fitted,xx[val_idx],states[val_idx],blend)
    result=_measure(pred,y[val_idx],dollars[val_idx],d.open.to_numpy()[val_idx+1],edge)
    result["val_idx"]=val_idx
    result["predictions"]=pred
    result["model"]=fitted
    result["train_n"]=len(train_idx)
    result["regime_counts"]={
        k:int((states[val_idx]==k).sum()) for k in STATES}
    return result


def nested_regime_walk_forward(frame,*,horizon,include_retrospective_macro=False,
                               include_official_observation_macro=False,
                               outer_years=(2021,2022,2023,2024)):
    if include_retrospective_macro and include_official_observation_macro:
        raise ValueError("TWO_MACRO_SOURCE_FAMILIES_CANNOT_SHARE_ONE_FIT")
    if horizon not in HORIZONS:
        raise ValueError("UNSUPPORTED_HORIZON")
    if any(y not in (2021,2022,2023,2024) for y in outer_years):
        raise ValueError("OUTER_FOLD_MUST_BE_PRE_2025_DEVELOPMENT")
    features=PRICE_FEATURES+(
        OFFICIAL_OBSERVATION_MACRO_FEATURES if include_official_observation_macro
        else RETRO_MACRO_FEATURES if include_retrospective_macro else ())
    d,excluded=_valid_frame(frame,features)
    output=_out(horizon,features,excluded)
    y,dollars=_windows(d,HORIZONS[horizon])
    admitted=_admitted(d,features,y)
    h=HORIZONS[horizon]
    if h==252:
        output["status"]="Y1_INDEPENDENT_FOLDS_INSUFFICIENT_WAIT"
        return output
    all_outer_n=0
    for year in outer_years:
        # Inner selection evaluates only PRIOR years; not a row from
        # this outer year is read while choosing hyperparameters.
        inner_years=[v for v in (year-2,year-1) if v>=2020]
        best=None
        for params in GRID:
            valid_inner=[]
            for inner in inner_years:
                report=_one(d,features,inner,h,params,y,dollars,admitted)
                if report is not None and report["n"]>=max(2,MIN_OUTER[horizon]//4):
                    valid_inner.append(report)
            if not valid_inner: continue
            # Objective uses return RMSE of all inner observations,
            # not a deceptive 80% hit-rate from 3-7 selected trades.
            weighted_mse=sum((r["all_rmse_log_return"]**2)*r["all_n"]
                             for r in valid_inner)/sum(r["all_n"] for r in valid_inner)
            cov=sum(r["n"] for r in valid_inner)/sum(r["all_n"] for r in valid_inner)
            # Mild abstention penalty; predeclared, no outer label use.
            score=weighted_mse*(1+0.10*(1-cov))
            rank=(score,-cov,params)
            if best is None or rank<best["rank"]:
                best={"params":params,"rank":rank,
                      "inner_years":[r["all_n"] for r in valid_inner]}
        if best is None:
            output["folds"].append({"year":year,"status":"NO_VALID_INNER_FOLD"})
            continue
        outer=_one(d,features,year,h,best["params"],y,dollars,admitted)
        if outer is None or outer["all_n"]<MIN_OUTER[horizon]:
            output["folds"].append({
                "year":year,"status":"INSUFFICIENT_NONOVERLAP_OUTER",
                "outer_n":outer["all_n"] if outer is not None else 0})
            continue
        lam,blend,edge=best["params"]
        weight={}
        model=outer["model"]
        abs_global=np.abs(model["global"]["beta"])
        tot=float(abs_global.sum())
        weight["GLOBAL"]={
            f:round(float(abs_global[j]/tot*100),3) if tot>1e-12 else 0.0
            for j,f in enumerate(features)}
        for state,fit in model["local"].items():
            # Regime-local ridge uses a DIFFERENT feature SD than
            # the global fit. Convert local beta to GLOBAL-standard
            # deviation units before comparing or displaying weights.
            comparable_local=fit["beta"]*model["global"]["sd"]/fit["sd"]
            b=(1-blend)*model["global"]["beta"]+blend*comparable_local
            tot=float(np.abs(b).sum())
            weight[state]={
                f:round(float(100*abs(b[j])/tot),3) if tot>1e-12 else 0.0
                for j,f in enumerate(features)}
        fold={k:v for k,v in outer.items() if k not in (
            "val_idx","predictions","model")}
        fold.update({
            "year":year,"status":"NESTED_DEVELOPMENT_FOLD",
            "inner_search_folds_prior_to_outer":inner_years,
            "selected_ridge_penalty":lam,
            "selected_regime_blend":blend,
            "selected_min_edge_bp":edge,
            "train_last_target_before_outer_year":True,
            "regime_factor_weight_pct":weight,
            "outer_2025_2026_touched":False,
        })
        output["folds"].append(fold)
        all_outer_n+=outer["all_n"]
    output["eligible_outer_total"]=all_outer_n
    output["status"]=("NESTED_DEVELOPMENT_EVIDENCE_NOT_INDEPENDENT" if
                       all_outer_n>=MIN_OUTER[horizon] else
                       "INSUFFICIENT_NESTED_DEVELOPMENT_EVIDENCE")
    output["price_history_2023_repair_provenance_verified"]=False
    output["next_action"]="FREEZE_MODEL_THEN_FORWARD_SHADOW_FROM_NEW_SOURCE_CAPTURES"
    return output
