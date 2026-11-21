"""R7.3 research-only lagged Fed/FOMC-rate, yield, VIX, official CFTC panel.

Explicitly NOT an archived intraday-PIT dataset. FRED is *latest-vintage*,
Treasury observation dates are not original publication times, and
CFTC reports may have been delayed beyond the conservative 14d lag.
No full FOMC statement hawkish/dovish NLP, CME FedWatch futures-based
probabilities, true surprise rate, COMEX DOM, or actual liquidation tape.

All features are computed from source observations and retrospectively
assumed releases AFTER their observation date. Production remains WAIT.
"""
from __future__ import annotations
from pathlib import Path
from io import BytesIO
import hashlib,json,zipfile
import numpy as np
import pandas as pd
from .fed_r71_official_treasury_dollar import _read_official_treasury

CONTRACT="RIZAN_R73_FED_POLICY_RATE_PATH_COT_RISK_LATEST_VINTAGE_V1"
YEARS=tuple(range(2018,2025))
RATES=("DFEDTARU","DFEDTARL","VIXCLS")
POLICY_COLUMNS=(
    "fed_target_mid_pct",
    "fed_target_change_14d_bps",
    "fed_path_spread_proxy_bp",
    "fed_path_repricing_proxy_5d_bps",
)
COT_COLUMNS=(
    "cot_gold_mmanaged_net_oi_pct",
    "cot_gold_mmanaged_net_week_change_pct",
    "cot_gold_open_interest_week_pct",
)
RISK_COLUMNS=("vix_level_lagged","vix_5obs_change_pct")
FEATURES=POLICY_COLUMNS+COT_COLUMNS+RISK_COLUMNS


def _read_archived_fred(root):
    root=Path(root)
    d=[]
    proofs={}
    for series in RATES:
        label={
            "DFEDTARU":"FRED_TARGET_UPPER.csv",
            "DFEDTARL":"FRED_TARGET_LOWER.csv",
            "VIXCLS":"FRED_VIX.csv",
        }[series]
        p=root/label
        if not p.is_file():raise ValueError("MISSING_FRED_SOURCE:"+label)
        blob=p.read_bytes()
        if not 20000<len(blob)<1_000_000:
            raise ValueError("INVALID_FRED_SOURCE_LENGTH:"+label)
        frame=pd.read_csv(BytesIO(blob))
        if not {"observation_date",series}.issubset(frame.columns):
            raise ValueError("FRED_SOURCE_SCHEMA_CHANGED:"+series)
        dates=pd.to_datetime(frame.observation_date,utc=True,errors="raise")
        if dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise ValueError("UNSORTED_OR_DUPLICATE_FRED_SOURCE:"+series)
        values=pd.to_numeric(frame[series],errors="coerce")
        s=pd.Series(values.to_numpy(dtype=float),index=pd.DatetimeIndex(dates),
                    name=series)
        if int(s.notna().sum())<2000:
            raise ValueError("FRED_HISTORY_TOO_SHORT:"+series)
        d.append(s)
        proofs[series]={
            "file":label,"sha256":hashlib.sha256(blob).hexdigest(),
            "latest_vintage_used":True,
            "original_historical_release_timestamp_verified":False,
            "source_observations":int(s.notna().sum()),
        }
    frame=pd.concat(d,axis=1).sort_index()
    frame=frame.loc[(frame.index.year>=2017)&(frame.index.year<=2024)]
    if len(frame)<2200:raise ValueError("FED_VIX_SOURCE_INCOMPLETE_2018_24")
    frame["target_mid"]=(frame.DFEDTARU+frame.DFEDTARL)/2.0
    # Event effective-date change observed over last 14 CALENDAR days,
    # NOT a surprise to pre-meeting futures. Missing unchanged-meeting
    # statements and dot-plot reactions remain a known omission.
    frame["target_change_14d_bps"]=(
        100*(frame.target_mid-frame.target_mid.shift(14)))
    vix=frame.VIXCLS.dropna()
    frame["vix_change_5obs_pct"]=100*(vix/vix.shift(5)-1)
    return frame,proofs


