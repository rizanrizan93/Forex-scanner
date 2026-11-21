"""R7.4 real-price finite multi-million XAU/Fed/COT research runner.

No 2025-26 uploads are downloaded, import is pre-2025 only.
Provenance and every fold's selected configuration recorded.
Each job evaluates ONE horizon + ONE 2023 source cohort.
"""
from __future__ import annotations
import json,os
from pathlib import Path
import pandas as pd
from .fed_r71_nested_real_runner import _verified_orig_source,_independent_repair
from .fed_r7_fred_proxy_panel import fetch_fred_proxies,align_retrospective_proxies
from .fed_r71_official_treasury_dollar import align_official_and_dollar
from .fed_r73_official_policy_cot_panel import align_fed_policy_cot_risk
from .fed_r74_finite_million_grid import (
    finite_nested_search,configured_count,CONTRACT)

RUN_CONTRACT="RIZAN_R74_REAL_PRE2025_FINITE_GRID_RESULTS_V1"
COHORTS=("REPAIRED_2023_DUKA","ORIGINAL_2023_HISTDATA_GAPS")
HORIZONS=("D1","W1","M1")


def run():
    horizon=os.environ["R74_HORIZON"]
    cohort=os.environ["R74_2023_COHORT"]
    if horizon not in HORIZONS or cohort not in COHORTS:
        raise ValueError("R74_UNREGISTERED_HORIZON_OR_SOURCE")
    original,old_meta=_verified_orig_source(
        os.environ["R74_XAU_ORIGINAL_2018_24"])
    repaired,rep_meta=_independent_repair(
        os.environ["R74_XAU_2023_DUKA"])
    if cohort=="REPAIRED_2023_DUKA":
        gold=pd.concat([
            original[original.index.year!=2023],repaired]).sort_index()
    else:
        gold=original
    if gold.index.has_duplicates or max(gold.index.year)>2024:
        raise ValueError("R74_ONLY_PRE_2025_PRICE_AND_NO_DUPLICATE")
    fred,fred_meta=fetch_fred_proxies()
    xau=align_retrospective_proxies(gold,fred)
    base,treasury_usd_meta=align_official_and_dollar(
        xau,treasury_root=os.environ["R74_TREASURY_ROOT"],
        dollar_root=os.environ["R74_DOLLAR_ROOT"])
    panel,policy_cot_meta=align_fed_policy_cot_risk(
        base,fred_root=os.environ["R74_FRED_POLICY_ROOT"],
        cftc_root=os.environ["R74_CFTC_ROOT"],
        treasury_root=os.environ["R74_TREASURY_ROOT"])
    actual=finite_nested_search(panel,horizon=horizon)
    result={
        "run_contract":RUN_CONTRACT,
        "model_contract":CONTRACT,
        "source_cohort":cohort,"horizon":horizon,
        "predeclared_total_unique_configurations_three_horizons":
            configured_count(),
        "predeclared_price_vendor_cohorts":list(COHORTS),
        "2025_2026_values_labels_in_the_input":False,
        "has_true_CME_premeeting_FedWatch":False,
        "has_official_ICE_DXY":False,
        "has_verified_historical_publication_receipt":False,
        "Fed_policy_rate_change_is_NOT_FOMC_surprise":True,
        "gold_old_2023_source_days":old_meta["2023"]["days"],
        "gold_repaired_2023_source_days":len(repaired),
        "independent_gold_2023_repair_sha":
            rep_meta["recovered_csv_sha256"],
        "gold_source_sha256_by_year":{
            yr:v["sha256"] for yr,v in old_meta.items()},
        "fred_retrospective_provenance":fred_meta,
        "treasury_and_dollar_provenance":treasury_usd_meta,
        "fed_and_cot_and_vix_provenance":policy_cot_meta,
        "result":actual,
        "research_only":True,
        "cBot_trading_changed":False,
        "frozen_r72_model_changed":False,
        "production_promotion":"REJECT_UNTIL_NEW_PROSPECTIVE_HOLDOUT",
    }
    outfile=Path(f"artifacts/r74-million-grid-{cohort}-{horizon}.json")
    outfile.parent.mkdir(parents=True,exist_ok=True)
    outfile.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("R74_COMPLETE_REAL_FINITE_GRID "+json.dumps({
        "cohort":cohort,"horizon":horizon,
        "per_horizon_unique":actual["unique_configs_each_horizon"],
        "fold_configuration_scores":actual["total_fold_config_scoring_evaluations"],
        "outer_fold_results":[{
            "outer_year":f.get("outer_year",f.get("year")),
            "status":f["status"],
            "n_eval":f.get("outer_evaluation_n"),
            "candidate":f.get("model_results",{}).get("R74_SELECTED",{}),
            "paired_r72":f.get("comparisons",{}).get(
                "R72_PRICE_ONLY_FIXED_RIDGE_500"),
            "selected":f.get("selected_inner_candidate"),
        } for f in actual["outer_development_folds"]],
        "untouched_holdout_scored":False,
        "trading_authority":False,
    },sort_keys=True),flush=True)


if __name__=="__main__":
    run()
