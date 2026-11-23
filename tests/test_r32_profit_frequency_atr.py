"""R32 stop-first intrabar, gap, causal trail, fixed 1oz and audit tests."""
import numpy as np
import pandas as pd
import pytest
import r32_profit_frequency_atr as r32


def candles(rows,start="2026-01-05"):
    idx=pd.date_range(start,periods=len(rows),freq="W-MON",tz="UTC")
    return pd.DataFrame(rows,columns=["o","h","l","c"],index=idx)


def test_next_open_to_future_close_no_lookahead():
    d=candles([[100,104,97,102],[105,108,103,106],[107,115,101,112]])
    gross,ends=r32.exits(d,np.array([4.,4.,4.]),"1W",2,"fixed",0,0)
    assert ends["BUY"][0]==2
    assert gross["BUY"][0]==pytest.approx(112-105)
    assert gross["SELL"][0]==pytest.approx(105-112)
    assert np.isnan(gross["BUY"][-1])


def test_simultaneous_tp_sl_conservatively_assumes_stop_first():
    d=candles([[100,102,98,101],[100,115,90,108],[106,109,101,107]])
    gross,ends=r32.exits(d,np.full(3,4.),"1W",2,"bracket",1.5,2)
    assert gross["BUY"][0]==pytest.approx(-6.)
    assert ends["BUY"][0]==1


def test_atr_trailing_updates_only_after_completed_candle():
    d=candles([[100,103,97,101],[100,115,99,110],[111,112,105,106]])
    profit,ends=r32.exits(d,np.full(3,4.),"1W",2,"trail",2,0)
    assert ends["BUY"][0]==2
    assert profit["BUY"][0]==pytest.approx(7.)


def test_gap_beyond_trailing_stop_fills_open_worse():
    d=candles([[100,103,97,101],[100,115,99,110],[95,112,93,102]])
    profit,ends=r32.exits(d,np.full(3,4.),"1W",2,"trail",2,0)
    assert profit["BUY"][0]==pytest.approx(-5.)
    assert ends["BUY"][0]==2


def test_missing_intermediate_bar_invalidates_exit():
    d=candles([[100,103,97,101],[100,115,99,110],[95,112,93,102]])
    d=d.drop(d.index[1])
    p,e=r32.exits(d,np.full(len(d),4.),"1W",1,"fixed",0,0)
    assert np.isnan(p["BUY"][0]) and e["BUY"][0]==-1


def test_nonoverlap_uses_actual_early_exit_not_fixed_horizon():
    mask=np.ones(8,bool)
    valid=np.ones(8,bool)
    exits=np.array([1,2,5,4,6,7,7,7],int)
    x=r32.pick(mask,valid,exits)
    assert x.tolist()==[0,1,2,5,7]


def test_profit_and_frequency_selection_are_separate():
    x={"n":30,"net":200.,"pf":1.7,"dd":150.}
    y={"n":80,"net":110.,"pf":1.4,"dd":120.}
    assert r32.ranked(x,"max_net",2,15)>r32.ranked(y,"max_net",2,15)
    assert r32.ranked(x,"max_signals",2,15)<r32.ranked(y,"max_signals",2,15)
    assert r32.ranked(x,"profit_frequency",2,15) is not None


def test_no_live_orders_and_validation_ends_before_test_boundary():
    from pathlib import Path
    s=(Path(__file__).resolve().parents[1]/
       "scripts/r32_profit_frequency_atr.py").read_text()
    assert "endt<cutoff" in s
    assert "NEXT candle OPEN" in s
    assert "execution_authority" in s
    for bad in ("execute_market_order(","place_order(","modify_position(",
                "broker/order","bridge/order","streamlit", "git push"):
        assert bad not in s