def _load_cftc_gold_futures_only(root):
    files=sorted(Path(root).rglob("cftc-gold-disagg-futures-only-20??.zip"))
    years=set()
    panels=[]
    audit={}
    for p in files:
        year=int(p.stem[-4:])
        if year in years:raise ValueError("CFTC_DUPLICATE_YEAR")
        years.add(year)
        meta_path=p.with_suffix(".json")
        if not meta_path.is_file():
            raise ValueError("CFTC_YEAR_PROVENANCE_MISSING")
        meta=json.loads(meta_path.read_text())
        blob=p.read_bytes()
        if (int(meta.get("year",0))!=year or
            meta.get("official_gold_contract_code")!="088691" or
            meta.get("raw_zip_sha256")!=hashlib.sha256(blob).hexdigest()):
            raise ValueError("CFTC_SOURCE_HASH_CHANGED")
        with zipfile.ZipFile(BytesIO(blob)) as z:
            names=[q for q in z.namelist() if q.lower().endswith((".txt",".csv"))]
            if len(names)!=1:raise ValueError("CFTC_ZIP_SCHEMA_CHANGED")
            raw=z.read(names[0])
        if hashlib.sha256(raw).hexdigest()!=meta.get("csv_sha256"):
            raise ValueError("CFTC_CSV_HASH_MISMATCH")
        allrows=pd.read_csv(BytesIO(raw),low_memory=False)
        required={
            "CFTC_Contract_Market_Code","Report_Date_as_YYYY-MM-DD",
            "M_Money_Positions_Long_All","M_Money_Positions_Short_All",
            "Open_Interest_All"}
        if not required.issubset(allrows.columns):
            raise ValueError("CFTC_REQUIRED_COLUMNS_MISSING")
        gold=allrows[
            allrows.CFTC_Contract_Market_Code.astype(str).str.strip()=="088691"
        ].copy()
        gold["reported_at"]=pd.to_datetime(
            gold["Report_Date_as_YYYY-MM-DD"],utc=True,errors="raise")
        if (len(gold)<45 or len(gold)>75 or
            gold.reported_at.duplicated().any() or
            not (gold.reported_at.dt.year==year).all()):
            raise ValueError("CFTC_INVALID_GOLD_WEEKLY_REPORT")
        gold=gold.sort_values("reported_at")
        for k in ("Open_Interest_All","M_Money_Positions_Long_All",
                  "M_Money_Positions_Short_All"):
            gold[k]=pd.to_numeric(gold[k],errors="raise")
        if (gold.Open_Interest_All<=0).any():
            raise ValueError("INVALID_CFTC_OPEN_INTEREST")
        gold["managed_net_oi_pct"]=100*(
            gold.M_Money_Positions_Long_All-
            gold.M_Money_Positions_Short_All)/gold.Open_Interest_All
        gold["oi_all"]=gold.Open_Interest_All
        panels.append(gold[["reported_at","managed_net_oi_pct","oi_all"]])
        audit[str(year)]={
            "raw_zip_sha256":meta["raw_zip_sha256"],
            "reported_gold_weeks":int(len(gold)),
            "exact_original_friday_release_clock_verified":False,
        }
    if years!=set(YEARS):
        raise ValueError("CFTC_MISSING_REQUIRED_2018_24_YEAR:"+str(sorted(set(YEARS)-years)))
    cot=pd.concat(panels).sort_values("reported_at")
    if cot.reported_at.duplicated().any():
        raise ValueError("CFTC_CROSS_YEAR_DUPLICATE_WEEK")
    cot=cot.set_index("reported_at")
    cot["managed_net_week_delta_pct"]=cot.managed_net_oi_pct.diff()
    cot["open_interest_week_change_pct"]=100*(cot.oi_all/cot.oi_all.shift(1)-1)
    return cot,audit


def _align_asof(decisions,values,*,lag_days,max_age_days):
    # Dates: daily calendar observation. "available_at" is an explicit
    # RETROSPECTIVE ASSUMPTION not an original verified release clock.
    x=values.replace([np.inf,-np.inf],np.nan).dropna().sort_index()
    if x.empty:raise ValueError("EMPTY_HISTORICAL_FACTOR")
    if not isinstance(x.index,pd.DatetimeIndex) or x.index.tz is None:
        raise ValueError("TIMEZONE_AWARE_SOURCE_OBSERVATIONS_REQUIRED")
    releases=pd.DataFrame({
        "asof_available_at":x.index+pd.Timedelta(days=lag_days),
        "value":x.to_numpy(dtype=float)})
    lookup=pd.DataFrame({"decision_at":decisions})
    matched=pd.merge_asof(lookup,releases,left_on="decision_at",
                          right_on="asof_available_at",direction="backward")
    age=(matched.decision_at-matched.asof_available_at).dt.total_seconds()/86400
    return np.where(age<=max_age_days,matched.value.to_numpy(),np.nan)


