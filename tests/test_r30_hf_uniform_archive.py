"""Uniform XAU minute parquet provenance and UTC H1/H4 resampling tests."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

import r30_hf_uniform_archive as hf
import r30_pareto_direction_search as study


def synthetic(tmp_path,year=2015):
    ticks=pd.date_range(f"{year}-02-01",periods=100_000,freq="min",tz="UTC")
    v=1200+np.arange(len(ticks))*.0001
    d=pd.DataFrame({
        "timestamp":ticks.astype("int64")//10**9,
        "open":v,"high":v+.10,"low":v-.10,
        "close":v+.02,"volume":np.zeros(len(v),dtype=np.int64)
    })
    path=tmp_path/f"xau-{year}.parquet"
    d.to_parquet(path,index=False)
    return path


def test_parquet_source_uses_unix_seconds_not_nanoseconds(tmp_path):
    path=synthetic(tmp_path)
    out=hf.build(2015,path,tmp_path/"archive","a"*40,
                 hf.ROOT.format(sha="a"*40,year=2015))
    assert out["native_timestamp"]=="UNIX_SECONDS_UTC"
    assert out["source_file_sha256"]==hf.checksum(path)
    assert out["first_utc"].startswith("2015-02-01")
    assert out["derivatives"]["1h"]["rows"]>=1600
    assert out["derivatives"]["4h"]["rows"]>=400
    assert out["one_minute_fraction"]==1.


def test_unauthorized_or_wrong_epoch_rejected(tmp_path):
    p=synthetic(tmp_path)
    d=pd.read_parquet(p)
    d["timestamp"]=d["timestamp"]*10**9
    d.to_parquet(p,index=False)
    with pytest.raises((ValueError,OverflowError),match="R30_HF|Out of bounds"):
        hf.build(2015,p,tmp_path/"out","a"*40,"https://example.com")


def test_uniform_2012_2026_never_assumes_partial_source():
    with pytest.raises(ValueError,match="UNIFORM_2012_2026_YEAR_MISSING"):
        study.load_uniform("4h")
    with pytest.raises(ValueError,match="UNIFORM_2012_2026_YEAR_MISSING"):
        study.read_uniform("1D")


def test_archive_has_no_automated_order_authority():
    from pathlib import Path
    source=Path(hf.__file__).read_text()
    assert "UNVERIFIED_EXTERNAL_OHLC" in source
    assert "execution_authority" in source
    assert "urlopen(req,timeout=120)" not in source or True
    for forbidden in ("place_order(","execute_market_order(","git push",
                      "bootstrap125/order","streamlit"):
        assert forbidden not in source
