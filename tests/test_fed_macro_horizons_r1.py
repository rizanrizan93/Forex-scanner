"""Macro directional horizon labels, not fixed +$3 trading TP."""
from datetime import timedelta
import pandas as pd
import pytest
from research.fed_expectation_r1.macro_horizons import evaluate_macro_horizons

AT=pd.Timestamp("2023-09-20T18:20:00Z")

def weekday_m1(start="2023-09-19",end="2023-10-10"):
    frames=[]
    for day in pd.date_range(start,end,freq="D",tz="UTC"):
        if day.weekday()>=5:continue
        index=pd.date_range(day,day+pd.Timedelta(hours=21,minutes=59),freq="min")
        price=(110.0 if day.date()<=pd.Timestamp("2023-09-22").date()
               else 90.0)
        if day.date()==AT.date():price=100.0
        frames.append(pd.DataFrame({
            "open":price,"high":price+.3,"low":price-.3,"close":price},index=index))
    return pd.concat(frames)

def test_buy_works_d1_but_fails_by_d5_without_any_3usd_tp_metric():
    d=weekday_m1()
    r=evaluate_macro_horizons(d,signal_at=AT,side="BUY",cost_usd_oz=.50)
    assert r["entry_price"]==100
    assert r["outcomes"]["H4"]["status"]=="CENSORED"
    assert r["outcomes"]["D1"]["direction_correct"] is True
    assert r["outcomes"]["D3"]["direction_correct"] is False
    assert r["outcomes"]["D5"]["direction_correct"] is False
    assert r["outcomes"]["D10"]["status"]=="EVALUATED"
    assert r["outcomes"]["D5"]["completed_utc_trading_sessions"]==5
    assert "target_first" not in r["outcomes"]["D5"]
    assert r["authority_to_deploy"] is False

def test_sell_direction_is_symmetric():
    d=weekday_m1()
    r=evaluate_macro_horizons(d,signal_at=AT,side="SELL",cost_usd_oz=.5)
    assert r["outcomes"]["D1"]["direction_correct"] is False
    assert r["outcomes"]["D3"]["direction_correct"] is True

def test_missing_weekday_session_censors_all_following_weekly_labels():
    d=weekday_m1()
    d=d.loc[d.index.date!=pd.Timestamp("2023-09-22").date()]
    r=evaluate_macro_horizons(d,signal_at=AT,side="BUY")
    assert r["outcomes"]["D1"]["status"]=="EVALUATED"
    assert r["outcomes"]["D3"]["status"]=="CENSORED"
    assert r["outcomes"]["D5"]["reason"]=="MISSING_OR_PARTIAL_TRADING_SESSION"

def test_no_entry_clock_no_label_or_price_guess():
    d=weekday_m1()
    d=d.drop(AT)
    r=evaluate_macro_horizons(d,signal_at=AT,side="BUY")
    assert all(v["status"]=="CENSORED" for v in r["outcomes"].values())

def test_h4_contiguous_history_required_and_direction_is_symmetric():
    ix=pd.date_range("2023-09-20T00:00:00Z",periods=650,freq="min",tz="UTC")
    p=[100.0]*360+[103.0]*290
    d=pd.DataFrame({"open":p,"high":[x+.2 for x in p],
                    "low":[x-.2 for x in p],"close":p},index=ix)
    t=pd.Timestamp("2023-09-20T05:00:00Z")
    r=evaluate_macro_horizons(d,signal_at=t,side="BUY")
    assert r["outcomes"]["H4"]["status"]=="EVALUATED"
    assert r["outcomes"]["H4"]["direction_correct"] is True
    d=d.drop(pd.Timestamp("2023-09-20T06:00:00Z"))
    r=evaluate_macro_horizons(d,signal_at=t,side="BUY")
    assert r["outcomes"]["H4"]["status"]=="CENSORED"

@pytest.mark.parametrize("side",["LONG","NONE",None])
def test_unknown_direction_rejected(side):
    with pytest.raises(ValueError,match="BAD_SIDE"):
        evaluate_macro_horizons(weekday_m1(),signal_at=AT,side=side)

def test_naive_signal_rejected():
    with pytest.raises(ValueError,match="UTC_AWARE_SIGNAL_REQUIRED"):
        evaluate_macro_horizons(weekday_m1(),signal_at="2023-09-20 18:20",side="BUY")

def test_partial_future_day_is_not_full_session():
    d=weekday_m1()
    d=d.loc[d.index<pd.Timestamp("2023-09-21T12:00:00Z")]
    r=evaluate_macro_horizons(d,signal_at=AT,side="BUY")
    assert r["outcomes"]["D1"]["status"]=="CENSORED"
    assert r["outcomes"]["D10"]["status"]=="CENSORED"

def test_data_gap_cannot_be_constructed_as_weekend():
    d=weekday_m1()
    # Remove 3 hours during a weekday session
    d=d.loc[~((d.index>=pd.Timestamp("2023-09-21T10:00Z"))&
              (d.index<pd.Timestamp("2023-09-21T13:00Z")))]
    r=evaluate_macro_horizons(d,signal_at=AT,side="BUY")
    assert r["outcomes"]["D1"]["status"]=="CENSORED"
    assert r["outcomes"]["D1"]["detail"]["reason"]=="INTRADAY_M1_GAP"
