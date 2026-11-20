"""R7.2: pre-registered D1 *price-only global ridge* research freeze.

Fixed in source BEFORE selecting any new future observations:
- ONE candidate: 1 trading session, ridge lambda=500, regime blend=0,
  0 bp abstention threshold, four as-of-closed XAU daily features.
- Train strictly on audited 2018-2024 gold daily history, repaired 2023
  as Dukascopy independently source-labelled.
- NEVER train or select on already-examined 2025-2026 observations.
- Prospective daily scenario is informational, NOT an executable
  broker trade, an order, or a calibrated probability.
- The underlying regularized model is a WEAK/UNPROVEN candidate;
  parameter choices are declared for reproducibility, not claimed best.

The immutable freeze is the Git SHA of this source plus canonical
parameter JSON stored in the branch before the first decision.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from .fed_r71_nested_regime import (
    _ridge,_predict_fit,_windows,_admitted,PRICE_FEATURES,
    HORIZONS,STATES)
from .fed_r71_regime_map import map_regimes
from .fed_r71_nested_real_runner import _verified_orig_source,_independent_repair

CONTRACT="RIZAN_R72_D1_PRICE_ONLY_GLOBAL_RIDGE_FREEZE_V1"
PARAMS={"horizon":"D1","horizon_trading_sessions":1,
        "factor_names":list(PRICE_FEATURES),
        "ridge_penalty":500.0,
        "regime_blend":0.0,
        "min_edge_bp":0.0,
        "train_years":"2018-2024_only",
        "target":"next_session_open_to_next_session_close",
        "daily_session_clock":"UTC_00:00_24:00",
        "price_vendor_policy":"HistData_2018-2022_2024;Dukascopy_2023",
        "hypothetical_cost_usd_per_oz":0.40,
        "search_only":True,
        "original_pit_macro_required":False,
        "macro_or_ICE_DXY_used":False,
        "cBot_execution_authority":False,
        "frozen_v1_modification":False}
FORBIDDEN_TRAIN_YEARS={2025,2026}


def price_features(d:pd.DataFrame):
    """Exact retrospective canonical price feature transform."""
    if not isinstance(d.index,pd.DatetimeIndex) or d.index.tz is None:
        raise ValueError("TIMEZONE_AWARE_PRICE_HISTORY_REQUIRED")
    if d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError("UNSORTED_OR_DUPLICATE_PRICE")
    x=d.copy()
    close=x.close
    x["xau_range5_pct"]=100*((x.high-x.low)/close).rolling(
        5,min_periods=5).mean()
    x["xau_mom5_pct"]=100*(close/close.shift(5)-1)
    x["xau_mom21_pct"]=100*(close/close.shift(21)-1)
    x["xau_rvol21_pct"]=100*close.pct_change().rolling(
        21,min_periods=21).std()
    return x


def _canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),
                      allow_nan=False).encode("utf-8")


def _hash(obj):
    return hashlib.sha256(_canon(obj)).hexdigest()


def train_freeze(*,historical_root,repaired_root):
    raw,original=_verified_orig_source(historical_root)
    fixed,recovery=_independent_repair(repaired_root)
    if set(raw.index.year)!={2018,2019,2020,2021,2022,2023,2024}:
        raise ValueError("EXACT_PRE_2025_YEARS_REQUIRED")
    if len(fixed)!=259 or len(raw[raw.index.year==2023])!=164:
        raise ValueError("AUDITED_REPAIRED_SOURCE_CHANGED")
    joined=pd.concat([raw[raw.index.year!=2023],fixed]).sort_index()
    if len(joined.index.unique())!=len(joined) or joined.index.year.max()>=2025:
        raise ValueError("TRAINING_HISTORY_FORBIDDEN_FUTURE_YEAR")
    d=price_features(joined)
    d["regime"]=map_regimes(d)
    y,_=_windows(d,1)
    admitted=_admitted(d,PRICE_FEATURES,y)
    # Final trained outcome must finish no later than 2024.
    train_idx=np.flatnonzero(admitted)
    train_idx=train_idx[train_idx+1<len(d)]
    # 1 session embargo: the most recent training label must end
    # >= one extra completed session before the freeze's training end.
    train_idx=train_idx[train_idx+2<len(d)]
    if len(train_idx)<1200:
        raise ValueError("INSUFFICIENT_PRICE_ONLY_TRAINING_ROWS")
    x=d[list(PRICE_FEATURES)].to_numpy(dtype=float)[train_idx]
    fit=_ridge(x,y[train_idx],500.0)
    model={
        "model_contract":CONTRACT,
        "params":PARAMS,
        "fitted_intercept_log_return":float(fit["intercept"]),
        "fitted_beta_log_return_per_standardized_feature":[
            float(z) for z in fit["beta"]],
        "training_feature_mean":[float(z) for z in fit["mu"]],
        "training_feature_std":[float(z) for z in fit["sd"]],
        "training_rows":len(train_idx),
        "training_last_decision_utc":d.index[train_idx[-1]].isoformat(),
        "training_last_label_end_utc":d.index[train_idx[-1]+1].isoformat(),
        "training_date_min_utc":d.index[train_idx[0]].isoformat(),
        "trained_2025_2026_outcomes":False,
        "provider_2023_repaired_rows":len(fixed),
        "price_source_sha256_by_year":{
            **{k:v["sha256"] for k,v in original.items() if k!="2023"},
            "2023_dukas":recovery["recovered_csv_sha256"],
        },
        "source_2023_substitution_repair_checksum":
            recovery["recovered_csv_sha256"],
        "source_2023_histdata_original_sha256":original["2023"]["sha256"],
        "source_reproducibility":"provenance_has_source_SHA256_and_actions_run_ids",
        "original_macro_publication_clock_verified":False,
        "genuinely_untouched_holdout_evaluated":False,
        "fit_is_validated_alpha":False,
        "production_order_authority":False,
    }
    model["frozen_payload_sha256"]=_hash(model)
    return model


def predict_from_frozen(model,closed_gold:pd.DataFrame):
    if model.get("model_contract")!=CONTRACT:
        raise ValueError("UNKNOWN_FROZEN_MODEL_CONTRACT")
    payload={k:v for k,v in model.items() if k!="frozen_payload_sha256"}
    if _hash(payload)!=model.get("frozen_payload_sha256"):
        raise ValueError("FROZEN_PARAMETER_HASH_MISMATCH")
    if model["params"]!=PARAMS:
        raise ValueError("FROZEN_MODEL_PARAMETERS_MODIFIED")
    if not isinstance(closed_gold.index,pd.DatetimeIndex) or closed_gold.index.tz is None:
        raise ValueError("DAILY_PRICE_TIMESTAMP_REQUIRED")
    if closed_gold.index.has_duplicates or not closed_gold.index.is_monotonic_increasing:
        raise ValueError("PRICE_HISTORY_NOT_SORTED_UNIQUE")
    if len(closed_gold)<90:
        raise ValueError("NOT_ENOUGH_CLOSED_GOLD_SESSIONS")
    # Caller must provide ONLY genuinely completed UTC day candles.
    x=price_features(closed_gold)
    last=x.iloc[-1]
    vals=np.asarray([last[z] for z in PRICE_FEATURES],dtype=float)
    if not np.isfinite(vals).all() or not (last[["open","high","low","close"]]>0).all():
        raise ValueError("INVALID_OR_STALE_PRICE_FACTOR")
    mu=np.asarray(model["training_feature_mean"],dtype=float)
    sd=np.asarray(model["training_feature_std"],dtype=float)
    beta=np.asarray(model["fitted_beta_log_return_per_standardized_feature"],
                    dtype=float)
    if len(mu)!=4 or len(sd)!=4 or len(beta)!=4 or np.any(sd<=0):
        raise ValueError("UNSAFE_FROZEN_MODEL_DIMENSION")
    z=np.clip((vals-mu)/sd,-4.,4.)
    predicted=float(model["fitted_intercept_log_return"]+z@beta)
    if not np.isfinite(predicted):
        raise ValueError("NONFINITE_FROZEN_MODEL_SCORE")
    side=("SEARCH_BUY" if predicted>0 else
          "SEARCH_SELL" if predicted<0 else "WAIT")
    return {
        "contract":"RIZAN_R72_ONE_DAY_SHADOW_DIRECTION_V1",
        "training_model_contract":CONTRACT,
        "frozen_payload_sha256":model["frozen_payload_sha256"],
        "source_last_completed_session_utc":x.index[-1].isoformat(),
        "source_session_close_usd_per_oz":float(last.close),
        "price_features_asof":{z:float(last[z]) for z in PRICE_FEATURES},
        "observed_price_regime":str(map_regimes(closed_gold).iloc[-1]),
        "estimated_next_session_log_return":predicted,
        "research_search_side":side,
        "relative_global_factor_weights_pct":{
            z:(round(float(abs(beta[j])/np.abs(beta).sum()*100),4)
               if np.abs(beta).sum()>1e-15 else 0)
            for j,z in enumerate(PRICE_FEATURES)},
        "claim_80_percent_success":False,
        "predicted_probability_calibrated":False,
        "historical_2025_2026_used_for_recalibration":False,
        "new_unseen_forward_accuracy_known":False,
        "order_authority":False,
        "frozen_v1_influence":False,
    }


def write_freeze(*,historical_root,repaired_root,output):
    model=train_freeze(historical_root=historical_root,
                       repaired_root=repaired_root)
    out=Path(output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(_canon(model)+b"\n")
    print("R72_FROZEN_CANDIDATE "+json.dumps({
        "frozen_payload_sha256":model["frozen_payload_sha256"],
        "training_rows":model["training_rows"],
        "training_last_label_end":model["training_last_label_end_utc"],
        "beta":model["fitted_beta_log_return_per_standardized_feature"],
        "model_params":PARAMS,
    },sort_keys=True),flush=True)


if __name__=="__main__":
    import os
    write_freeze(historical_root=os.environ["R72_TRAIN_SHARDS"],
                 repaired_root=os.environ["R72_REPAIRED_2023"],
                 output=os.environ.get("R72_FROZEN_OUT",
                                      "artifacts/r72-frozen-candidate.json"))
