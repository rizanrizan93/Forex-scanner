"""Dukascopy normalization contract, synthetic fixtures never market claims."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from r30_duka_h1_h4_shard import normalize


def synthetic_csv(tmp_path):
    ix=[]
    for month in range(1,13):
        ix.extend(pd.date_range(f"2012-{month:02d}-02",periods=250,
                                freq="h",tz="UTC"))
    f=pd.DataFrame({
        "timestamp":[int(x.timestamp()*1000) for x in ix],
        "open":[1740.]*len(ix),"high":[1741.]*len(ix),
        "low":[1739.]*len(ix),"close":[1740.2]*len(ix),
    })
    p=tmp_path/"duka.csv";f.to_csv(p,index=False)
    return p


def test_dukascopy_h1_to_h4_requires_closed_four_hour_candles(tmp_path):
    p=synthetic_csv(tmp_path)
    h1,h4,months,session=normalize(p,2012,now=pd.Timestamp("2013-01-01",tz="UTC"))
    assert 1500<len(h1)<3000\n    assert session["weekend_filtered"]>0\n    assert session["tradable_h1"]==len(h1)\n    assert (h1.index.dayofweek<5).all()
    assert len(months)==12 and all(n>=120 for n in months.values())
    assert len(h4)>=400
    assert all(h4.index.hour%4==0)
    assert h4.index.tz is not None
    assert set(h4.columns)=={"o","h","l","c"}


def test_dukascopy_invalid_and_duplicate_prices_fail_closed(tmp_path):
    p=synthetic_csv(tmp_path)
    d=pd.read_csv(p)
    d.loc[2,"timestamp"]=d.loc[1,"timestamp"]
    d.to_csv(p,index=False)
    with pytest.raises(ValueError,match="DUKA_TIMESTAMP_INVALID"):
        normalize(p,2012,now=pd.Timestamp("2013-01-01",tz="UTC"))
    p=synthetic_csv(tmp_path)
    d=pd.read_csv(p)
    d.loc[4,"high"]=1700
    d.to_csv(p,index=False)
    with pytest.raises(ValueError,match="DUKA_OHLC_INVALID"):
        normalize(p,2012,now=pd.Timestamp("2013-01-01",tz="UTC"))


def test_dukascopy_missing_month_is_not_filled_synthetically(tmp_path):
    p=synthetic_csv(tmp_path)
    d=pd.read_csv(p)
    d=d.iloc[:250*9]
    d.to_csv(p,index=False)
    with pytest.raises(ValueError,match="DUKA_YEAR_MONTH_COVERAGE_INSUFFICIENT"):
        normalize(p,2012,now=pd.Timestamp("2013-01-01",tz="UTC"))
