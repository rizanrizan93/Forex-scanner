"""R31B proves dense packed-screen coverage and no order authority."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import research_r31b_dense_coverage as dense


def test_dense_screen_prefers_validation_volume_and_precision():
    valid=np.array([0,1,2,3,4])
    n=np.array([50,100,200,300,80])
    wins=np.array([30,60,110,120,76])
    result=dense.top_indices(valid,n,wins,limit=2,kind="volume")
    assert set(result)=={2,3}
    precision=dense.top_indices(valid,n,wins,limit=1,kind="precision")
    assert precision.tolist()==[4]


def test_full_research_evaluation_count_and_research_only(tmp_path,monkeypatch):
    r31=dense.r31
    d=pd.DataFrame(index=pd.date_range("2012-01-01",periods=1250,freq="5D",tz="UTC"),
                   data={"o":100.,"h":101.,"l":99.,"c":100.})
    events=[]
    for i in range(90,1200,4):
        events.append({
          "formation":i-2,"signal_index":i-1,"entry_index":i,
          "year":d.index[i].year,"side":1,"base":1,
          "displacement":.8,"body":.4,"bos":.3,"width":1.,
          "vol":.6,"retest_lag":2,"rejection":.15,
          "entry":100.,"stop":99.,"risk":1.})
    monkeypatch.setattr(r31.r30,"load",lambda tf:(d,{"synthetic":"yes"}))
    monkeypatch.setattr(r31.r30,"prepare",lambda d:{"synthetic":True})
    monkeypatch.setattr(r31,"events_from_closed_ohlc",lambda d,f,tf:events)
    monkeypatch.setattr(r31,"direction_votes",lambda d,f,e:[
        np.ones(len(e),dtype=bool)]*256)
    monkeypatch.setattr(r31,"zone_axes",lambda e:[
        [np.ones(len(e),dtype=bool)]*4 for _ in range(6)])
    def fake(d,e):
        n=len(e)
        return np.tile(np.where(np.arange(n)%4==0,-1.,2.),(8,1)),np.tile(
            [x["entry_index"]+1 for x in e],(8,1))
    monkeypatch.setattr(r31,"outcome_matrix",fake)
    monkeypatch.setattr(dense,"OUT",tmp_path)
    report=dense.sweep("H1",model_start=0,models=2,caps=4)
    assert report["actual_evaluations"]==64
    assert report["direction_models"]==2
    assert report["frozen_model_parity"] is False
    assert report["execution_authority"] is False
    assert report["scope"].startswith("SAME_R31")
    assert (tmp_path/"r31b-H1-models-0.json").exists()


def test_no_extrapolated_unrun_configurations():
    with pytest.raises(ValueError,match="R31B_INVALID_SCOPE"):
        dense.sweep("H1",model_start=255,models=32,caps=4096)
    with pytest.raises(ValueError,match="R31B_INVALID_SCOPE"):
        dense.sweep("D1",model_start=0,models=32,caps=0)
