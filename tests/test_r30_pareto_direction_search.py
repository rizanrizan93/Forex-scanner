"""R30 accuracy/frequency Pareto must stay on prior-year outcome and true n."""
import numpy as np
import pytest
from r30_pareto_direction_search import (
    choose,selection_metrics,aggregate,frontier,load_intraday,
    THRESHOLDS,COST,CONTRACT
)


def row(n,accuracy,mean,half=None,coverage=None,key=("x","ridge","all",.53)):
    correct=int(round(n*accuracy))
    return {"key":key,"validation":{
        "n":n,"correct":correct,"accuracy":correct/max(1,n),
        "wilson":float(accuracy)-.09,
        "coverage":coverage if coverage is not None else n/2000,
        "net_mean_usd_oz":mean,
        "half_year":half if half is not None else [n//2,n-n//2],
    }}


def test_frequency_maximizes_n_subject_to_validation_quality():
    rows=[
        row(48,.9,1.2,key=("x","ridge","all",.56)),
        row(170,.60,1.0,key=("y","hgb","all",.50)),
        row(210,.56,1.0,key=("z","ridge","all",.53)),
        row(190,.61,-2.3,key=("b","ridge","all",.50)),
    ]
    freq=choose(rows,"frequency","4h")
    assert freq["validation"]["n"]==170
    precision=choose(rows,"precision","4h")
    assert precision["validation"]["n"]==48
    balance=choose(rows,"balanced","4h")
    assert balance is not None


def test_tiny_perfect_precision_and_negative_net_excluded():
    rows=[row(5,1.,8.),row(60,.7,-.1),row(80,.52,.5)]
    assert choose(rows,"precision","4h")["validation"]["n"]==80
    assert choose(rows,"frequency","4h") is None


def test_no_future_outcome_in_candidate_ranking():
    rows=[row(100,.62,.8),row(80,.65,1.1)]
    a=choose(rows,"balanced","4h")
    # Both contain only the previous-year validation report;
    # evaluation fields must not enter the ranker or its input.
    rows[0]["evaluation_forbidden"]={"correct":0,"n":100}
    rows[1]["evaluation_forbidden"]={"correct":80,"n":80}
    assert choose(rows,"balanced","4h") is a


def test_accuracy_sample_return_metrics_and_half_year():
    y=np.array([1,1,0,0,1],dtype=int)
    mask=np.array([1,1,0,0,1],dtype=bool)
    d=np.array([2.,2.,-2.,-3.,2.],dtype=float)
    months=np.array([1,2,4,6,8])
    r=selection_metrics(y,mask,"BUY",d,months)
    assert r["n"]==3 and r["correct"]==3
    assert r["coverage"]==.6
    assert r["net_mean_usd_oz"]==pytest.approx(2-COST)
    assert r["half_year"]==[2,1]


def test_non_dominated_accuracy_and_frequency_both_survive():
    base={"mode":"precision","BUY":{"n":100,"accuracy":.66,
           "net_mean_after_assumed_cost_usd_oz":.75},
          "SELL":{"n":80,"accuracy":.64,
           "net_mean_after_assumed_cost_usd_oz":.4}}
    freq={"mode":"frequency","BUY":{"n":230,"accuracy":.59,
           "net_mean_after_assumed_cost_usd_oz":.5},
          "SELL":{"n":180,"accuracy":.59,
           "net_mean_after_assumed_cost_usd_oz":.6}}
    dominated={"mode":"balanced","BUY":{"n":70,"accuracy":.5,
           "net_mean_after_assumed_cost_usd_oz":.1},
          "SELL":{"n":50,"accuracy":.5,
           "net_mean_after_assumed_cost_usd_oz":.1}}
    got=frontier([base,freq,dominated])
    assert got["BUY"]==["precision","frequency"]
    assert got["SELL"]==["precision","frequency"]


def test_full_2012_2026_h1_h4_cannot_be_falsely_claimed(monkeypatch):
    import r30_pareto_direction_search as r30
    monkeypatch.setattr(r30.glob,"glob",lambda path:[])
    with pytest.raises(ValueError,match="FULL_2012_2026_NOT_AVAILABLE"):
        load_intraday("4h","full")


def test_research_only_no_broker_order_calls():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r30_pareto_direction_search.py").read_text()
    assert "FULL_2012_2026_NOT_AVAILABLE" in s
    assert "base.split_masks(times,usable,year,window=6)" in s
    for forbidden in ("place_order(","execute_market_order(","bridge/order",
                      "git push","streamlit","modify_position("):
        assert forbidden not in s
