"""R7 historical real-price daily research shard (secondary market vendor).

Fetches actual HistData XAUUSD M1 for one calendar year, saves UTC daily
OHLC. Day boundary is UTC 00:00, NOT FP Markets or NY-17 session;
the result is a sensitivity study, never broker execution parity.
"""
from __future__ import annotations
from datetime import UTC,date,datetime
from pathlib import Path
import hashlib,json,os
import pandas as pd
from .research_xau_histdata_download_v193 import _normalize_frame,PROVIDER_COMMIT


def download_year(year:int):
    from histdata_fetcher import fetch_data
    if not 2018<=year<=datetime.now(UTC).year:
        raise ValueError("YEAR_OUTSIDE_STUDY")
    start,end=date(year,1,1),date(year,12,31)
    if year==datetime.now(UTC).year:
        end=min(end,datetime.now(UTC).date())
    result=fetch_data(pair="XAUUSD",start_date=start,end_date=end,
                      timeframe="1min",output_format=None,max_workers=1)
    if result.data.empty:
        raise RuntimeError("HISTDATA_EMPTY")
    d=_normalize_frame(result.data)
    d=d[(d.timestamp.dt.year==year)].sort_values("timestamp")
    if len(d)<60000:
        raise RuntimeError("INSUFFICIENT_PUBLIC_XAU_M1")
    d["session_utc"]=d.timestamp.dt.floor("D")
    g=d.groupby("session_utc",sort=True)
    daily=g.agg(
        open=("open","first"),high=("high","max"),
        low=("low","min"),close=("close","last"),
        minute_rows=("close","count"),
        first_m1=("timestamp","min"),last_m1=("timestamp","max"))
    # Require near-full active trading day; no synthetic forward fill.
    daily=daily[daily.minute_rows>=1000]
    if daily.empty:
        raise RuntimeError("NO_COMPLETE_DAILY_XAU_BARS")
    # Compute gaps WITHIN each UTC day, excluding weekend rollover.
    # No forward-filled or interpolated missing intraday bars.
    d["intraday_gap_s"]=(
        d.groupby("session_utc")["timestamp"].diff().dt.total_seconds().fillna(60))
    daily["max_interbar_gap_s"]=(
        d.groupby("session_utc")["intraday_gap_s"].max()
         .reindex(daily.index).fillna(60))
    # Spot gold routinely has a daily maintenance break; an M1 hole
    # >30m is not by itself corrupted history. Admit up to 2h, still
    # demand >=1000 observed source minutes and record maximum gaps.
    eligible_before=int(len(daily))
    daily=daily[daily.max_interbar_gap_s<=7200].copy()
    daily=daily[(daily.index.dayofweek<5)]
    if len(daily)<100:
        raise RuntimeError(
            f"TOO_FEW_VALID_TRADING_SESSIONS:year={year}"
            f":before_gap_screen={eligible_before}:after={len(daily)}"
            f":source_m1={len(d)}")
    outdir=Path("artifacts/r7-daily");outdir.mkdir(parents=True,exist_ok=True)
    dest=outdir/f"xau-daily-{year}.csv"
    daily.reset_index().to_csv(dest,index=False,float_format="%.7f")
    checksum=hashlib.sha256(dest.read_bytes()).hexdigest()
    provenance={
        "contract":"RIZAN_R7_SECONDARY_XAU_DAILY_SHARD_V1",
        "year":year,"source":"HISTDATA_XAUUSD_M1",
        "provider_commit":PROVIDER_COMMIT,
        "source_timestamps":"FIXED_EST_TO_UTC",
        "session_definition":"UTC_00:00_DAY_REQUIRES_1000_M1",
        "source_m1_rows":len(d),"accepted_daily_rows":len(daily),
        "first_day":daily.index[0].isoformat(),"last_day":daily.index[-1].isoformat(),
        "sha256":checksum,
        "failed_periods":[{
            "period_label":str(f.period_label),"reason":str(f.reason)}
            for f in result.failed_periods],
        "broker_execution_parity":False,"point_in_time_macro_provenance":False,
        "order_authority":False,
    }
    dest.with_suffix(".json").write_text(json.dumps(provenance,indent=2))
    print("R7_HISTDATA_DAILY "+json.dumps({
        "year":year,"source_m1_rows":len(d),
        "accepted_daily_rows":len(daily),
        "failed_periods":len(result.failed_periods)}),flush=True)


if __name__=="__main__":
    download_year(int(os.environ["R7_PRICE_YEAR"]))
