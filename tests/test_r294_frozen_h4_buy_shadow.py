"""R29.4 H4 BUY frozen research: cannot trade or forge parity."""
import copy
from datetime import UTC,datetime,timedelta

import numpy as np
import pandas as pd
import pytest

import r294_frozen_h4_buy_shadow as frozen


NOW=pd.Timestamp("2026-11-23T12:24:00+00:00")


def test_frozen_r292_2026_policy_from_exact_archived_artifact():
    d=frozen.verify_lock()
    assert d["source_json_sha256"]==frozen.ARTIFACT_SHA
    assert frozen.POLICY=={
        "model":"ridge","group":"broad_context",
        "threshold":.54,"gate":"trend_impulse",
    }
    assert frozen.VAL2025=={"n":63,"correct":41}
    assert frozen.EVAL2026=={"n":23,"correct":14}
    assert frozen.POOLED=={"n":126,"correct":79}
    assert d["aggregate"]["all_strategy_gates_passed"] is False


class FakeModel:
    def __init__(self,score):self.score=score
    def predict_proba(self,x):
        return np.array([[1-self.score,self.score] for _ in x])


@pytest.mark.parametrize("score,gate,expected,reason",[
    (.55,True,"BUY","H4_BUY_FROZEN_R292_TRIGGER"),
    (.53,True,"WAIT","BELOW_THRESHOLD_OR_GATE"),
    (.58,False,"WAIT","BELOW_THRESHOLD_OR_GATE"),
])
def test_live_signal_requires_frozen_score_and_gate(
    monkeypatch,tmp_path,score,gate,expected,reason
):
    monkeypatch.setattr(frozen,"OUTPUT",tmp_path/"r294-h4-buy-shadow.json")
    monkeypatch.setattr(frozen,"verified_refit",lambda:(
        FakeModel(score),{
            "status":"PASS",
            "feature_columns":["frozen_feature"],
            "evidence_sha256":frozen.ARTIFACT_SHA,
        }
    ))
    index=pd.date_range("2026-11-22T04:00:00+00:00",periods=9,freq="4h")
    d=pd.DataFrame({"c":[3620.+i for i in range(len(index))]},index=index)
    z=pd.DataFrame({"test":np.ones(len(index))},index=index)
    closed=pd.Timestamp("2026-11-23T12:00:00+00:00")
    target=pd.Timestamp("2026-11-23T16:00:00+00:00")
    monkeypatch.setattr(frozen,"broker_latest",lambda now:(
        d,z,{"as_of":(now-pd.Timedelta(seconds=20)).isoformat()},
        closed,target
    ))
    monkeypatch.setattr(frozen.r292,"feature_groups",
                        lambda tf,d,z:{"broad_context":pd.DataFrame(
                            {"frozen_feature":np.ones(len(d))},index=d.index)})
    monkeypatch.setattr(frozen.r292,"gates",
                        lambda tf,z,times,side:{"trend_impulse":np.array(
                            [False]*(len(z)-1)+[gate])})
    x=frozen.run(now=NOW)
    assert x["direction"]==expected
    assert x["reason"]==reason
    assert x["execution_authority"] is False
    assert x["execution_influence"] is False
    assert x["forward_validated"] is False
    assert x["target_close_at"]==target.isoformat()
    assert frozen.OUTPUT.is_file()


def test_cannot_extend_2026_training_to_2027(monkeypatch):
    monkeypatch.setattr(frozen,"verified_refit",
                        lambda:(_ for _ in ()).throw(AssertionError("must gate first")))
    with pytest.raises(ValueError,match="NOT_BEEN_REVALIDATED"):
        frozen.run(now=pd.Timestamp("2027-01-05T12:00:00+00:00"))


def test_invalid_model_and_live_feature_schema_fail_closed(monkeypatch,tmp_path):
    monkeypatch.setattr(frozen,"OUTPUT",tmp_path/"frozen.json")
    monkeypatch.setattr(frozen,"verified_refit",lambda:(
        FakeModel(.90),{"status":"PASS","feature_columns":["different_feature"],
                        "evidence_sha256":frozen.ARTIFACT_SHA}
    ))
    idx=pd.date_range("2026-11-22",periods=9,freq="4h",tz="UTC")
    d=pd.DataFrame({"c":np.ones(len(idx))},index=idx)
    z=pd.DataFrame(index=idx)
    monkeypatch.setattr(frozen,"broker_latest",lambda now:(
        d,z,{"as_of":now.isoformat()},
        pd.Timestamp("2026-11-23T12:00:00+00:00"),
        pd.Timestamp("2026-11-23T16:00:00+00:00")))
    monkeypatch.setattr(frozen.r292,"feature_groups",
                        lambda *a:{"broad_context":pd.DataFrame(
                            {"wrong_feature":np.ones(len(d))},index=idx)})
    with pytest.raises(ValueError,match="FEATURE_SCHEMA"):
        frozen.run(now=NOW)
    assert not frozen.OUTPUT.exists()


def test_no_live_orders_or_cbot_mutation():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r294_frozen_h4_buy_shadow.py").read_text()
    assert "read_m1(now=now)" in s
    for forbidden in ("place_order(","execute_market_order(",
                      "git push","bootstrap125/order","create_order(",
                      "streamlit"):
        assert forbidden not in s
