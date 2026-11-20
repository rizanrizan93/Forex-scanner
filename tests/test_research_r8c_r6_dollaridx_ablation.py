"""R8-C synthetic integrity tests; NOT a real historical replay."""
import hashlib,json
import pandas as pd
import pytest
from scripts.research_r8c_r6_dollaridx_ablation import verified_events,evaluate

def ledger(tmp_path):
    p=tmp_path/"events.csv";m=tmp_path/"events.json"
    pd.DataFrame([dict(event_at="2024-01-02T12:00:00Z",side="BUY",
         horizon_minutes=60,net_delta_usd=1.5,year=2024)]).to_csv(p,index=False)
    m.write_text(json.dumps(dict(sha256_csv=hashlib.sha256(p.read_bytes()).hexdigest(),
         source_contract="RIZAN_XAU_M5_SWEEP_MSS_R6",
         label_recipe="NEXT_M1_OPEN_TO_HORIZON_CLOSE_COST_INCLUDED",
         cost_usd_oz=0.5)))
    return p,m

def test_verified_r6_ledger_contract(tmp_path):
    p,m=ledger(tmp_path)
    e,meta=verified_events(p,m)
    assert len(e)==1 and meta["rows"]==1

def test_tampered_r6_ledger_rejected(tmp_path):
    p,m=ledger(tmp_path)
    p.write_text(p.read_text().replace("1.5","10.5"))
    with pytest.raises(ValueError,match="PROVENANCE"):
        verified_events(p,m)

def test_unverified_cost_or_label_rejected(tmp_path):
    p,m=ledger(tmp_path)
    v=json.loads(m.read_text());v["cost_usd_oz"]=0
    m.write_text(json.dumps(v))
    with pytest.raises(ValueError,match="COST"):
        verified_events(p,m)

def test_year_mismatch_rejected(tmp_path):
    p,m=ledger(tmp_path)
    p.write_text(p.read_text().replace(",2024\n",",2025\n"))
    v=json.loads(m.read_text());v["sha256_csv"]=hashlib.sha256(p.read_bytes()).hexdigest()
    m.write_text(json.dumps(v))
    with pytest.raises(ValueError,match="YEAR"):
        verified_events(p,m)

def test_empty_macro_is_not_counted_as_valid_direction():
    idx=pd.date_range("2024-01-02T11:58:00Z",periods=2,freq="min")
    d=pd.DataFrame(dict(timestamp=idx,available_at=idx+pd.Timedelta(minutes=1),
                        open=[100,100],high=[100,100],low=[100,100],close=[100,100]))
    events=pd.DataFrame([dict(event_at="2024-01-02T12:00:00Z",side="BUY",
                         horizon_minutes=60,net_delta_usd=1.5,year=2024)])
    out=evaluate(d,events)
    r=[x for x in out["results"] if x["year"]==2024 and x["horizon"]==60 and x["side"]=="BUY"]
    assert next(x for x in r if x["cohort"]=="BASELINE_ALL")["n"]==1
    assert next(x for x in r if x["cohort"]=="DXY_ALIGNED")["n"]==0
