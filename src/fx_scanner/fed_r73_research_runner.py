"""Run source-hashed R7.3 nested paired test on real XAUUSD 2018-24.

Original HistData and independently repaired Dukascopy 2023 cohorts,
each with identical factor-date baseline/challengers. No 2025-26
prices are downloaded, imported, scored or reused as fresh holdout.
"""
from __future__ import annotations
from pathlib import Path
import os,json
import pandas as pd
from .fed_r71_nested_real_runner import _verified_orig_source,_independent_repair
from .fed_r7_fred_proxy_panel import fetch_fred_proxies,align_retrospective_proxies
from .fed_r71_official_treasury_dollar import align_official_and_dollar
from .fed_r73_official_policy_cot_panel import align_fed_policy_cot_risk
from .fed_r73_nested_matched_ablation import run_nested_matched_ablation,HORIZONS

CONTRACT="RIZAN_R73_ACTUAL_FED_COT_VIX_NESTED_AUDITED_DEV_V1"


def run():
    original,old_meta=_verified_orig_source(os.environ["R73_XAU_ORIGINAL_2018_24"])
    repaired,repair_meta=_independent_repair(os.environ["R73_XAU_2023_DUKA"])
    if set(original.index.year)!=set(range(2018,2025)):
        raise ValueError("R73_PRICE_HISTORY_MUST_BE_PRE_2025")
    replace=pd.concat([
        original[original.index.year!=2023],repaired]).sort_index()
    if replace.index.has_duplicates:
        raise ValueError("R73_TWO_GOLD_VENDORS_MUST_NOT_OVERLAP")
    fseries,fred_base_proof=fetch_fred_proxies()
    output={
        "contract":CONTRACT,
        "sources":{
            "xau_histdata_2018_2024":old_meta,
            "xau_dukas_repaired_2023_sha":repair_meta["recovered_csv_sha256"],
            "xau_original_2023_days":old_meta["2023"]["days"],
            "xau_repaired_2023_days":len(repaired),
            "historical_fred_base":fred_base_proof,
        },
        "data_period":"2018-2024_DEVELOPMENT_ONLY",
        "2025_2026_prior_holdout_loaded":False,
        "actual_CME_fedwatch_probabilities_used":False,
        "actual_premeeting_FOMC_market_surprise_used":False,
        "actual_FOMC_statement_NLP_used":False,
        "actual_FOMC_dotplot_used":False,
        "actual_COT_managed_money_positions_used":True,
        "actual_CFTC_report_receipt_timestamp_verified":False,
        "real_Treasury_observations_used":True,
        "real_VIX_FRED_observations_used":True,
        "source_vintage_verified_originally":False,
        "original_bid_ask_trading_cost_verified":False,
        "forward_fresh_post_R72_freeze_scored":False,
        "production_recommendation":"RESEARCH_ONLY_WAIT",
        "results":{},
    }
    for cohort,prices in (
        ("ORIGINAL_2023_MISSING_SOURCE",original),
        ("REPAIRED_2023_DUKAS_SOURCE",replace),
    ):
        prior=align_retrospective_proxies(prices,fseries)
        treasury_dollar,source1=align_official_and_dollar(
            prior,treasury_root=os.environ["R73_TREASURY_ROOT"],
            dollar_root=os.environ["R73_DOLLAR_ROOT"])
        full,source2=align_fed_policy_cot_risk(
            treasury_dollar,
            fred_root=os.environ["R73_FRED_POLICY_ROOT"],
            cftc_root=os.environ["R73_CFTC_ROOT"],
            treasury_root=os.environ["R73_TREASURY_ROOT"])
        output["sources"][cohort]={"treasury_dollar":source1,
                                    "fed_policy_cot_vix":source2}
        output["results"][cohort]={}
        for h in ("D1","W1","M1","Y1"):
            record=run_nested_matched_ablation(full,horizon=h)
            output["results"][cohort][h]=record
            cohorts=record.get("summary",{})
            report={}
            for group,res in cohorts.items():
                report[group]={
                    "n":res["matched_evaluation_n"],
                    "acc_pct":res["direction_accuracy_pct"],
                    "rmse":res["pooled_oos_development_rmse_log_return"],
                    "delta_rmse":res["paired_rmse_delta_vs_r72_method"],
                    "buy_n":res["buy_n"],"sell_n":res["sell_n"],
                }
            print("R73_NESTED_MATCHED_ACTUAL "+json.dumps({
                "source_cohort":cohort,"horizon":h,
                "status":record["status"],
                "fresh_untouched_holdout":False,
                "has_real_fedwatch":False,
                "has_true_FOMC_surprise":False,
                "paired_models":report},sort_keys=True),flush=True)
    out=Path("artifacts/r73-macro-fed-cot-nested-matched.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(output,indent=2,sort_keys=True,allow_nan=False))
    print("R73_RESEARCH_COMPLETED "+json.dumps({
        "cohorts":len(output["results"]),"horizons":4,
        "old_2023_days":old_meta["2023"]["days"],
        "repaired_2023_days":len(repaired),
        "new_prospective_forward_signals_scored":0,
        "production_alpha_certified":False,
    }),flush=True)


if __name__=="__main__":
    run()
