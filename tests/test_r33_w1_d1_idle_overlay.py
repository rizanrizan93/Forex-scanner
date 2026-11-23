"""R33 W1/D1 one-oz multi-timeframe history-only and preemption controls."""
from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import r33_w1_d1_idle_overlay as r


def dates(start="2025-01-06",n=12,freq="W-MON"):
    return pd.date_range(start,periods=n,freq=freq,tz="UTC")

def one(t,kind,side="BUY",days=5,gross=10.,index=0):
    return {
        "kind":kind,"side":side,"signal_index":index,
        "entry_time":t,"exit_time":t+pd.Timedelta(days=days),
        "entry_price":100.,"signed_gross":gross,
        "year":t.year,"exit_bar":index+1,
    }

def week(rows=12):
    t=dates(n=rows)
    w=pd.DataFrame({"o":[110.]*rows,"c":[112.]*rows,
                    "h":[114.]*rows,"l":[108.]*rows},index=t)
    return w

def permissions(n):
    return {g:{"BUY":np.ones(n,bool),"SELL":np.ones(n,bool)}
            for g in r.GATES}


def test_overlay_only_flat_and_baseline_prioritized(monkeypatch):
    # Small synthetic baseline uses two main events; override count for unit test.
    monkeypatch.setattr(r,"BASE_N",2)
    w=week(12)
    d=pd.DataFrame(index=dates(n=90,freq="D"))
    permitted=permissions(len(d))
    a=one(w.index[1],"main",days=14,gross=30.)
    b=one(w.index[5],"main",days=14,gross=30.)
    extra=[
        one(w.index[1]+pd.Timedelta(days=1),"overlay",days=2,gross=20.),
        one(w.index[4],"overlay",days=3,gross=12.),
        one(w.index[6],"overlay",days=3,gross=10.),
    ]
    result=r.schedule([a,b],extra,d,w,permitted,"any")
    assert result["main_trades"]==2
    assert result["additional_trades"]==1
    assert result["total_trades"]==3
    assert result["rejected"]["during_main"]>=2
    assert result["net_cost2_usd_per_1oz"]==pytest.approx(30-2+30-2+12-2)


def test_overlay_closes_at_main_w1_open_no_future_close(monkeypatch):
    monkeypatch.setattr(r,"BASE_N",1)
    w=week()
    d=pd.DataFrame(index=dates(n=90,freq="D"))
    g=permissions(len(d))
    b=one(w.index[4],"main",days=7,gross=20.)
    x=one(w.index[2],"overlay",days=25,gross=120.)
    got=r.schedule([b],[x],d,w,g,"any")
    assert got["additional_trades"]==1
    assert got["rejected"]["preempted"]==1
    early=next(x for x in got["trade_receipts"] if x["kind"]=="overlay")
    assert early["preempted"]
    assert early["exit_time"]==w.index[4].isoformat()
    # W1 actual open=110, overlay entry_price=100; never uses future +120.
    assert early["net_cost2_usd_oz"]==pytest.approx(110-100-2)
    assert got["net_cost2_usd_per_1oz"]==pytest.approx(8+18)


def test_concurrent_multiple_overlay_trades_rejected(monkeypatch):
    monkeypatch.setattr(r,"BASE_N",0)
    w=week()
    d=pd.DataFrame(index=dates(n=90,freq="D"))
    g=permissions(len(d))
    a=one(w.index[1],"overlay",days=14,gross=11.)
    b=one(w.index[2],"overlay",days=7,gross=100.)
    q=r.schedule([],[a,b],d,w,g,"any")
    assert q["additional_trades"]==1
    assert q["rejected"]["during_overlay"]==1
    assert q["net_cost2_usd_per_1oz"]==pytest.approx(9)


def test_overlay_bearish_weekly_prior_closed_gate_causal():
    w=week()
    zw=pd.DataFrame({"ema8":np.arange(len(w),dtype=float),
                     "ema21":np.ones(len(w),float)*2.},index=w.index)
    d=pd.DataFrame(index=dates("2025-01-06",84,"D"))
    zd=pd.DataFrame({
       "ema8":np.zeros(len(d)),"ema21":np.ones(len(d)),
       "adx14":np.ones(len(d))*25,
       "break8":np.zeros(len(d)),
    },index=d.index)
    got=r.gates(d,zd,w,zw)
    # Monday 13 Jan can only see the W1 bar beginning Jan 6.
    mon13=int(d.index.get_loc(pd.Timestamp("2025-01-13",tz="UTC")))
    assert not got["prior_week_ema"]["BUY"][mon13]
    # Jan 27 sees W1 bar Jan 20 whose EMA8=2 and EMA21=2, still not buy.
    mon27=int(d.index.get_loc(pd.Timestamp("2025-01-27",tz="UTC")))
    assert not got["prior_week_ema"]["BUY"][mon27]
    monfeb3=int(d.index.get_loc(pd.Timestamp("2025-02-03",tz="UTC")))
    assert got["prior_week_ema"]["BUY"][monfeb3]


def test_no_orders_only_research_and_full_history():
    path=Path(__file__).resolve().parents[1]/"scripts/r33_w1_d1_idle_overlay.py"
    s=path.read_text()
    assert "two prior calendar years" in s.lower()
    assert "R33_FROZEN_W1_REFERENCE_MISMATCH" in s
    assert "execution_authority" in s
    for forbidden in ("place_order(","execute_market_order(","broker/order",
                      "modify_position(","bridge/order","streamlit","git push"):
        assert forbidden not in s
