"""Frozen winner reproducibility and no-broker-order contracts for R25/R11."""
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import rbest_side_candidates as best


def test_archived_best_side_configs_preserve_original_side_and_policy():
    for tf in ("1h","4h"):
        buy,sell=best.selected(tf)
        assert buy["threshold"]==0.55
        assert sell["tf"]==tf and sell["side"]=="SELL"
        assert sell["training_signal_sha256"] and sell["validation_signal_sha256"]
        assert len(sell["group_choices"])==7
    assert best.selected("1h")[0]["gate"]=="vol_high"
    assert best.selected("4h")[0]["gate"]=="london_open"
    assert best.selected("1h")[1]["config_index"]==127013
    assert best.selected("4h")[1]["config_index"]==1310748


@pytest.mark.parametrize("wantbuy,wantsell,wantdirection,wantreason",[
    (True,False,"BUY","RESEARCH_CANDIDATE_SIGNAL"),
    (False,True,"SELL","RESEARCH_CANDIDATE_SIGNAL"),
    (False,False,"WAIT","NO_SIDE_TRIGGER"),
    (True,True,"WAIT","SIDE_CONFLICT"),
])
def test_two_independent_heads_resolve_without_forced_trade(
    monkeypatch, tmp_path, wantbuy, wantsell, wantdirection, wantreason
):
    monkeypatch.setattr(best,"OUTPUT",tmp_path)
    buy_cfg,sell_cfg=best.selected("1h")
    monkeypatch.setattr(best,"freeze_r25_buy",lambda *args:(
        FakeModel(.60 if wantbuy else .50),
        {"feature_columns":["z"],"parity":"PASS","group":buy_cfg["group"]}
    ))
    monkeypatch.setattr(best,"verify_r11_sell",lambda *args:{"parity":"PASS"})
    observed=pd.Timestamp("2026-11-23T10:22:00+00:00")
    idx=pd.date_range(end="2026-11-23T09:00:00+00:00",periods=10,freq="h")
    d=pd.DataFrame({"c":np.linspace(3600,3610,10)},index=idx)
    z=pd.DataFrame({"c":d.c},index=idx)
    monkeypatch.setattr(best,"live_latest",lambda tf,now:(
        d,z,{"as_of":(now+pd.Timedelta(milliseconds=55)).isoformat()},
        pd.Timestamp("2026-11-23T10:00:00+00:00"),
        pd.Timestamp("2026-11-23T11:00:00+00:00")
    ))
    groups={buy_cfg["group"]:pd.DataFrame({"z":np.ones(10)},index=idx)}
    monkeypatch.setattr(best,"r25_setup",lambda tf,d,z,times,s:(
        groups,{buy_cfg["gate"]:np.full(10,True)},np.ones(10,bool)
    ))
    monkeypatch.setattr(best,"anchor",lambda *args:np.ones(10,bool))
    monkeypatch.setattr(best,"rules",lambda *args:None)
    monkeypatch.setattr(best,"exactmask",lambda *args:np.array(
        [False]*9+[wantsell],dtype=bool))
    x=best.run("1h",now=observed)
    assert x["direction"]==wantdirection
    assert x["reason"]==wantreason
    assert x["sides"]["BUY"]["active"] is wantbuy
    assert x["sides"]["SELL"]["active"] is wantsell
    assert x["research_only"] is True
    assert x["execution_authority"] is False
    assert x["execution_influence"] is False
    # Transport can finish milliseconds after run-start; retain causal stamps.
    assert pd.Timestamp(x["generated_at"]) >= pd.Timestamp(x["observed_at"])


class FakeModel:
    def __init__(self,p):self.p=p
    def predict_proba(self,X):
        return np.array([[1-self.p,self.p]]*len(X))


def test_code_never_opens_order_or_executes_trade():
    src=(Path(__file__).resolve().parents[1]/
         "scripts/rbest_side_candidates.py").read_text()
    assert "place_order(" not in src
    assert "execute_order(" not in src
    assert "create_order(" not in src
    assert "bootstrap125/order" not in src
    assert "read_m1(now=now)" in src
    assert "combine_history(" in src
    assert "R11_SELECTED_TRACE_PARITY_MISMATCH" in src
    assert "R25_VALIDATION_PARITY_MISMATCH" in src
