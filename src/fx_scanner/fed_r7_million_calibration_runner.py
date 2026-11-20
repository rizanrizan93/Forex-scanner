"""R7 2018-2026 XAU annual shards + retrospective FRED proxy million-grid.

Only the eight actual listed historical inputs are admitted. Outputs
clearly identify current-vintage macro as a retrospective proxy, NOT
a full point-in-time R7 model or valid order trigger.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json,os
import pandas as pd
from .fed_r7_fred_proxy_panel import fetch_fred_proxies,align_retrospective_proxies
from .fed_r7_million_grid import search_one_horizon,HORIZONS,FEATURES,GRID_PER_HORIZON


def run():
    root=Path(os.environ.get("R7_SOURCE_SHARDS","artifacts/r7-daily"))
    files=sorted(root.rglob("xau-daily-20??.csv"))
    years={int(p.stem[-4:]):p for p in files}
    required=set(range(2018,2027))
    if required!=set(years):
        raise SystemExit(f"R7_MISSING_YEAR_SHARDS:{sorted(required-set(years))}")
    chunks=[]
    proofs={}
    for year in sorted(years):
        file=years[year]
        meta=file.with_suffix(".json")
        if not meta.exists():
            raise SystemExit("R7_MISSING_YEAR_PROVENANCE:"+str(year))
        m=json.loads(meta.read_text())
        if (m.get("contract")!="RIZAN_R7_SECONDARY_XAU_DAILY_SHARD_V1"
            or m.get("year")!=year
            or m.get("sha256")!=hashlib.sha256(file.read_bytes()).hexdigest()
            or len(m.get("failed_periods",[]))>0):
            raise SystemExit("R7_UNVERIFIED_YEAR_SHARD:"+str(year))
        f=pd.read_csv(file)
        required_fields={"session_utc","open","high","low","close"}
        if not required_fields.issubset(f.columns):
            raise SystemExit("R7_INVALID_YEAR_FILE_SCHEMA")
        f["session_utc"]=pd.to_datetime(f["session_utc"],utc=True)
        f=f.set_index("session_utc")
        chunks.append(f)
        proofs[str(year)]={
            "sha256":m["sha256"],
            "source_m1_rows":m["source_m1_rows"],
            "accepted_daily_rows":m["accepted_daily_rows"]}
    daily=pd.concat(chunks).sort_index()
    if daily.index.has_duplicates:
        raise SystemExit("R7_OVERLAPPING_DAILY_YEAR_SHARDS")
    series,source_provenance=fetch_fred_proxies()
    panel=align_retrospective_proxies(daily,series)
    results={}
    for h in HORIZONS:
        r=search_one_horizon(panel,horizon=h)
        # D1/W1/M1 must actually execute full million grid or
        # explicitly fail: no claim that 1M were tested without proof.
        if h in ("D1","W1","M1") and r["trial_count_evaluated"] not in (
                GRID_PER_HORIZON,0):
            raise SystemExit("R7_PARTIAL_GRID_NOT_COUNTED:"+h)
        results[h]=r
        print("R7_MILLION_GRID_HORIZON "+json.dumps({
            "horizon":h,"status":r["status"],
            "trial_count":r["trial_count_evaluated"],
            "n_dev":r["n_development_nonoverlap"],
            "n_holdout":r["n_holdout_nonoverlap"],
            "holdout_accuracy_pct":(
                r.get("untouched_holdout_once_selected",{}).get("accuracy_pct")),
            "holdout_buy_n":(
                r.get("untouched_holdout_once_selected",{}).get("buy_n")),
            "holdout_sell_n":(
                r.get("untouched_holdout_once_selected",{}).get("sell_n")),
        },sort_keys=True),flush=True)
    output={
        "contract":"RIZAN_R7_EIGHT_YEAR_REAL_GOLD_MILLION_GRID_NO_PIT_V1",
        "data_scope":"2018-2026_XAU_AND_FRED_LATEST_VINTAGE",
        "provenance":{"xau":proofs,"fred_latest_vintage":source_provenance},
        "hypothesis":"SHORT_TERM_FACTORS_RELATIVE_WEIGHT_SCREEN",
        "factors":list(FEATURES),
        "predeclared_horizons":HORIZONS,
        "grid_per_eligible_horizon":GRID_PER_HORIZON,
        "total_actual_evaluations":sum(
            x["trial_count_evaluated"] for x in results.values()),
        "all_reported_accuracy_after_assumed_spread_usd_oz":0.4,
        "macro_original_vintage_or_release_time_verified":False,
        "dxy_ice_used":False,
        "false_precision_warning":"BROAD_USD_IS_NOT_DXY",
        "full_r7_validated":False,
        "verified_multiyear_alpha":False,
        "automated_trading_approved":False,
        "results":results,
    }
    dest=Path("artifacts/r7-million-grid-results.json")
    dest.parent.mkdir(exist_ok=True,parents=True)
    dest.write_text(json.dumps(output,indent=2,allow_nan=False))
    print("R7_GRID_TOTAL "+json.dumps({
        "real_evaluations":output["total_actual_evaluations"],
        "full_R7_validated":False}),flush=True)


if __name__=="__main__":
    run()
