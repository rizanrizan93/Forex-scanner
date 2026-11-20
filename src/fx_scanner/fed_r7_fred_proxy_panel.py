"""R7 retrospective latest-vintage FRED proxy archive ALREADY IN repo.

Source research/zone_rebound/fixed10_evidence/fred_macro_snapshot.csv.gz,
captured around 2026-11-13. Real observation dates, NO original
vintage, NO exact historical publication timestamps. Conservative
assumed release lags are not a substitute for PIT capture.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from pandas.tseries.offsets import BDay
import pandas as pd
import numpy as np

CONTRACT="RIZAN_R7_REPOSITORY_FRED_LATEST_VINTAGE_NOT_PIT_V1"
FRED_SNAPSHOT=Path("research/zone_rebound/fixed10_evidence/fred_macro_snapshot.csv.gz")
SERIES={
    "DFII10":("real10_delta_5_bps",3),
    "DGS2":("nom2_delta_5_bps",3),
    "DGS10":("nom10_delta_5_bps",3),
    "DTWEXBGS":("broad_usd_ret5_pct",10),
}


def fetch_fred_proxies(*,path=FRED_SNAPSHOT):
    """Read the archived unmodified source. No network / FRED timeout risk."""
    p=Path(path)
    if not p.is_file():
        raise ValueError("R7_REPOSITORY_SNAPSHOT_MISSING")
    raw=p.read_bytes()
    if len(raw)>5_000_000 or len(raw)<100:
        raise ValueError("R7_REPOSITORY_SNAPSHOT_BAD_SIZE")
    frame=pd.read_csv(p,compression="gzip")
    if not {"observation_date",*SERIES}.issubset(frame.columns):
        raise ValueError("R7_REPOSITORY_FRED_SOURCE_SCHEMA_MISMATCH")
    dates=pd.DatetimeIndex(pd.to_datetime(frame["observation_date"],utc=True,errors="raise"))
    if dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError("R7_REPOSITORY_FRED_UNSORTED")
    out={}
    provenance={}
    archive_sha=sha256(raw).hexdigest()
    for source,(_,lag) in SERIES.items():
        s=pd.Series(pd.to_numeric(frame[source],errors="coerce").to_numpy(dtype=float),
                    index=dates,name=source).dropna()
        if len(s)<1500:
            raise ValueError("INSUFFICIENT_REPOSITORY_MACRO_HISTORY:"+source)
        out[source]=s
        provenance[source]={
            "file":str(p),"sha256":archive_sha,
            "observation_rows":int(len(s)),
            "latest_observation":s.index[-1].isoformat(),
            "lag_assumed_us_business_days":lag,
            "historical_original_vintage_verified":False,
            "verified_exact_publication_time":False,
            "source":"IN_REPO_FRED_LATEST_VINTAGE_GZIP",
        }
    return out,provenance


def align_retrospective_proxies(gold:pd.DataFrame, series:dict):
    """Observed historical FRED at assumed delayed availability only."""
    if not isinstance(gold.index,pd.DatetimeIndex) or gold.index.tz is None:
        raise ValueError("GOLD_DAILY_UTC_REQUIRED")
    d=gold.copy()
    d.index=d.index.tz_convert("UTC")
    if not {"open","high","low","close"}.issubset(d.columns):
        raise ValueError("GOLD_OHLC_REQUIRED")
    if (d.index.has_duplicates or not d.index.is_monotonic_increasing
        or d[["open","high","low","close"]].isna().any().any()):
        raise ValueError("GOLD_DAILY_BAD_INDEX_OR_PRICE")
    for source,(name,lag) in SERIES.items():
        if source not in series:
            raise ValueError("MISSING_FRED_SERIES:"+source)
        s=series[source].dropna()
        if s.empty or s.index.tz is None:
            raise ValueError("MISSING_FRED_DATA:"+source)
        before=(s-s.shift(5)) if source!="DTWEXBGS" else 100*(s/s.shift(5)-1)
        available=(before.index.tz_localize(None)+BDay(lag)).tz_localize("UTC")
        release=pd.DataFrame({"published_at":available,name:before.to_numpy(dtype=float)})
        release=release.dropna().sort_values("published_at")
        target=pd.DataFrame({"decision_at":d.index})
        joined=pd.merge_asof(target,release,left_on="decision_at",
                             right_on="published_at",direction="backward")
        age=(joined.decision_at-joined.published_at).dt.total_seconds()/86400
        d[name]=np.where(age <= (25 if source=="DTWEXBGS" else 10),
                         joined[name].to_numpy(),np.nan)
    close=d.close
    d["xau_mom5_pct"]=100*(close/close.shift(5)-1)
    d["xau_mom21_pct"]=100*(close/close.shift(21)-1)
    d["xau_rvol21_pct"]=100*close.pct_change().rolling(21,min_periods=21).std()
    d["xau_range5_pct"]=100*((d.high-d.low)/close).rolling(5,min_periods=5).mean()
    d.attrs["macro_contract"]=CONTRACT
    d.attrs["historical_original_vintage_verified"]=False
    d.attrs["execution_authority"]=False
    return d
