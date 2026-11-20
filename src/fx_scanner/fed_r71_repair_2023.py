"""Recover full independent-provider XAUUSD 2023 UTC daily evidence.

Uses 12 separate original Dukascopy BID M1 downloads. Validates each
month's raw OHLC, epoch-ms timestamps, continuity and provenance.
NEVER overwrites HistData prices without cross-vendor comparison;
repaired year is labeled Dukascopy, to avoid silent vendor mixing.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json,re
import numpy as np
import pandas as pd

CONTRACT="RIZAN_R71_XAU_2023_INDEPENDENT_DUKASCOPY_REPAIR_V1"
MONTHS={f"{m:02d}" for m in range(1,13)}


def _load_month(path):
    d=pd.read_csv(path)
    if list(d.columns)!=["timestamp","open","high","low","close"]:
        raise ValueError("R71_DUKASCOPY_OHLC_SCHEMA_CHANGED")
    raw_ts=pd.to_numeric(d["timestamp"],errors="raise")
    if (raw_ts<1_650_000_000_000).any() or (
        raw_ts>1_730_000_000_000).any():
        raise ValueError("EXPECTED_DUKASCOPY_EPOCH_MILLIS")
    d["timestamp"]=pd.to_datetime(raw_ts,unit="ms",utc=True)
    if d.timestamp.duplicated().any() or not d.timestamp.is_monotonic_increasing:
        raise ValueError("DUKASCOPY_DUPLICATE_OR_UNSORTED_M1")
    for k in ("open","high","low","close"):
        d[k]=pd.to_numeric(d[k],errors="raise")
    if (not np.isfinite(d[["open","high","low","close"]].to_numpy()).all()
        or (d[["open","high","low","close"]]<=0).any().any()
        or (d.low>d[["open","close"]].min(axis=1)).any()
        or (d.high<d[["open","close"]].max(axis=1)).any()):
        raise ValueError("INVALID_DUKASCOPY_M1_CANDLES")
    if len(d)<10000:
        raise ValueError("EMPTY_OR_TOO_SHORT_DUKASCOPY_MONTH")
    return d


def aggregate_months(root,original_daily=None,*,outdir="artifacts/r71-dukas-repair"):
    root=Path(root)
    csvs=sorted(root.rglob("*.csv"))
    if len(csvs)!=12:
        raise ValueError(f"REQUIRE_12_INDEPENDENT_MONTHLY_SOURCES:{len(csvs)}")
    frames=[]
    source_meta={}
    months=set()
    for p in csvs:
        m=re.search(r"xauusd-m1-bid-2023-(\d{2})-\d{2}-",p.name)
        if not m:
            raise ValueError("UNRECOGNIZED_DUKASCOPY_FILENAME:"+p.name)
        month=m.group(1)
        if month in months:
            raise ValueError("DUPLICATE_MONTHLY_SOURCE")
        months.add(month)
        d=_load_month(p)
        # Target output may contain first minute of next month;
        # trim to expected month, never mix adjacent vendor shards.
        q=d[(d.timestamp.dt.year==2023)&
            (d.timestamp.dt.month==int(month))].copy()
        if len(q)<10000:
            raise ValueError("MONTH_HAS_INSUFFICIENT_2023_M1:"+month)
        frames.append(q)
        source_meta[month]={
            "file_name":p.name,"raw_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
            "full_file_rows":len(d),"admitted_month_rows":len(q),
            "first_m1":q.timestamp.iloc[0].isoformat(),
            "last_m1":q.timestamp.iloc[-1].isoformat()}
    if months!=MONTHS:
        raise ValueError("MISSING_2023_MONTHS:"+str(sorted(MONTHS-months)))
    x=pd.concat(frames,ignore_index=True).sort_values("timestamp")
    if x.timestamp.duplicated().any():
        raise ValueError("CROSS_MONTH_DUPLICATE_OR_OVERLAP")
    if len(x)<300000:
        raise ValueError("INCOMPLETE_VENDOR_2023_M1")
    x["session_utc"]=x.timestamp.dt.floor("D")
    x["intraday_gap_s"]=x.groupby("session_utc").timestamp.diff().dt.total_seconds().fillna(60)
    by=x.groupby("session_utc",sort=True)
    daily=by.agg(
        open=("open","first"),high=("high","max"),
        low=("low","min"),close=("close","last"),
        minute_rows=("close","count"),first_m1=("timestamp","min"),
        last_m1=("timestamp","max"),
        max_interbar_gap_s=("intraday_gap_s","max"))
    candidates=daily[daily.index.dayofweek<5]
    accepted=candidates[
        (candidates.minute_rows>=1000)&
        (candidates.max_interbar_gap_s<=7200)].copy()
    if len(accepted)<210:
        raise ValueError(f"DUKASCOPY_2023_RECOVERY_INCOMPLETE:{len(accepted)}")
    comparison={
        "reference_vendor":"HISTDATA_XAUUSD_M1",
        "reference_comparison_performed":False,
        "same_vendor":False,
    }
    if original_daily is not None:
        ref=Path(original_daily)
        base=pd.read_csv(ref)
        if not {"session_utc","close"}.issubset(base.columns):
            raise ValueError("HISTDATA_BASELINE_SCHEMA_INVALID")
        base["session_utc"]=pd.to_datetime(base.session_utc,utc=True)
        joined=accepted[["close"]].join(
            base.set_index("session_utc")[["close"]],how="inner",
            lsuffix="_duka",rsuffix="_histdata")
        if len(joined)<100:
            raise ValueError("TOO_FEW_DUKASCOPY_HISTDATA_OVERLAP_DAYS")
        raw_diff=abs(joined.close_duka-joined.close_histdata)
        diff_pct=100*raw_diff/joined.close_histdata
        comparison={
            "reference_vendor":"HISTDATA_XAUUSD_M1",
            "reference_comparison_performed":True,"same_vendor":False,
            "overlap_valid_days":len(joined),
            "mean_absolute_close_diff_usd":round(float(raw_diff.mean()),5),
            "median_absolute_close_diff_usd":round(float(raw_diff.median()),5),
            "p95_absolute_close_diff_usd":round(float(raw_diff.quantile(.95)),5),
            "p95_close_difference_pct":round(float(diff_pct.quantile(.95)),5),
            "max_close_difference_pct":round(float(diff_pct.max()),5),
            "reference_valid_days":len(base),
            "independent_valid_days":len(accepted),
            "additional_valid_days":len(accepted.index.difference(base.session_utc)),
            "independent_provider_study_only":True,
        }
        if float(diff_pct.quantile(.95))>0.5:
            raise ValueError("CROSS_VENDOR_PRICES_DO_NOT_AGREE")
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    file=out/"xau-daily-2023-dukas-recovered.csv"
    accepted.reset_index().to_csv(file,index=False,float_format="%.7f")
    meta={
        "contract":CONTRACT,
        "provider":"Dukascopy public M1 BID via dukascopy-node@1.51.1",
        "vendor_monthly_sources":source_meta,
        "utc_original_epoch_ms":True,
        "m1_total":len(x),"accepted_utc_daily":len(accepted),
        "screen":"weekday AND >=1000 observed M1 AND <=7200-second internal gap",
        "utc_day_is_not_ctrader_broker_session":True,
        "source_bytes_verified_by_month_sha256":True,
        "recovered_csv_sha256":hashlib.sha256(file.read_bytes()).hexdigest(),
        "comparison":comparison,
        "mixing_vendor_not_claimed":True,
        "true_broker_bid_ask_execution_not_verified":True,
        "trading_authority":False,
    }
    (out/"xau-daily-2023-dukas-recovered.json").write_text(
        json.dumps(meta,indent=2,sort_keys=True,allow_nan=False))
    print("R71_DUKA_2023_REPAIRED "+json.dumps({
        "accepted_daily":len(accepted),"source_m1":len(x),
        "reference_accepted_daily":comparison.get("reference_valid_days"),
        "additional_valid_days":comparison.get("additional_valid_days"),
        "cross_vendor_p95_diff_pct":comparison.get("p95_close_difference_pct"),
    }),flush=True)
    return meta


if __name__=="__main__":
    import os
    aggregate_months(
        os.environ["R71_DUKA_MONTH_DIR"],
        original_daily=os.environ.get("R71_HISTDATA_2023_CSV"),
        outdir=os.environ.get("R71_REPAIRED_OUTPUT","artifacts/r71-dukas-repair"))
