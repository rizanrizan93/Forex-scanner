"""R6 H1 risk labels use future OHLC only for OUTCOME not signal features."""
import pandas as pd
import pytest
from fx_scanner.fomc_continuation_risk_r6_research import continuation_h1_risk

def prices():
    idx=pd.date_range("2023-09-20T18:00:00Z",periods=110,freq="min",tz="UTC")
    d=pd.DataFrame({"open":100.,"high":100.4,"low":99.6,"close":100.},index=idx)
    return d

def test_simultaneous_target_and_stop_same_m1_counts_as_adverse_buy():
    d=prices()
    d.iloc[11,d.columns.get_loc("high")]=104.
    d.iloc[11,d.columns.get_loc("low")]=96.
    x=continuation_h1_risk(d,10,side="BUY",atr_m5=1.0)
    assert x["status"]=="EVALUATED"
    assert x["target3_vs_adverse3"]=="ADVERSE_FIRST"
    assert x["static_stop_before_target3"] is True
    assert x["max_favorable_excursion_net_usd_oz"]>=3.5
    assert x["max_adverse_excursion_usd_oz"]>=4
    assert not x["authority_to_trade"]

def test_target_first_before_adverse_sell():
    d=prices()
    d.iloc[11,d.columns.get_loc("low")]=96.3
    d.iloc[16,d.columns.get_loc("high")]=104.
    x=continuation_h1_risk(d,10,side="SELL",atr_m5=2.0)
    assert x["target3_vs_adverse3"]=="TARGET_FIRST"
    assert x["static_stop_before_target3"] is False
    assert x["target3_first_minute"]==1
    assert x["adverse3_first_minute"]==6

def test_target_first_before_adverse_buy():
    d=prices()
    d.iloc[11,d.columns.get_loc("high")]=103.7
    d.iloc[16,d.columns.get_loc("low")]=95.0
    x=continuation_h1_risk(d,10,side="BUY",atr_m5=2)
    assert x["target3_vs_adverse3"]=="TARGET_FIRST"
    assert not x["static_stop_before_target3"]

def test_direction_right_while_adverse_barrier_was_hit():
    d=prices()
    d.iloc[11,d.columns.get_loc("low")]=96.
    d.iloc[70,d.columns.get_loc("close")]=105.
    x=continuation_h1_risk(d,10,side="BUY",atr_m5=1)
    assert x["terminal_direction_correct_after_cost"]
    assert x["target3_vs_adverse3"]=="ADVERSE_FIRST"
    assert x["static_stop_before_target3"] is True
    # A favorable terminal close is NOT a safe tradable path.

def test_missing_future_minutes_censors_risk():
    d=prices()
    d=d.drop(d.index[30])
    x=continuation_h1_risk(d,10,side="BUY",atr_m5=2)
    assert x["status"].startswith("CENSORED_")

def test_pre_signal_stop_window_must_be_contiguous():
    d=prices()
    d=d.drop(d.index[9])
    with pytest.raises(ValueError,match="PRE_SIGNAL_M1_GAP"):
        continuation_h1_risk(d,10,side="BUY",atr_m5=2)

def test_no_fake_probabilities_or_live_fill():
    x=continuation_h1_risk(prices(),10,side="SELL",atr_m5=1)
    assert x["true_bid_ask_verified"] is False
    assert x["cost_assumed_usd_oz"]==.50
    assert not x["authority_to_trade"]

def test_invalid_risk_side_or_atr():
    with pytest.raises(ValueError,match="BAD_SIDE"):
        continuation_h1_risk(prices(),10,side="WAIT",atr_m5=1)
    with pytest.raises(ValueError,match="BAD_RISK_PARAMS"):
        continuation_h1_risk(prices(),10,side="BUY",atr_m5=0)
