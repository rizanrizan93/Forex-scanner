"""R7.1 OFFICIAL Treasury 2Y/10Y and real 10Y + historical dollar CFD.

Sources:
* US Treasury original CSV archive 1990-2023 nominal/2003-2023 real,
  and official 2024 Atom XML. Observed dates are not release timestamps.
* Dukascopy DOLLAR.IDX/USD H1 BID bars 2018-2024, a broker CFD quote
  and NOT ICE licensed DXY. H1 timestamps indicate bar OPEN, not
  an original evidence-backed receipt clock at a historic decision.

Conservative 2-calendar-day lag on both data families. This avoids
same-day lookahead but does NOT certify historical exact publication
times or original data vintages. Any actual trading model must remain WAIT.
"""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
from datetime import timezone
import json
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd

CONTRACT="RIZAN_R71_TREASURY_DOLLAR_PROXY_ARCHIVE_NOT_INTRADAY_PIT_V1"
HIST_YEARS=set(range(2018,2025))
NS={
    "a":"http://www.w3.org/2005/Atom",
    "m":"http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d":"http://schemas.microsoft.com/ado/2007/08/dataservices",
}
TREASURY={
    "nominal_1990_2023.csv":("nominal",None),
    "real_2003_2023.csv":("real",None),
    "nominal_2024.xml":("nominal",2024),
    "real_2024.xml":("real",2024),
}


def _read_official_treasury(root):
    root=Path(root)
    all_by_type={"nominal":[],"real":[]}
    provenance={}
    for filename,(kind,year) in TREASURY.items():
        p=root/filename
        if not p.exists():
            raise ValueError("TREASURY_OFFICIAL_ARCHIVE_MISSING:"+filename)
        raw=p.read_bytes()
        provenance[filename]={"source_sha256":sha256(raw).hexdigest(),
                              "source_original_url":"https://home.treasury.gov/",
                              "historic_publish_at_verified":False}
        if filename.endswith(".csv"):
            table=pd.read_csv(p)
            if kind=="nominal":
                if not {"date","2 yr","10 yr"}.issubset(table.columns):
                    raise ValueError("TREASURY_NOMINAL_ARCHIVE_SCHEMA_CHANGED")
                data=table[["date","2 yr","10 yr"]].rename(
                    columns={"date":"observed_date","2 yr":"ust2y_pct",
                             "10 yr":"ust10y_pct"})
            else:
                if not {"date","10 yr"}.issubset(table.columns):
                    raise ValueError("TREASURY_REAL_ARCHIVE_SCHEMA_CHANGED")
                data=table[["date","10 yr"]].rename(
                    columns={"date":"observed_date","10 yr":"tips10y_pct"})
            data["observed_date"]=pd.to_datetime(data.observed_date,
                format="%m/%d/%Y",utc=True,errors="raise")
        else:
            root_elem=ET.fromstring(raw)
            records=[]
            for e in root_elem.findall("a:entry",NS):
                props=e.find(".//m:properties",NS)
                if props is None:continue
                fields={t.tag.rsplit("}",1)[-1]:t.text for t in props}
                if "NEW_DATE" not in fields: continue
                row={"observed_date":pd.Timestamp(fields["NEW_DATE"],tz="UTC")}
                if kind=="nominal":
                    row["ust2y_pct"]=fields.get("BC_2YEAR")
                    row["ust10y_pct"]=fields.get("BC_10YEAR")
                else:
                    row["tips10y_pct"]=fields.get("TC_10YEAR")
                records.append(row)
            if len(records)<200:
                raise ValueError("TREASURY_2024_XML_TOO_FEW_ENTRIES:"+kind)
            data=pd.DataFrame(records)
            if not (data.observed_date.dt.year==2024).all():
                raise ValueError("TREASURY_XML_UNEXPECTED_YEAR")
            # Atom <updated> is feed refresh time (often 2026), NOT
            # the year-2024 original publication clock.
            provenance[filename]["atom_updated_not_original_publication"]=True
        for c in data.columns:
            if c!="observed_date":
                data[c]=pd.to_numeric(data[c],errors="coerce")
        data=data[(data.observed_date.dt.year>=2018)&(
            data.observed_date.dt.year<=2024)]
        all_by_type[kind].append(data)
    nominal=pd.concat(all_by_type["nominal"]).drop_duplicates(
        "observed_date",keep="last").set_index("observed_date").sort_index()
    real=pd.concat(all_by_type["real"]).drop_duplicates(
        "observed_date",keep="last").set_index("observed_date").sort_index()
    rates=nominal.join(real,how="outer").sort_index()
    if len(rates)<1600 or not set(rates.columns)=={
        "ust2y_pct","ust10y_pct","tips10y_pct"}:
        raise ValueError("TREASURY_NOMINAL_REAL_HISTORY_INCOMPLETE")
    rates=rates.ffill(limit=3)
    rates["ust2y_delta5_bps"]=100*(rates.ust2y_pct-rates.ust2y_pct.shift(5))
    rates["ust10y_delta5_bps"]=100*(rates.ust10y_pct-rates.ust10y_pct.shift(5))
    rates["tips10y_delta5_bps"]=100*(rates.tips10y_pct-rates.tips10y_pct.shift(5))
    return rates,provenance


