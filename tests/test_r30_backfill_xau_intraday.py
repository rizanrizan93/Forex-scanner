"""R30 resample must prove original HistData SHA and closed H1/H4 only."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from r30_backfill_xau_intraday import build,checksum,CONTRACT


def create(tmp_path,year=2016):
    index=pd.date_range(f"{year}-01-03 00:00:00+00:00",periods=60_000,freq="min")
    n=len(index)
    values=1100+np.arange(n,dtype=float)*.001
    frame=pd.DataFrame({
        "timestamp":index.strftime("%Y-%m-%d %H:%M:%S%z"),
        "open":values,"high":values+.04,"low":values-.04,"close":values+.01
    })
    file=tmp_path/"m1.csv"
    frame.to_csv(file,index=False)
    prov={
        "year":year,"contract":"XAU_HISTDATA_M1_SHARD_V193_1",
        "source":"HISTDATA_XAUUSD_M1",
        "source_timestamp_contract":"FIXED_EST_UTC_MINUS5_NO_DST",
        "normalized_csv_sha256":checksum(file),
        "provider_commit":"4a3c11b67f97758f6e3f77a3e5905b6aa87367b8",
        "failed_periods":[],"execution_authority":False
    }
    source=tmp_path/"source.json"
    source.write_text(json.dumps(prov))
    return file,source


def test_year_h1_h4_shards_and_independent_provenance(tmp_path):
    file,prov=create(tmp_path)
    out=build(file,prov,tmp_path/"result",2016)
    assert out["contract"]==CONTRACT
    assert out["year"]==2016
    assert out["shards"]["1h"]["rows"]==1000
    assert out["shards"]["4h"]["rows"]==250
    for tf,info in out["shards"].items():
        path=tmp_path/"result"/info["file"]
        assert info["sha256"]==checksum(path)
        q=pd.read_csv(path,index_col=0,parse_dates=True)
        assert q.index.year.max()==2016
        assert (q.h>=q[["o","c"]].max(axis=1)).all()
        assert (q.l<=q[["o","c"]].min(axis=1)).all()


def test_tampered_original_m1_or_future_year_refused(tmp_path):
    f,prov=create(tmp_path)
    q=json.loads(prov.read_text())
    q["normalized_csv_sha256"]="0"*64
    prov.write_text(json.dumps(q))
    with pytest.raises(ValueError,match="SOURCE_NOT_PROVEN"):
        build(f,prov,tmp_path/"result",2016)
    q["normalized_csv_sha256"]=checksum(f)
    prov.write_text(json.dumps(q))
    with pytest.raises(ValueError,match="SOURCE_NOT_PROVEN"):
        build(f,prov,tmp_path/"result",2024)
