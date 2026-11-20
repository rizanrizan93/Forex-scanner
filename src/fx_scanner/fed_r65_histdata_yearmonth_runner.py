"""Fetch publicly available XAU M1 on GitHub Actions, run price-only R6.5 audit.

No broker credentials, live trading endpoints, private feeds, or orders.
Eight ONE-MONTH samples, not an exhaustive 2019-2026 historical replay.
"""
from __future__ import annotations
from datetime import UTC,date,datetime,timedelta
from pathlib import Path
import hashlib
import json
import os
import pandas as pd
from .research_xau_histdata_download_v193 import _normalize_frame,PROVIDER_COMMIT
from .fed_r65_histdata_price_audit import audit_price_only_four_hours


def run():
    from histdata_fetcher import fetch_data
    ym=os.environ["R65_AUDIT_MONTH"]
    if not len(ym)==7 or ym[4]!="-":
        raise SystemExit("INVALID_YEAR_MONTH")
    year,month=map(int,ym.split("-"))
    if not 2019<=year<=2026 or not 1<=month<=12:
        raise SystemExit("YEAR_MONTH_OUTSIDE_STUDY")
    start=date(year,month,1)-timedelta(days=16)
    end=(date(year+1,1,1) if month==12
         else date(year,month+1,1))-timedelta(days=1)
    if end>=datetime.now(UTC).date():
        end=min(end,datetime.now(UTC).date()-timedelta(days=1))
    data=fetch_data(pair="XAUUSD",start_date=start,end_date=end,
                    timeframe="1min",output_format=None,max_workers=1)
    if data.data.empty:
        raise SystemExit("HISTDATA_NO_SOURCE_BARS")
    cleaned=_normalize_frame(data.data)
    cleaned=cleaned[(cleaned.timestamp.dt.date>=start)&
                    (cleaned.timestamp.dt.date<=end)].copy()
    if len(cleaned)<4000:
        raise SystemExit("HISTDATA_TOO_FEW_REAL_M1")
    m1=cleaned.set_index("timestamp")[["open","high","low","close"]]
    result=audit_price_only_four_hours(m1,year=year,month=month)
    if result["status"]!="PRICE_ONLY_DIAGNOSTIC":
        raise SystemExit("R65_NOT_ENOUGH_REAL_DATA")
    fetched=list(data.fetched_periods)
    failed=[{
        "label":str(f.period_label),"reason":str(f.reason)
    } for f in data.failed_periods]
    checksum=hashlib.sha256(
        cleaned.to_csv(index=False).encode("utf-8")).hexdigest()
    result["provenance"]={
        "provider":"https://www.histdata.com/ via histdata-fetcher",
        "provider_commit":PROVIDER_COMMIT,
        "timezone_original":"UTC-05:00_FIXED_EST",
        "first_m1_utc":cleaned.timestamp.iloc[0].isoformat(),
        "last_m1_utc":cleaned.timestamp.iloc[-1].isoformat(),
        "processed_raw_m1_checksum":checksum,
        "source_download_start":start.isoformat(),
        "source_download_end":end.isoformat(),
        "fetched_periods":fetched,"failed_periods":failed,
        "partial_vendor_coverage_possible":bool(failed)
    }
    out=Path("artifacts")/f"r65-price-only-4h-{ym}.json"
    out.parent.mkdir(exist_ok=True,parents=True)
    out.write_text(json.dumps(result,indent=2,allow_nan=False,default=str))
    base=result["cohorts"]["0.4"]
    print("R65_REAL_HISTDATA_4H_PRICE_ONLY "+json.dumps({
        "month":ym,"m1_rows":result["source_m1_rows"],
        "candidate_n":result["candidate_count"],
        "allowed_n":result["guarded_count"],
        "blocked_n":result["blocked_count"],
        "accuracy_baseline_pct":base["baseline"]["accuracy_pct"],
        "accuracy_guarded_pct":base["guarded"]["accuracy_pct"],
        "buy_n":base["buy_baseline"]["n"],
        "sell_n":base["sell_baseline"]["n"],
        "source_errors":len(failed),
        "full_macro_backtest":False,
    },sort_keys=True),flush=True)

if __name__=="__main__":
    run()
