"""R7 empirical >1M weight/threshold combinations PER eligible horizon.

This is a RETROSPECTIVE latest-vintage FRED proxy study, not real R7 PIT
history, not all macro factors, not a robust 80% strategy. Sign-limited
integer coefficients explore a huge grid on 2023-2024 *development*
data; 2025-2026 remains separate and evaluated once for the top chosen
candidate. The >1M trials dramatically raise selection-overfit risk.

A prospective production forecaster would require original observed
vintages, full order flow/Fed/ETF data, and later forward shadow.
"""
from __future__ import annotations
from math import sqrt
import numpy as np
import pandas as pd

CONTRACT="RIZAN_R7_MILLION_GRID_LATEST_VINTAGE_DIAGNOSTIC_V1"
FEATURES=(
    "real10_delta_5_bps","nom2_delta_5_bps",
    "nom10_delta_5_bps","broad_usd_ret5_pct",
    "xau_range5_pct","xau_mom5_pct",
    "xau_mom21_pct","xau_rvol21_pct",
)
HORIZONS={"D1":1,"W1":5,"M1":21,"Y1":252}
WEIGHT_LEVELS=np.array([-2.,-1.,1.,2.],dtype=np.float64)
THRESHOLDS=np.round(np.arange(16)*0.05,5)
GRID_PER_HORIZON=4**len(FEATURES)*len(THRESHOLDS)
SPREAD_USD_OZ=0.40


def _stats(signs,moves, *, spread=SPREAD_USD_OZ):
    signs=np.asarray(signs,dtype=np.int8)
    moves=np.asarray(moves,dtype=float)
    if len(signs)!=len(moves):
        raise ValueError("ALIGNMENT_ERROR")
    picks=signs!=0
    pnls=signs[picks]*moves[picks]-spread
    if len(pnls)==0:
        return {"n":0,"accuracy_pct":None,
                "mean_net_usd_oz":None,"buy_n":0,"sell_n":0}
    n=len(pnls)
    return {
        "n":n,"accuracy_pct":round(100*float((pnls>0).mean()),3),
        "mean_net_usd_oz":round(float(pnls.mean()),5),
        "buy_n":int((signs==1).sum()),"sell_n":int((signs==-1).sum()),
        "buy_accuracy_pct":(round(100*float((pnls[signs[picks]==1]>0).mean()),3)
                            if (signs==1).any() else None),
        "sell_accuracy_pct":(round(100*float((pnls[signs[picks]==-1]>0).mean()),3)
                             if (signs==-1).any() else None),
    }


def _weights_from_ids(ids):
    ids=np.asarray(ids,dtype=np.uint32)
    digits=((ids[:,None]>>(2*np.arange(len(FEATURES),
                                      dtype=np.uint32)))&3).astype(np.int64)
    weights=WEIGHT_LEVELS[digits]
    return weights/np.abs(weights).sum(axis=1,keepdims=True)


def _segment(df,h,start,end):
    idx=np.flatnonzero((df.index>=pd.Timestamp(start,tz="UTC"))&
                       (df.index<pd.Timestamp(end,tz="UTC")))
    idx=idx[idx+h<len(df)]
    idx=idx[df.index[idx+h]<pd.Timestamp(end,tz="UTC")]
    # Exclude labels that jump over multi-session collection gaps.
    gap=(df.index.to_series().diff()>pd.Timedelta(days=5)).cumsum().to_numpy()
    idx=idx[gap[idx]==gap[idx+h]]
    # Disjoint forward horizon outcomes, not every overlapping day.
    return idx[::h]


def _validate(panel):
    if not isinstance(panel,pd.DataFrame):
        raise ValueError("PANEL_DATAFRAME_REQUIRED")
    if not isinstance(panel.index,pd.DatetimeIndex) or panel.index.tz is None:
        raise ValueError("UTC_AWARE_DAILY_INDEX_REQUIRED")
    if panel.index.has_duplicates or not panel.index.is_monotonic_increasing:
        raise ValueError("UNSORTED_OR_DUPLICATE_INDEX")
    required={"open","close",*FEATURES}
    if not required.issubset(panel.columns):
        raise ValueError("MISSING_MACRO_PRICE_FACTOR_COLUMNS")
    if len(panel)<500:
        raise ValueError("INSUFFICIENT_HISTORICAL_GOLD_DAYS")
    d=panel[list(required)].copy()
    d.index=d.index.tz_convert("UTC")
    for col in required:
        d[col]=pd.to_numeric(d[col],errors="coerce")
    d=d.replace([np.inf,-np.inf],np.nan).dropna()
    if (d[["open","close"]]<=0).any().any() or len(d)<500:
        raise ValueError("INVALID_DAILY_OHLC_OR_FACTOR_COVERAGE")
    if (d.index.year.min()>2019 or d.index.year.max()<2025):
        raise ValueError("INSUFFICIENT_TRAIN_AND_UNTOUCHED_HOLDOUT")
    return d


