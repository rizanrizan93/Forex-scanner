"""R32.1 W1 main+overlay actual portfolio occupation and cost tests."""
import numpy as np
import pandas as pd
import pytest
import r321_w1_profit_signal_overlay as r


def candles():
    d=pd.DataFrame({
        "o":[100.,102.,103.,104.,101.,106.,107.,108.,109.,110.],
        "h":[104.,105.,106.,108.,107.,110.,111.,112.,114.,115.],
        "l":[98.,100.,99.,101.,100.,102.,103.,104.,105.,108.],
        "c":[102.,103.,104.,105.,104.,108.,108.,110.,112.,113.],
    },index=pd.date_range("2025-02-03",periods=10,freq="W-MON",tz="UTC"))
    z=pd.DataFrame({"ema8":[1.]*10,"ema21":[0.]*10},index=d.index)
    return d,z


def trade(kind,signal,exitbar,gross,side="BUY",year=2025):
    return {"kind":kind,"side":side,"signal_bar":signal,
            "entry_bar":signal+1,"exit_bar":exitbar,
            "signed_gross_usd_oz":gross,"year":year}


def test_overlay_only_when_main_is_flat_one_oz():
    d,z=candles()
    base=[trade("baseline",0,4,4),trade("baseline",5,9,6)]
    overlay=[
        trade("overlay",1,2,2),
        trade("overlay",4,5,5),
    ]
    p=r.portfolio(d,z,base,overlay,"any_flat")
    assert p["baseline_n"]==2
    assert p["overlay_n"]==0
    assert p["n"]==2
    assert p["net_cost2_usd_per_fixed1oz"]==pytest.approx(6)
    assert p["net_cost5_usd_per_fixed1oz"]==pytest.approx(0)


def test_main_entry_preempts_overlay_at_open_without_future_close():
    d,z=candles()
    base=[trade("baseline",4,8,10)]
    overlay=[trade("overlay",1,6,40,side="BUY")]
    p=r.portfolio(d,z,base,overlay,"any_flat")
    assert p["baseline_n"]==1 and p["overlay_n"]==1
    candidate=next(t for t in p["trades"] if t["kind"]=="overlay")
    assert candidate["preempted"]
    assert candidate["exit_bar"]==5
    assert candidate["net_cost2_usd_oz"]==pytest.approx(d.o.iloc[5]-d.o.iloc[2]-2)
    assert p["ignored"]["preempted"]==1


def test_main_has_priority_if_simultaneous_entry():
    d,z=candles()
    base=[trade("baseline",0,4,10)]
    overlay=[trade("overlay",0,1,2)]
    p=r.portfolio(d,z,base,overlay,"any_flat")
    assert p["n"]==1 and p["baseline_n"]==1


def test_direction_filter_uses_only_prior_closed_candle():
    d,z=candles()
    base=[]
    overlay=[trade("overlay",0,1,3,side="SELL")]
    assert r.portfolio(d,z,base,overlay,"any_flat")["n"]==1
    assert r.portfolio(d,z,base,overlay,"ema_direction")["n"]==0


def test_no_broker_order_or_account_leverage():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r321_w1_profit_signal_overlay.py").read_text()
    assert "max_gross_risk_exposure_oz" in s
    assert "max_concurrent_positions" in s
    for bad in ("execute_market_order(","place_order(","modify_position(",
                "broker/order","bridge/order","streamlit","git push"):
        assert bad not in s
