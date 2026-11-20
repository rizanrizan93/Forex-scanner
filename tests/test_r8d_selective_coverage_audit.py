"""Synthetic contract tests only. No XAU accuracy claim."""
import importlib.util
from pathlib import Path
import pytest
P=Path(__file__).resolve().parents[1]/"research/zone_rebound/r8d_selective_coverage_audit.py"
spec=importlib.util.spec_from_file_location("r8d",P)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
SHA="a"*64
def row(event,side="BUY",direction="DOWN",success=True,age=60,year=2023,h="H1"):
    return dict(event_id=event,side=side,dxy_direction=direction,success=success,
        dxy_age_seconds=age,year=year,horizon=h,
        source_sha256=SHA,xau_source_sha256=SHA)

def test_symmetric_inverse_dxy_acceptance_and_coverage():
    data=[row("b"),row("s",side="SELL",direction="UP"),
          row("bw",direction="UP",success=False),
          row("sw",side="SELL",direction="DOWN",success=False)]
    r=mod.audit(data,min_side_n=1)
    assert r["overall"]["H1"]["BUY"]["n"]==1
    assert r["overall"]["H1"]["SELL"]["n"]==1
    assert all(x["coverage_pct"]==50 for x in r["annual_side"])

def test_stale_and_unknown_abstain_not_win():
    data=[row("a",age=121),row("b",age=None),
          row("c",direction="UNAVAILABLE"),row("d",age=120)]
    r=mod.audit(data,min_side_n=1)
    assert r["overall"]["H1"]["BUY"]["n"]==1
    assert r["annual_side"][0]["missing_or_stale_n"]==3

def test_no_fake_accuracy_when_no_rows():
    r=mod.audit([])
    assert r["rows"]==0
    assert not r["overall"]["H1"]["both_sides_pass"]
    assert r["overall"]["H1"]["BUY"]["wilson95"]==[None,None]

def test_reject_duplicate_outcome():
    with pytest.raises(ValueError,match="DUPLICATE"):
        mod.audit([row("same"),row("same")])

def test_reject_missing_provenance():
    x=row("a");x["source_sha256"]=""
    with pytest.raises(ValueError,match="SHA"):
        mod.audit([x])

def test_reject_nonboolean_outcome():
    x=row("a");x["success"]=1
    with pytest.raises(ValueError,match="OUTCOME"):
        mod.audit([x])

def test_reject_future_or_negative_age():
    with pytest.raises(ValueError,match="AGE"):
        mod.audit([row("a",age=-1)])

def test_no_60_claim_from_small_sample():
    data=[row(str(i)) for i in range(20)]
    r=mod.audit(data,min_side_n=100)
    assert r["overall"]["H1"]["BUY"]["gate"]=="INSUFFICIENT_N"
    assert r["annual_side"][0]["accepted_pct"]==100
    assert not r["overall"]["H1"]["both_sides_pass"]
