"""R7 retrospective macro proxy alignment: newest FRED vintages NOT PIT.

These series deliberately have conservative assumed as-of publication lags.
Original vintage and intraday release times are NOT captured. Consequently
this dataset must never be supplied to the live R7 point-in-time engine or
declared a validated Fed-surprise/DXY/COMEX factor history.
"""
from __future__ import annotations
from hashlib import sha256
from io import StringIO
from urllib.request import Request,urlopen
from pandas.tseries.offsets import BDay
import pandas as pd
import numpy as np

SERIES={
    "DFII10":("real10_delta_5_bps",3),
    "DGS2":("nom2_delta_5_bps",3),
    "T10YIE":("breakeven10_delta_5_bps",3),
    "DTWEXBGS":("broad_usd_ret5_pct",10),
    "VIXCLS":("vix_ret5_pct",3),
}
CONTRACT="RIZAN_R7_LATEST_VINTAGE_MACRO_PROXY_NOT_PIT_V1"


def fetch_fred_proxies(*,opener=urlopen):
    out={}
    provenance={}
    for series,(_,lag) in SERIES.items():
        url=f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
        req=Request(url,headers={"User-Agent":"RIZAN-R7-ReadOnlyResearch/1.0"})
        with opener(req,timeout=35) as response:
            raw=response.read(10_000_001)
        if len(raw)>10_000_000:
            raise ValueError("FRED_SOURCE_TOO_LARGE")
        frame=pd.read_csv(StringIO(raw.decode("utf-8")))
        datecol="DATE" if "DATE" in frame.columns else "observation_date"
        if datecol not in frame.columns or series not in frame.columns:
            raise ValueError("FRED_SERIES_SCHEMA_CHANGED:"+series)
        idx=pd.to_datetime(frame[datecol],utc=True,errors="raise")
        values=pd.to_numeric(frame[series],errors="coerce")
        s=pd.Series(values.to_numpy(dtype=float),index=idx,name=series)
        s=s.dropna().sort_index()
        if s.index.has_duplicates or len(s)<1500:
            raise ValueError("FRED_SERIES_HISTORY_INCOMPLETE:"+series)
        out[series]=s
        provenance[series]={
            "url":url,"sha256":sha256(raw).hexdigest(),
            "observation_rows":int(len(s)),
            "latest_observation":s.index[-1].isoformat(),
            "lag_assumed_us_business_days":lag,
            "historical_original_vintage_verified":False,
        }
    return out,provenance


def align_retrospective_proxies(gold:pd.DataFrame, series:dict):
    """Signals observed after conservative BDay lag, not true release stamp."""
    if not isinstance(gold.index,pd.DatetimeIndex) or gold.index.tz is None:
        raise ValueError("GOLD_DAILY_UTC_REQUIRED")
    d=gold.copy()
    d.index=d.index.tz_convert("UTC")
    if not {"open","close"}.issubset(d.columns):
        raise ValueError("GOLD_OHLC_REQUIRED")
    if (d.index.has_duplicates or not d.index.is_monotonic_increasing
        or d[["open","close"]].isna().any().any()):
        raise ValueError("GOLD_DAILY_BAD_INDEX_OR_PRICE")
    for source,(name,lag) in SERIES.items():
        if source not in series:
            raise ValueError("MISSING_FRED_SERIES:"+source)
        s=series[source].dropna()
        if s.empty or s.index.tz is None:
            raise ValueError("MISSING_FRED_DATA:"+source)
        # Macro from prior observations only; carry last published
        # reported value, never today's unreleased record.
        # Conservative lag is still NOT historical release proof.
        before=(s-s.shift(5)) if source in ("DFII10","DGS2","T10YIE") else (
            100*(s/s.shift(5)-1))
        available=(before.index.tz_localize(None)+BDay(lag)).tz_localize("UTC")
        release=pd.DataFrame({"published_at":available,
                              name:before.to_numpy(dtype=float)})
        release=release.dropna().sort_values("published_at")
        target=pd.DataFrame({"decision_at":d.index})
        joined=pd.merge_asof(target,release,left_on="decision_at",
                             right_on="published_at",direction="backward")
        freshness_days=(joined.decision_at-joined.published_at).dt.total_seconds()/86400
        # Do not extrapolate weeks of missing feeds.
        d[name]=np.where(freshness_days <= (25 if source=="DTWEXBGS" else 10),
                         joined[name].to_numpy(),np.nan)
    # Research-only technical factors derived from completed daily XAU.
    px=d.close
    d["xau_mom5_pct"]=100*(px/px.shift(5)-1)
    d["xau_mom21_pct"]=100*(px/px.shift(21)-1)
    d["xau_rvol21_pct"]=100*px.pct_change().rolling(21,min_periods=21).std()
    d.attrs["macro_contract"]=CONTRACT
    d.attrs["historical_original_vintage_verified"]=False
    d.attrs["order_authority"]=False
    return d
