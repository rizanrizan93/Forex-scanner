"""Fast synthetic regression only; empirical accuracy comes from HistData CI."""
from math import sin
import pandas as pd
import pytest
from fx_scanner.fed_r65_histdata_price_audit import (
    audit_price_only_four_hours, _bias_series, CONTRACT)
from fx_scanner.fed_r6_manual_entry_areas import _bias


def fake_m1():
    ix=pd.date_range("2025-01-01",periods=60*24*13,freq="min",tz="UTC")
    vals=[2000+0.0025*i+1.5*sin(i/125) for i in range(len(ix))]
    return pd.DataFrame({"open":vals,"high":[x+.3 for x in vals],
                         "low":[x-.3 for x in vals],"close":vals},index=ix)


def test_price_only_four_hour_accounting_never_claims_macro_accuracy():
    x=audit_price_only_four_hours(fake_m1(),year=2025,month=1)
    assert x["contract"]==CONTRACT
    assert x["status"]=="PRICE_ONLY_DIAGNOSTIC"
    assert x["candidate_count"]>0
    assert x["guarded_count"]+x["blocked_count"]==x["candidate_count"]
    assert x["historical_macro_dxy_yield_verified"] is False
    assert x["R65_full_engine_forecast_backtested"] is False
    assert x["execution_authority"] is False
    for k in ("0.0","0.4","1.0"):
        g=x["cohorts"][k]
        assert g["baseline"]["n"]==x["candidate_count"]
        assert g["guarded"]["n"]==x["guarded_count"]
        assert g["blocked_losers"]+g["blocked_winners"]==x["blocked_count"]


def test_precomputed_bias_matches_original_r6_bias_exactly():
    ix=pd.date_range("2025-01-01",periods=80,freq="15min",tz="UTC")
    d=pd.DataFrame({"close":[2000+i*.08+.6*sin(i/6) for i in range(80)]},
                   index=ix)
    s=_bias_series(d)
    for i in range(24,80):
        assert s.iloc[i]==_bias(d.iloc[:i+1])


def test_invalid_data_not_silently_counted_as_real_history():
    d=fake_m1()
    dupe=pd.concat([d,d.tail(1)])
    with pytest.raises(ValueError,match="NON_MONOTONIC"):
        audit_price_only_four_hours(dupe,year=2025,month=1)
    d.iloc[-1,d.columns.get_loc("low")]=d.close.iloc[-1]+3
    with pytest.raises(ValueError,match="INVALID_M1"):
        audit_price_only_four_hours(d,year=2025,month=1)
