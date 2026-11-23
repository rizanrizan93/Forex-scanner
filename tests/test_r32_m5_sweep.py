"""R32 source and causal M5 sweep tests (synthetic fixtures, NOT results)."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import r32_m5_source as source
import r32_liquidity_sweep_m5_events as replay


def synthetic_year(tmp_path,year=2019):
    dates=[]
    for month in range(1,13):
        first=pd.Timestamp(f"{year}-{month:02d}-01",tz="UTC")
        start=first+pd.Timedelta(days=(7-first.dayofweek)%7)
        dates.extend(pd.date_range(start,periods=900,freq="5min"))
    dates=pd.DatetimeIndex(dates)
    price=1500+np.sin(np.arange(len(dates))/13.)*1.2
    f=pd.DataFrame({
        "timestamp":dates.asi8//1_000_000,
        "open":price,"high":price+.5,"low":price-.5,"close":price+.03,
    })
    p=tmp_path/"m5.csv";f.to_csv(p,index=False)
    return p


def test_dukascopy_m5_source_requires_months_and_removes_weekends(tmp_path):
    raw=synthetic_year(tmp_path)
    f,audit=source.normalize(raw,2019,asof=pd.Timestamp("2020-01-01",tz="UTC"))
    assert len(audit["months"])==12
    assert (f.index.dayofweek<5).all()
    assert audit["trading_session_rows"]==len(f)
    assert f.index.is_monotonic_increasing and f.index.is_unique


def test_dukascopy_duplicate_or_bad_ohlc_fail_closed(tmp_path):
    p=synthetic_year(tmp_path)
    d=pd.read_csv(p)
    d.loc[1,"timestamp"]=d.loc[0,"timestamp"]
    d.to_csv(p,index=False)
    with pytest.raises(ValueError,match="TIMESTAMP_INVALID"):
        source.normalize(p,2019,asof=pd.Timestamp("2020-01-01",tz="UTC"))
    p=synthetic_year(tmp_path);d=pd.read_csv(p)
    d.loc[2,"low"]=d.loc[2,"high"]+100
    d.to_csv(p,index=False)
    with pytest.raises(ValueError,match="PRICE_GEOMETRY"):
        source.normalize(p,2019,asof=pd.Timestamp("2020-01-01",tz="UTC"))


def test_m5_source_tf_bars_are_closed_only():
    ix=pd.date_range("2024-03-11",periods=26,freq="5min",tz="UTC")
    d=pd.DataFrame({"o":2000.,"h":2001.,"l":1999.,"c":2000.},index=ix)
    q=replay.source_tf(d,"H1")
    assert len(q)==2
    assert q.closed_at.iloc[-1]==pd.Timestamp("2024-03-11T02:00:00Z")
    assert q.closed_at.iloc[-1]<=ix[-1]+pd.Timedelta(minutes=5)


def test_m5_rejection_uses_completed_bar_and_mss_uses_prior_high():
    o=np.array([100.,100.,100.,100.,100.])
    h=np.array([102.,102.,102.,104.,105.])
    l=np.array([99.,99.,99.,99.,99.])
    c=np.array([100.,100.,100.,103.,103.])
    x=replay.confirm_m5(o,h,l,c,2,5,1,98.,101.,"REJECTION")
    assert x==3
    y=replay.confirm_m5(o,h,l,c,2,5,1,98.,101.,"MSS")
    assert y is None or y>=4


def test_barrier_simulation_stop_first_and_weekend_censor():
    ix=pd.date_range("2025-01-06",periods=500,freq="5min",tz="UTC")
    d=pd.DataFrame({"o":100.,"h":101.,"l":99.,"c":100.},index=ix)
    ev=pd.DataFrame([{"entry_index":10,"entry":100.,"side":1,
                      "stop":99.5,"risk":.5}])
    out=replay.outcomes(d,ev)
    assert out.loc[0,"pnl_0"]==pytest.approx(-.5-replay.COST)
    assert out.loc[0,"exit_at_0"]!=""
    assert out["pnl_0"].notna().all()
    d2=d.copy();ix2=ix.copy()
    ix2=ix2.where(ix2<ix2[11],ix2+pd.Timedelta(hours=2))
    d2.index=ix2
    assert np.isnan(replay.outcomes(d2,ev).loc[0,"pnl_0"])


def test_no_fake_trade_if_source_has_no_sweep():
    ix=pd.date_range("2024-01-08",periods=1200,freq="5min",tz="UTC")
    d=pd.DataFrame({"o":100.,"h":101.,"l":99.,"c":100.},index=ix)
    assert replay.make_events(d,"H1",2024).empty