def search_one_horizon(panel, *, horizon, batch_weights=256,
                       max_weight_vectors=None):
    """Enumerate all 65,536 signed-weight vectors x 16 thresholds.

    Return one pre-holdout-selected configuration. Holdout is used
    only AFTER selecting its ID using the two development years.
    """
    if horizon not in HORIZONS:
        raise ValueError("UNKNOWN_HORIZON")
    d=_validate(panel)
    h=HORIZONS[horizon]
    train=d[(d.index>="2019-01-01")&(d.index<"2023-01-01")]
    dev_idx=_segment(d,h,"2023-01-01","2025-01-01")
    test_idx=_segment(d,h,"2025-01-01","2027-01-01")
    out={
        "contract":CONTRACT,"horizon":horizon,"trading_sessions":h,
        "status":"WAIT_INSUFFICIENT_NONOVERLAPPING_YEARLY_OBSERVATIONS",
        "trial_count_evaluated":0,"total_available_grid":GRID_PER_HORIZON,
        "candidate_selected_on":"2023-2024_ONLY",
        "holdout":"2025-2026_UNTOUCHED_DURING_SELECTION",
        "train":"2019-2022_FEATURE_NORMALIZATION",
        "macro_provenance":"RETROSPECTIVE_IN_REPO_FRED_LATEST_VINTAGE_LAG_ASSUMPTION_NOT_PIT",
        "full_r7_factor_universe":False,
        "actual_original_publication_timestamps_verified":False,
        "historical_comex_cot_etf_fed_surprise_included":False,
        "used_dxy":False,"used_trade_weighted_broad_usd_proxy":True,
        "broker_execution_parity":False,
        "production_alpha_validated":False,"execution_authority":False,
        "minimum_holdout_evidence_met":False,
        "n_train":len(train),"n_development_nonoverlap":len(dev_idx),
        "n_holdout_nonoverlap":len(test_idx),
    }
    req={"D1":180,"W1":36,"M1":8,"Y1":6}[horizon]
    if len(train)<600 or len(dev_idx)<req or len(test_idx)<req//2:
        return out
    mu=train[list(FEATURES)].mean().to_numpy(dtype=float)
    sd=train[list(FEATURES)].std(ddof=0).to_numpy(dtype=float)
    sd=np.where(sd<1e-12,1.0,sd)
    allfeatures=np.clip(
        (d[list(FEATURES)].to_numpy(dtype=float)-mu)/sd,-4,4)
    xdev=allfeatures[dev_idx]
    if not np.isfinite(xdev).all():
        return out
    closes=d.close.to_numpy(dtype=float)
    opens=d.open.to_numpy(dtype=float)
    # NEXT available session open -> end of h-th subsequent session.
    moves_dev=closes[dev_idx+h]-opens[dev_idx+1]
    yrdev=d.index.year.to_numpy()[dev_idx]
    levels=len(WEIGHT_LEVELS)**len(FEATURES)
    if max_weight_vectors is not None:
        if not isinstance(max_weight_vectors,int) or max_weight_vectors<1:
            raise ValueError("INVALID_GRID_LIMIT")
        levels=min(levels,max_weight_vectors)
    if not isinstance(batch_weights,int) or not 32<=batch_weights<=2048:
        raise ValueError("INVALID_BATCH")
    min_side={"D1":25,"W1":6,"M1":2,"Y1":2}[horizon]
    min_coverage={"D1":.3,"W1":.3,"M1":.4,"Y1":.5}[horizon]
    winner=None
    eligible=0
    tested=0
    # Candidate search performed only on DEV. No access to holdout
    # feature vectors or labels until winner is chosen.
    for start in range(0,levels,batch_weights):
        ids=np.arange(start,min(start+batch_weights,levels),dtype=np.uint32)
        w=_weights_from_ids(ids)
        scores=xdev@w.T
        b=scores.shape[1]
        tested+=b*len(THRESHOLDS)
        for threshold in THRESHOLDS:
            buys=scores>threshold
            sells=scores < -threshold
            sides=buys.astype(np.int8)-sells.astype(np.int8)
            nb=buys.sum(axis=0)
            ns=sells.sum(axis=0)
            n=nb+ns
            ok=(nb>=min_side)&(ns>=min_side)&(n>=min_coverage*len(dev_idx))
            if not ok.any():
                continue
            # Candidate must work on BOTH development years, otherwise
            # it is selection-only and too dependent on one gold regime.
            for yy in (2023,2024):
                ix=(yrdev==yy)
                ok &= ((buys[ix].sum(axis=0)+sells[ix].sum(axis=0))>=
                       max(2,int(min_coverage*ix.sum()*.5)))
            if not ok.any():
                continue
            true_buy=moves_dev[:,None]>SPREAD_USD_OZ
            true_sell=-moves_dev[:,None]>SPREAD_USD_OZ
            wins=np.where(buys,true_buy,np.where(sells,true_sell,False))
            wn=wins.sum(axis=0)
            buy_acc=(wins&buys).sum(axis=0)/np.maximum(nb,1)
            sell_acc=(wins&sells).sum(axis=0)/np.maximum(ns,1)
            balanced=(buy_acc+sell_acc)/2
            year_acc=[]
            for yy in (2023,2024):
                ix=yrdev==yy
                sn=(buys[ix]|sells[ix]).sum(axis=0)
                year_acc.append(wins[ix].sum(axis=0)/np.maximum(sn,1))
            worst_year=np.minimum(year_acc[0],year_acc[1])
            # Balanced BUY/SELL + worst-year robustness; validation
            # is a training/selection domain, never a performance claim.
            utility=.65*balanced+.35*worst_year
            utility=np.where(ok,utility,-1.)
            eligible+=int(ok.sum())
            j=int(np.argmax(utility))
            if utility[j]<0:
                continue
            rank=(float(utility[j]),float(balanced[j]),
                  float(worst_year[j]),int(n[j]),-int(ids[j]))
            if winner is None or rank>winner["rank"]:
                winner={
                    "id":int(ids[j]),"threshold":float(threshold),
                    "rank":rank,
                    "dev_n":int(n[j]),"dev_wins":int(wn[j]),
                    "dev_buy_n":int(nb[j]),"dev_sell_n":int(ns[j]),
                    "dev_buy_win_pct":round(float(100*buy_acc[j]),3),
                    "dev_sell_win_pct":round(float(100*sell_acc[j]),3),
                    "dev_worst_year_accuracy_pct":round(float(100*worst_year[j]),3),
                }
    out["trial_count_evaluated"]=tested
    out["admissible_trial_count"]=eligible
    if winner is None:
        out["status"]="NO_TWO_SIDED_ROBUST_DEVELOPMENT_CANDIDATE"
        return out
    weight=_weights_from_ids(np.array([winner["id"]]))[0]
    # HOLDOUT ACCESSED FIRST TIME HERE. No hyperparam re-selection.
    xtest=allfeatures[test_idx]
    moves_test=closes[test_idx+h]-opens[test_idx+1]
    if not np.isfinite(xtest).all():
        out["status"]="HOLDOUT_HAS_INVALID_FACTOR_DATA"
        return out
    signal=np.where(xtest@weight>winner["threshold"],1,
                    np.where(xtest@weight< -winner["threshold"],-1,0))
    devsignal=np.where(xdev@weight>winner["threshold"],1,
                       np.where(xdev@weight< -winner["threshold"],-1,0))
    oos=_stats(signal,moves_test)
    dev=_stats(devsignal,moves_dev)
    # Simpler baselines evaluated on the same nonoverlapping holdout
    # dates but without selection or tuned abstention.
    buyhold=_stats(np.ones(len(test_idx),dtype=np.int8),moves_test)
    momentumhold=_stats(
        np.where(xtest[:,5]>=0,1,-1).astype(np.int8),moves_test)
    groups={
        "REAL_RATES_AND_NOMINAL":float(np.abs(weight[:3]).sum()),
        "USD_BROAD_PROXY_NOT_DXY":float(abs(weight[3])),
        "PRICE_ONLY_VOLATILITY_MOMENTUM":float(np.abs(weight[4:]).sum()),
    }
    result_weight=dict(zip(FEATURES,[round(float(z),6) for z in weight]))
    group_pct={k:round(100*v,3) for k,v in groups.items()}
    coverage=oos["n"]/len(test_idx)
    out.update({
        "status":"RETROSPECTIVE_HOLDOUT_DIAGNOSTIC_NOT_PIT",
        "selected_weight_id":winner["id"],
        "selected_threshold":winner["threshold"],
        "selected_signed_weights":result_weight,
        "relative_abs_group_weights_pct":group_pct,
        "all_weight_magnitudes_sum_to_1":True,
        "selection_sample":{**dev,"worst_year_accuracy_pct":
                            winner["dev_worst_year_accuracy_pct"]},
        "untouched_holdout_once_selected":oos,
        "holdout_coverage_pct":round(100*coverage,3),
        "always_buy_holdout":buyhold,
        "momentum_5d_holdout":momentumhold,
        "minimum_holdout_evidence_met":(oos["n"]>=
            {"D1":80,"W1":18,"M1":7,"Y1":6}[horizon] and
            oos["buy_n"]>=3 and oos["sell_n"]>=3),
        "multiple_testing_warning":"ONE_MILLION_TRIAL_SEARCH_OVERFITTING_RISK",
        "model_selection_provenance":"DEV_2023_2024_ONLY_NO_HOLDOUT_OPTIMIZATION",
    })
    return out
