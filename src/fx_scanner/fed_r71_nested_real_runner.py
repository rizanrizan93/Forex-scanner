"""R7.1 empirical regime-weight nested development study on REAL XAU prices.

Never loads 2025-26 shards or labels for fit/selection/evaluation.
Evaluate two sensitivity panels: original 2023 HistData with missing
periods, independent Dukascopy full-year 2023 replacement.
Both use UTC close bars. Cross-provider transitions are a
documented research confound, NOT simulated broker execution.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json,os
import pandas as pd
from .fed_r7_fred_proxy_panel import fetch_fred_proxies,align_retrospective_proxies
from .fed_r71_nested_regime import nested_regime_walk_forward,HORIZONS
from .fed_r71_repair_2023 import CONTRACT as REPAIRED_CONTRACT

CONTRACT="RIZAN_R71_NESTED_REAL_2018_2024_DEVELOPMENT_V1"
YEARS=set(range(2018,2025))


def _verified_orig_source(root):
    files=list(Path(root).rglob("xau-daily-20??.csv"))
    by_year={int(p.stem[-4:]):p for p in files}
    if set(by_year)!=YEARS:
        raise ValueError("MISSING_2018_2024_SOURCE_YEAR:"+str(sorted(YEARS-set(by_year))))
    panels=[]
    proven={}
    for year in sorted(by_year):
        p=by_year[year]
        meta=json.loads(p.with_suffix(".json").read_text())
        if (meta.get("contract")!="RIZAN_R7_SECONDARY_XAU_DAILY_SHARD_V1"
            or meta.get("year")!=year
            or hashlib.sha256(p.read_bytes()).hexdigest()!=meta.get("sha256")
            or meta.get("failed_periods")):
            raise ValueError("HISTDATA_YEAR_SOURCE_HASH_OR_PROVENANCE_FAILED:"+str(year))
        x=pd.read_csv(p)
        x["session_utc"]=pd.to_datetime(x.session_utc,utc=True)
        x=x.set_index("session_utc")
        if not x.index.is_monotonic_increasing or x.index.has_duplicates:
            raise ValueError("YEAR_INDEX_INVALID")
        panels.append(x[["open","high","low","close"]])
        proven[str(year)]={
            "provider":"HistData XAUUSD M1",
            "sha256":meta["sha256"],"days":len(x)}
    all_price=pd.concat(panels).sort_index()
    if all_price.index.has_duplicates or (all_price.index.year>=2025).any():
        raise ValueError("DUPLICATE_OR_QUARANTINED_PRICE_DATA")
    return all_price,proven


def _independent_repair(root):
    p=Path(root)/"xau-daily-2023-dukas-recovered.csv"
    meta=json.loads(p.with_suffix(".json").read_text())
    if meta.get("contract")!=REPAIRED_CONTRACT or (
        hashlib.sha256(p.read_bytes()).hexdigest()!=
        meta.get("recovered_csv_sha256")):
        raise ValueError("REPAIR_PROVENANCE_HASH_MISMATCH")
    if meta.get("comparison",{}).get("reference_comparison_performed") is not True:
        raise ValueError("REPAIR_NOT_INDEPENDENTLY_COMPARED")
    d=pd.read_csv(p)
    d["session_utc"]=pd.to_datetime(d.session_utc,utc=True)
    d=d.set_index("session_utc")
    if (not d.index.is_monotonic_increasing or
        d.index.has_duplicates or not (d.index.year==2023).all()):
        raise ValueError("REPAIR_YEAR_INVALID")
    return d[["open","high","low","close"]],meta


def run():
    old,orig_proven=_verified_orig_source(
        os.environ.get("R71_ORIGINAL_SHARDS","/tmp/r71-original"))
    fixed,fix_meta=_independent_repair(
        os.environ.get("R71_DUKA_REPAIR","/tmp/r71-fixed"))
    # This replacement is EXPLICIT. It does not masquerade as the same
    # price source or claim continuity of vendor bid/ask trading costs.
    new=pd.concat([old[old.index.year!=2023],fixed]).sort_index()
    if new.index.has_duplicates:
        raise ValueError("REPLACEMENT_OVERLAPS_PRICE_SESSIONS")
    series,fred_proven=fetch_fred_proxies()
    results={}
    for source,price in (
        ("ORIGINAL_HISTDATA_2023_GAPS",old),
        ("INDEPENDENT_DUKASCOPY_2023_REPLACEMENT",new),
    ):
        price_panel=align_retrospective_proxies(price,series)
        results[source]={}
        for horizon in HORIZONS:
            results[source][horizon]={}
            for macro_flag in (False,True):
                label="RETRO_MACRO_PROXY" if macro_flag else "PRICE_ONLY"
                record=nested_regime_walk_forward(
                    price_panel,horizon=horizon,
                    include_retrospective_macro=macro_flag)
                record["regime_input_source"]="DAILY_OHLC_NO_ORDERBOOK"
                record["xau_2023_source"]=source
                results[source][horizon][label]=record
                folds=[f for f in record["folds"] if f.get("status")=="NESTED_DEVELOPMENT_FOLD"]
                n=sum(f["n"] for f in folds)
                correct=sum(
                    f["n"]*f["accuracy_pct"]/100 for f in folds
                    if f["accuracy_pct"] is not None)
                print("R71_NESTED_REGIME_FOLDS "+json.dumps({
                    "year2023_dataset":source,"horizon":horizon,
                    "factor_mode":label,"complete_folds":len(folds),
                    "nested_eval_n":n,
                    "direction_accuracy_pct":round(100*correct/n,3) if n else None,
                    "not_new_untouched_holdout":True,
                    "real_2023_repair_confirmed":True,
                },sort_keys=True),flush=True)
    output={
        "contract":CONTRACT,
        "real_market_gold_source_period":"2018-2024_ONLY",
        "2025_2026_prior_seen_outcomes_quarantined":True,
        "fresh_unseen_holdout_scored":False,
        "new_untouched_start_wib":"2026-11-21T00:00:00+07:00",
        "old_original_2023_days":orig_proven["2023"]["days"],
        "repaired_independent_2023_days":len(fixed),
        "xau_provenance_original":orig_proven,
        "xau_provenance_repair":fix_meta,
        "fred_snapshots":fred_proven,
        "vintage_accurate_macro":False,
        "direct_ice_dxy_historiography":False,
        "historical_orderbook_liquidation_proof":False,
        "nested_development_results":results,
        "production_alpha_verified":False,
        "broker_execution_enabled":False,
        "frozen_v1_changed":False,
    }
    dest=Path("artifacts/r71-nested-results.json")
    dest.parent.mkdir(exist_ok=True,parents=True)
    dest.write_text(json.dumps(output,indent=2,sort_keys=True,allow_nan=False))
    print("R71_NESTED_COMPLETE "+json.dumps({
        "original_2023_days":orig_proven["2023"]["days"],
        "repaired_2023_days":len(fixed),
        "factor_modes":2,"price_sources":2,
        "horizons":len(HORIZONS),"fresh_untouched_evaluations":0}),flush=True)

if __name__=="__main__":
    run()