def align_fed_policy_cot_risk(gold_panel,*,fred_root,cftc_root,treasury_root):
    """Return panel with separately source-hashed macro factor features.

    Decision clock is NEXT UTC midnight after a *completed* UTC gold
    daily session. All source availability is assumed with multi-day
    buffers. Cannot be treated as original intraday realtime feed.
    """
    if (not isinstance(gold_panel,pd.DataFrame) or
        not isinstance(gold_panel.index,pd.DatetimeIndex) or
        gold_panel.index.tz is None or
        gold_panel.index.has_duplicates or
        not gold_panel.index.is_monotonic_increasing):
        raise ValueError("GOLD_DAILY_UTC_UNIQUE_SORTED_REQUIRED")
    out=gold_panel.copy()
    out.index=out.index.tz_convert("UTC")
    decision=out.index+pd.Timedelta(days=1)
    fred,fred_proof=_read_archived_fred(fred_root)
    treasury,treasury_proof=_read_official_treasury(treasury_root)
    cot,cot_proof=_load_cftc_gold_futures_only(cftc_root)

    mid=_align_asof(decision,fred.target_mid,lag_days=3,max_age_days=9)
    change=_align_asof(decision,fred.target_change_14d_bps,
                       lag_days=3,max_age_days=9)
    ust2=_align_asof(decision,treasury.ust2y_pct,lag_days=2,max_age_days=10)
    out["fed_target_mid_pct"]=mid
    out["fed_target_change_14d_bps"]=change
    out["fed_path_spread_proxy_bp"]=100*(ust2-mid)
    # Paired source-aligned path data only; no interpolation across
    # missing gold days, and no claim of CME implied meeting odds.
    out["fed_path_repricing_proxy_5d_bps"]=(
        out["fed_path_spread_proxy_bp"]-
        out["fed_path_spread_proxy_bp"].shift(5))

    out["vix_level_lagged"]=_align_asof(
        decision,fred.VIXCLS,lag_days=2,max_age_days=10)
    out["vix_5obs_change_pct"]=_align_asof(
        decision,fred.vix_change_5obs_pct,lag_days=2,max_age_days=10)

    # CFTC as-of Tuesday != Friday publication, and 2023 has
    # disrupted releases. 14d post-report lag is a conservative
    # RESEARCH assumption, not verified historical release receipts.
    out["cot_gold_mmanaged_net_oi_pct"]=_align_asof(
        decision,cot.managed_net_oi_pct,lag_days=14,max_age_days=32)
    out["cot_gold_mmanaged_net_week_change_pct"]=_align_asof(
        decision,cot.managed_net_week_delta_pct,lag_days=14,max_age_days=32)
    out["cot_gold_open_interest_week_pct"]=_align_asof(
        decision,cot.open_interest_week_change_pct,
        lag_days=14,max_age_days=32)

    out.attrs["r73_source_contract"]=CONTRACT
    out.attrs["is_original_intraday_pit"]=False
    out.attrs["has_cme_fedwatch_futures_expectations"]=False
    out.attrs["has_fomc_meeting_surprise"]=False
    out.attrs["has_actual_order_book_liquidations"]=False
    return out,{
        "contract":CONTRACT,"source_fred_latest_vintage":fred_proof,
        "source_treasury_observation_not_release":treasury_proof,
        "source_cftc_annual_archives":cot_proof,
        "fed_observation_availability_assumed_lag_calendar_days":3,
        "vix_observation_availability_assumed_lag_calendar_days":2,
        "cftc_tuesday_to_asof_assumed_lag_calendar_days":14,
        "missing_original_historical_fomc_surprise":True,
        "fed_expectation_is_yield_spread_proxy_not_CME_FedWatch":True,
        "liquidity_is_COT_OI_and_VIX_not_actual_forced_liquidations":True,
        "retro_revision_risk":True,
        "source_provenance_independently_received_in_2018_2024":False,
        "2025_2026_labels_used":False,
        "production_authority":False,
    }