def _load_dollar_h1(root):
    files=list(Path(root).rglob("dollaridxusd-h1-bid-*.csv"))
    if len(files)!=7:
        raise ValueError("REQUIRE_SEVEN_INDEPENDENT_DOLLAR_INDEX_YEARS")
    slices=[]
    meta={}
    years=set()
    for p in sorted(files):
        import re
        m=re.search(r"dollaridxusd-h1-bid-(20\d{2})-01-01-",p.name)
        if m is None:
            raise ValueError("BROKER_DOLLAR_INDEX_FILENAME_UNEXPECTED:"+p.name)
        year=int(m.group(1))
        if year in years:
            raise ValueError("DOLLAR_INDEX_DUPLICATE_YEAR")
        years.add(year)
        d=pd.read_csv(p)
        if list(d.columns)!=["timestamp","open","high","low","close"]:
            raise ValueError("DOLLAR_BROKER_SOURCE_SCHEMA_CHANGED")
        millis=pd.to_numeric(d.timestamp,errors="raise")
        if (millis<1_400_000_000_000).any() or (millis>1_900_000_000_000).any():
            raise ValueError("DOLLAR_SOURCE_EPOCH_INVALID")
        d["timestamp"]=pd.to_datetime(millis,utc=True,unit="ms")
        d=d[d.timestamp.dt.year==year]
        if not d.timestamp.is_monotonic_increasing or d.timestamp.duplicated().any():
            raise ValueError("DOLLAR_SOURCE_TIMESTAMP_INVALID")
        for k in ("open","high","low","close"):
            d[k]=pd.to_numeric(d[k],errors="raise")
        if len(d)<3500 or not np.isfinite(d[["open","high","low","close"]].to_numpy()).all():
            raise ValueError("DOLLAR_H1_INCOMPLETE_OR_BAD")
        if (d[["open","high","low","close"]]<=0).any().any():
            raise ValueError("DOLLAR_H1_NEGATIVE_PRICE")
        slices.append(d)
        meta[str(year)]={
            "source_filename":p.name,"sha256":sha256(p.read_bytes()).hexdigest(),
            "hourly_rows":len(d),"instrument":"DOLLAR.IDX/USD",
            "vendor":"DUKASCOPY_BID_CFD_QUOTE_NOT_ICE_DXY"}
    if years!=HIST_YEARS:
        raise ValueError("DOLLAR_HISTORY_MISSING_YEARS")
    bars=pd.concat(slices,ignore_index=True).sort_values("timestamp")
    if bars.timestamp.duplicated().any():
        raise ValueError("CROSS_YEAR_USD_DUPLICATE_TIMESTAMP")
    bars["utc_day"]=bars.timestamp.dt.floor("D")
    daily=bars.groupby("utc_day").agg(
        close=("close","last"),hourly_rows=("close","count"),
        high=("high","max"),low=("low","min"))
    daily=daily[(daily.index.dayofweek<5)&
                (daily.hourly_rows>=12)&
                ((daily.high-daily.low)>=0)].copy()
    if len(daily)<1600:
        raise ValueError("DOLLAR_PROXY_DAILY_COVERAGE_INSUFFICIENT")
    daily["duka_dollaridx_5d_pct"]=100*(daily.close/daily.close.shift(5)-1)
    return daily,meta


def align_official_and_dollar(gold,*,treasury_root,dollar_root):
    if (not isinstance(gold.index,pd.DatetimeIndex) or
        gold.index.tz is None or gold.index.has_duplicates or
        not gold.index.is_monotonic_increasing):
        raise ValueError("GOLD_UTC_DAILY_INDEX_REQUIRED")
    gold=gold.copy()
    gold.index=gold.index.tz_convert("UTC")
    rate,proof_treasury=_read_official_treasury(treasury_root)
    dollar,proof_dollar=_load_dollar_h1(dollar_root)
    # Gold OHLC closes at the END of its 00:00-24:00 UTC date.
    # Decisions occur at or AFTER the closing midnight.
    decision=gold.index+pd.Timedelta(days=1)
    out=gold.copy()
    for name,source,age_max in (
        ("ust2y_delta5_bps",rate,10),
        ("ust10y_delta5_bps",rate,10),
        ("tips10y_delta5_bps",rate,10),
        ("duka_dollaridx_5d_pct",dollar,7),
    ):
        signal=source[name].dropna()
        # No claim this is the *actual* publication timestamp:
        # 2-calendar-day delay from observation date is an explicit
        # conservative retrospective protocol, not original receipt.
        available=signal.index+pd.Timedelta(days=2)
        records=pd.DataFrame({
            "available_at_assumed":available,
            "signal":signal.to_numpy(dtype=float),
        }).sort_values("available_at_assumed")
        lookup=pd.DataFrame({"decision_at":decision})
        aligned=pd.merge_asof(
            lookup,records,left_on="decision_at",
            right_on="available_at_assumed",direction="backward")
        age=(aligned.decision_at-aligned.available_at_assumed).dt.total_seconds()/86400
        out[name]=np.where(age<=age_max,aligned.signal.to_numpy(),np.nan)
    # True original receipt is UNKNOWN; certified R7 execution remains WAIT.
    out.attrs["macro_contract"]=CONTRACT
    out.attrs["macro_release_clock_verified"]=False
    out.attrs["ice_dxy_verified"]=False
    out.attrs["original_vendor_bid_ask_execution_verified"]=False
    return out,{
        "contract":CONTRACT,
        "treasury":proof_treasury,"dollar":proof_dollar,
        "2024_atom_updated_is_historical_release_time":False,
        "2calendar_day_issuer_source_lag_assumed_not_actual":True,
        "gold_decision_clock":"NEXT_UTC_MIDNIGHT_AFTER_DAILY_CLOSE",
        "broker_usdx_proxy_not_ICE_DXY":True,
        "historical_original_publication_timestamps_verified":False,
        "read_only":True,
    }
