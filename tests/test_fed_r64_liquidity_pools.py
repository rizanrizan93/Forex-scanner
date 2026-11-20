"""Synthetic fixtures for point-in-time liquidity pool mapping, not a replay."""
import pandas as pd
from fx_scanner.fed_r64_liquidity_pools import map_xau_liquidity_pools, CONTRACT


def historical_m5(end="2026-11-20T11:00:00Z"):
    idx=pd.date_range("2026-11-17T22:05:00Z",end,freq="5min")
    d=pd.DataFrame({"open":100.0,"high":101.0,"low":99.0,"close":100.0},index=idx)
    return d


def test_previous_completed_ny17_session_and_completed_asia_session():
    d=historical_m5()
    # Known completed Asia session of Nov 20 (01:05 through 06:00 UTC).
    at=pd.Timestamp("2026-11-20T02:00:00Z")
    d.loc[at,["open","high","low","close"]]=[100.,105.,99.,101.]
    x=map_xau_liquidity_pools(d,now=d.index[-1])
    assert x["contract"]==CONTRACT
    assert x["entry_permission"] is False
    assert x["actual_stop_orders_observed"] is False
    tags={v["name"]:v for v in x["levels"]}
    assert {"PRIOR_NY_DAY_HIGH","PRIOR_NY_DAY_LOW","ASIA_SESSION_HIGH","ASIA_SESSION_LOW"}<=set(tags)
    assert tags["ASIA_SESSION_HIGH"]["session_date"]=="2026-11-20"
    assert tags["ASIA_SESSION_HIGH"]["price"]==105.
    assert tags["PRIOR_NY_DAY_HIGH"]["price"]==101.


def test_current_unfinished_asia_must_not_leak_into_reference_levels():
    d=historical_m5(end="2026-11-20T04:00:00Z")
    # Large high inside today's unfinished Asian session may not be used.
    d.loc[pd.Timestamp("2026-11-20T02:00:00Z"),["open","high","low","close"]]=[100,115,99,101]
    x=map_xau_liquidity_pools(d,now=d.index[-1])
    sessions=[v for v in x["levels"] if v["name"]=="ASIA_SESSION_HIGH"]
    assert sessions
    assert all(v["session_date"]!="2026-11-20" for v in sessions)
    assert all(v["price"]!=115. for v in sessions)


def test_previous_day_is_not_current_unfinished_ny_day():
    d=historical_m5(end="2026-11-20T11:00:00Z")
    d.loc[pd.Timestamp("2026-11-20T08:00:00Z"),["open","high","low","close"]]=[100,115,99,101]
    x=map_xau_liquidity_pools(d,now=d.index[-1])
    prior=[v for v in x["levels"] if v["name"]=="PRIOR_NY_DAY_HIGH"]
    assert prior
    assert all(v["price"]!=115. for v in prior)


def test_stale_source_blocks_liquidity_reference_levels():
    d=historical_m5(end="2026-11-19T12:00:00Z")
    x=map_xau_liquidity_pools(d,now=pd.Timestamp("2026-11-20T11:00:00Z"))
    assert x["state"]=="UNKNOWN"
    assert x["levels"]==[]


def test_naive_or_incomplete_data_does_not_invent_levels():
    d=historical_m5().iloc[:30]
    assert map_xau_liquidity_pools(d,now=d.index[-1])["levels"]==[]
    d=historical_m5()
    assert map_xau_liquidity_pools(d,now=pd.Timestamp("2026-11-20 11:00"))["state"]=="UNKNOWN"
