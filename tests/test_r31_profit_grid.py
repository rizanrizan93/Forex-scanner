"""R31 strict 1oz non-overlap and next-OPEN execution proxy tests."""
import numpy as np
import pandas as pd
import pytest

import r31_profit_grid as r


def candles(n=240,tf="1h"):
    dates=pd.date_range("2025-11-01",periods=n,freq=tf,tz="UTC")
    a=np.arange(n,dtype=float)
    return pd.DataFrame({
       "o":2000+a,"c":2000+a+1,
       "h":2000+a+3,"l":2000+a-2,
    },index=dates)


def test_next_open_price_and_horizon_strictly_future():
    d=candles()
    valid,gross,exit_time,adverse=r.exit_frames(d,"1h",1)
    assert valid[0]
    assert gross[0]==pytest.approx(d.c.iloc[1]-d.o.iloc[1])
    assert exit_time[0]==np.datetime64("2025-11-01T02:00:00")
    assert adverse[0,0]==pytest.approx(-2)
    assert adverse[1,0]==pytest.approx(-3)
    valid2,gross2,_,_=r.exit_frames(d,"1h",2)
    assert valid2[0]
    assert gross2[0]==pytest.approx(d.c.iloc[2]-d.o.iloc[1])
    assert not valid2[-1]


def test_gap_blocks_optimistic_next_bar_fill():
    d=candles()
    d=d.drop(d.index[2])
    v1,_,_,_=r.exit_frames(d,"1h",1)
    assert not v1[1]


def test_nonoverlap_excludes_same_bar_duplicates():
    n=30
    mask=np.ones(n,dtype=bool)
    eligible=mask.copy()
    assert r.choose_indices(mask,eligible,1).tolist()==list(range(30))
    assert r.choose_indices(mask,eligible,3).tolist()==list(range(0,30,3))
    mask[0]=False
    assert r.choose_indices(mask,eligible,3)[0]==1


def test_metrics_are_net_2_usd_one_oz_and_realized_drawdown():
    vals=np.array([10.,-4.,-4.,10.])
    ids=np.arange(len(vals))
    q=r.metrics(ids,"BUY",vals)
    assert q["gross_usd_oz"]==12
    assert q["net_usd_oz"]==4
    assert q["n"]==4
    assert q["max_drawdown_usd_oz"]==12
    assert q["profit_factor"]==pytest.approx(16/12)
    assert r.metrics(ids,"BUY",vals,cost=5.)["net_usd_oz"]==-8
    assert r.metrics(ids,"SELL",vals)["net_usd_oz"]==-20


def test_profit_rank_prefers_net_not_only_accuracy():
    good={"n":100,"net_usd_oz":1000.,"net_mean_usd_oz":10.,
          "profit_factor":1.5,"max_drawdown_usd_oz":200.}
    higher={"n":30,"net_usd_oz":1500.,"net_mean_usd_oz":50.,
          "profit_factor":1.2,"max_drawdown_usd_oz":2000.}
    assert r.policy_rank(higher,"max_net",2)>r.policy_rank(good,"max_net",2)
    assert r.policy_rank(higher,"net_dd",2)<r.policy_rank(good,"net_dd",2)
    assert r.policy_rank(higher,"net_dd",1) is None


def test_no_future_labels_feed_side_masks():
    from r10_million import ohlc_indicators
    d=candles()
    z=ohlc_indicators(d)
    before,bs,bv=r.sides(d,z,d.index+pd.Timedelta(hours=1),"1h")
    altered=d.copy()
    # Changing a future candle cannot change the signal at an earlier close.
    altered.loc[altered.index[-1],"c"]+=3000
    altered.loc[altered.index[-1],"h"]+=3000
    after,aas,av=r.sides(altered,ohlc_indicators(altered),
                         altered.index+pd.Timedelta(hours=1),"1h")
    for side in ("BUY","SELL"):
        for name in before[side]["base"]:
            assert np.array_equal(before[side]["base"][name][:-1],
                                  after[side]["base"][name][:-1])


def test_read_only_contract_and_partial_2026_flag():
    from pathlib import Path
    code=(Path(__file__).resolve().parents[1]/"scripts/r31_profit_grid.py").read_text()
    assert "NEXT_BAR_OPEN" in code
    assert "finish<boundary" in code
    assert '"partial_2026":True' in code
    assert "execution_authority" in code
    for prohibited in (
        "execute_market_order(","place_order(","modify_position(",
        "broker/order","bridge/order","streamlit",
    ):
        assert prohibited not in code
