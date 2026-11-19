"""Pure tests for real-price replay oracle separation and production evidence gate."""
import pytest
from research.fed_expectation_r1.release_gate import evaluate,wilson_lower
from scripts.replay_fed_macro_event_pilot_r1 import classify_offline_window,excel_et

def test_expost_hawkish_dovish_same_units_symmetric():
    x=classify_offline_window({"MP2":0.020689655,"UST2Y":0.06525,"DXY":0.2997})
    assert x["side"]=="SELL" and x["mp2_change_bp"]>2
    y=classify_offline_window({"MP2":-0.030,"UST2Y":-0.045,"DXY":-0.32})
    assert y["side"]=="BUY"
    assert classify_offline_window({"MP2":0.004,"UST2Y":0.08,"DXY":0.4})["side"]=="WAIT"
    assert classify_offline_window({"MP2":None,"UST2Y":0.08,"DXY":0.4})["side"]=="WAIT"

def test_excel_timestamp_et_dst_not_naive_utc():
    v=45189+14/24
    d=excel_et(v)
    assert d.year==2023 and d.month==9 and d.day==20 and d.hour==14
    assert d.utcoffset().total_seconds()==-4*3600
    assert d.astimezone(__import__('datetime').timezone.utc).hour==18

def evidence():
    return {
        "paired_real_xau_events":False,
        "futures_same_contract_pit":False,
        "intraday_cash_us2y_pit":False,
        "usd_proxy_pit":False,
        "source_hashes_valid":True,
        "utc_release_windows_verified":True,
        "real_quote_age_and_spread_valid":False,
        "commission_slippage_included":False,
        "genuine_prospective_holdout":False,
        "buy":{"n":0,"wins":0,"nonoverlapping":True,"net_expectancy_usd":0.0},
        "sell":{"n":0,"wins":0,"nonoverlapping":True,"net_expectancy_usd":0.0},
        "years":[2023],
    }

def test_incomplete_true_price_source_does_not_authorize_release():
    r=evaluate(evidence())
    assert not r["read_only_production_review_eligible"]
    assert not r["authority_to_deploy"]
    assert not r["authority_to_send_orders"]
    assert "INSUFFICIENT_BUY_N" in r["failed_gates"]
    assert "INSUFFICIENT_SELL_N" in r["failed_gates"]

def test_even_paper_100pct_accuracy_cannot_override_missing_pit():
    m=evidence()
    m["buy"]={"n":100,"wins":100,"nonoverlapping":True,"net_expectancy_usd":2.5}
    m["sell"]={"n":100,"wins":100,"nonoverlapping":True,"net_expectancy_usd":2.5}
    m["years"]=[2019,2021,2023]
    assert not evaluate(m)["read_only_production_review_eligible"]

def test_wilson_is_lower_confidence_not_point_rate():
    assert wilson_lower(60,100)<.60
    assert wilson_lower(80,100)>.60
    assert wilson_lower(0,0) is None
    with pytest.raises(ValueError):
        wilson_lower(11,10)

def test_manual_review_only_even_if_hypothetically_all_checks_pass():
    m=evidence()
    for key,value in tuple(m.items()):
        if isinstance(value,bool):m[key]=True
    m["buy"]={"n":200,"wins":170,"nonoverlapping":True,"net_expectancy_usd":1.5}
    m["sell"]={"n":210,"wins":170,"nonoverlapping":True,"net_expectancy_usd":1.0}
    m["years"]=[2019,2020,2022,2024]
    result=evaluate(m)
    assert result["read_only_production_review_eligible"]
    assert result["authority_to_deploy"] is False
    assert result["authority_to_send_orders"] is False
