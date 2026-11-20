"""R7.1 empirical official Treasury observation + broker USD proxy nested test.

Daily Treasury officially sourced, with observation date and assumed
2-calendar-day signal delay; Duke DOLLAR.IDX H1 BID uses source
timestamp and an explicit conservative delay. Does NOT manufacture
actual 2018-24 publication timestamps nor ICE-licensed DXY.
"""
from __future__ import annotations
from pathlib import Path
import os,json
from .fed_r71_nested_real_runner import _verified_orig_source,_independent_repair
from .fed_r7_fred_proxy_panel import fetch_fred_proxies,align_retrospective_proxies
from .fed_r71_official_treasury_dollar import align_official_and_dollar
from .fed_r71_nested_regime import nested_regime_walk_forward,HORIZONS

CONTRACT="RIZAN_R71_OFFICIAL_TREASURY_BROKER_DOLLAR_NESTED_DEV_V1"


def run():
    old,orig=_verified_orig_source(
        os.environ.get("R71_ORIGINAL_SHARDS","/tmp/r71-original"))
    repaired,repair=_independent_repair(
        os.environ.get("R71_DUKA_REPAIR","/tmp/r71-repaired"))
    new=old[old.index.year!=2023]
    import pandas as pd
    new=pd.concat([new,repaired]).sort_index()
    if new.index.has_duplicates:
        raise ValueError("DOUBLE_2023_SOURCE_ROWS")
    # Compute PRICE factors from genuinely completed past gold daily
    # bars; ignore the FRED macro columns in official-source fits.
    fred,_=fetch_fred_proxies()
    out={}
    proofs={}
    for label,price in (
        ("HISTDATA_2023_INCOMPLETE",old),
        ("DUKASCOPY_2023_COMPLETE_PROVIDER_SWITCH",new)):
        base=align_retrospective_proxies(price,fred)
        panel,source=align_official_and_dollar(
            base,treasury_root=os.environ["R71_TREASURY_ROOT"],
            dollar_root=os.environ["R71_DOLLAR_ROOT"])
        proofs[label]=source
        out[label]={}
        for horizon in HORIZONS:
            record=nested_regime_walk_forward(
                panel,horizon=horizon,include_official_observation_macro=True)
            out[label][horizon]=record
            folds=[f for f in record["folds"]
                   if f.get("status")=="NESTED_DEVELOPMENT_FOLD"]
            n=sum(f["n"] for f in folds)
            correct=sum(f["n"]*f["accuracy_pct"]/100 for f in folds
                        if f["accuracy_pct"] is not None)
            print("R71_OFFICIAL_YIELD_DUKA_DOLLAR_NESTED "+json.dumps({
                "price_vendor_cohort":label,"horizon":horizon,
                "total_n":n,"folds":len(folds),
                "direction_accuracy_pct":round(100*correct/n,3) if n else None,
                "official_treasury_observations":True,
                "true_PIT_publication_hours_verified":False,
                "ICE_DXY_direct":False,"trading_allowed":False,
            },sort_keys=True),flush=True)
    result={
        "contract":CONTRACT,
        "source_cohorts":out,"source_provenance":proofs,
        "original_2023_valid_days":orig["2023"]["days"],
        "recovered_2023_valid_days":len(repaired),
        "data_period":"2018-2024_DEVELOPMENT_ONLY",
        "quarantined_2025_2026_outcomes_still_untouched_in_this_run":True,
        "new_forward_holdout_since_2026_11_21_scored":False,
        "historical_publication_timestamp_verified":False,
        "historical_treasury_observation_date_verified":True,
        "duka_dollar_index_quotes_h1_have_original_bar_timestamps":True,
        "duka_dollar_index_is_ICE_DXY":False,
        "macro_vintage_archived_as_of_original_date":False,
        "research_only":True,
        "production_authority":False,
    }
    p=Path("artifacts/r71-official-treasury-dollar-nested.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
    print("R71_MACRO_ORIGINAL_SOURCE_EVIDENCE "+json.dumps({
        "treasury_observed_dates_not_pub_timestamps":True,
        "broker_dollar_index_not_ICE_DXY":True,
        "development_model_outcomes_fresh_holdout":0}),flush=True)

if __name__=="__main__":
    run()
