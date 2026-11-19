"""Synthetic integrity tests only; no claims about real market returns."""
import hashlib,json
import pandas as pd
import pytest
from scripts.research_r8_dollaridx_asof_audit import audit,causal_features

def fixture(tmp_path,delay=0):
    times=pd.date_range("2024-02-05T12:00:00Z",periods=80,freq="min")
    df=pd.DataFrame(dict(timestamp=times.strftime("%Y-%m-%dT%H:%M:%SZ"),
        open=[100+i*.01 for i in range(80)],
        high=[100.02+i*.01 for i in range(80)],
        low=[99.98+i*.01 for i in range(80)],
        close=[100.01+i*.01 for i in range(80)],
        available_at=(times+pd.Timedelta(minutes=1,seconds=delay)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    csv=tmp_path/"dxy.csv";df.to_csv(csv,index=False)
    manifest=tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dict(sha256_csv=hashlib.sha256(csv.read_bytes()).hexdigest(),
        instrument="DOLLARIDXUSD",provider="Dukascopy",timestamp_semantics="M1_OPEN_UTC")))
    return csv,manifest,df

def test_valid_provenance_and_5_15_60_asof(tmp_path):
    csv,manifest,_=fixture(tmp_path)
    d,report=audit(csv,manifest)
    assert report["valid_for_replay"] and report["rows"]==80
    result=causal_features(d,pd.DataFrame({"event_at":["2024-02-05T13:20:00Z"]}))
    assert result.iloc[0]["status"]=="OK"
    assert all(result.iloc[0]["dxy_direction_"+str(m)+"m"]=="UP" for m in (5,15,60))

def test_delayed_publication_excluded(tmp_path):
    csv,manifest,_=fixture(tmp_path,delay=120)
    d,_=audit(csv,manifest)
    result=causal_features(d,pd.DataFrame({"event_at":["2024-02-05T13:20:00Z"]}))
    assert result.iloc[0]["status"]=="STALE_DXY"

def test_sha_tamper_rejected(tmp_path):
    csv,manifest,_=fixture(tmp_path)
    csv.write_text(csv.read_text()+"\n")
    with pytest.raises(ValueError,match="SHA256_MISMATCH"):
        audit(csv,manifest)

def test_missing_minute_never_forward_filled(tmp_path):
    csv,manifest,df=fixture(tmp_path)
    df=df.drop(index=40)
    df.to_csv(csv,index=False)
    info=json.loads(manifest.read_text())
    info["sha256_csv"]=hashlib.sha256(csv.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(info))
    d,report=audit(csv,manifest)
    assert report["missing_minute_transitions"]==1
    assert not report["valid_for_replay"]
    r=causal_features(d,pd.DataFrame({"event_at":["2024-02-05T13:20:00Z"]}))
    assert pd.isna(r.iloc[0]["dxy_direction_60m"])

def test_early_availability_rejected(tmp_path):
    csv,manifest,df=fixture(tmp_path)
    df.loc[1,"available_at"]=df.loc[1,"timestamp"]
    df.to_csv(csv,index=False)
    info=json.loads(manifest.read_text())
    info["sha256_csv"]=hashlib.sha256(csv.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(info))
    with pytest.raises(ValueError,match="LOOKAHEAD"):
        audit(csv,manifest)
