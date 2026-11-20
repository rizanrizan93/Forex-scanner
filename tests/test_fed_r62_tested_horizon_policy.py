"""Lock R6.2 dashboard D1/D5 evidence to audited 2019-26 reports."""
import pytest
from fx_scanner.fed_r62_tested_horizon_policy import (
    audited_horizon_context, CONTRACT,
)

def test_audit_exact_r4_policy_shock_d1_d5_win_counts():
    r=audited_horizon_context()
    def cohort(h,side):
        return next(x for x in r["evidence"] if (
            x["model"]=="FOMC_OIS1Y_TIPS10_SP500_POLICY_LIKE" and
            x["horizon"]==h and x["side"]==side))
    assert (cohort("D1","BUY")["wins"],cohort("D1","BUY")["n_evaluable"])==(9,13)
    assert (cohort("D1","SELL")["wins"],cohort("D1","SELL")["n_evaluable"])==(9,11)
    assert (cohort("D5","BUY")["wins"],cohort("D5","BUY")["n_evaluable"])==(6,12)
    assert (cohort("D5","SELL")["wins"],cohort("D5","SELL")["n_evaluable"])==(5,8)

def test_audit_exact_r3_yields_dollar_d1_d5_win_counts():
    r=audited_horizon_context()
    def cohort(h,side):
        return next(x for x in r["evidence"] if (
            x["model"]=="FOMC_WINDOW_UST2Y_UST10Y_DXY" and
            x["horizon"]==h and x["side"]==side))
    assert (cohort("D1","BUY")["wins"],cohort("D1","BUY")["n_evaluable"])==(13,21)
    assert (cohort("D1","SELL")["wins"],cohort("D1","SELL")["n_evaluable"])==(10,15)
    assert (cohort("D5","BUY")["wins"],cohort("D5","BUY")["n_evaluable"])==(6,18)
    assert (cohort("D5","SELL")["wins"],cohort("D5","SELL")["n_evaluable"])==(6,12)

@pytest.mark.parametrize("dir",["BUY","SELL","WAIT"])
def test_d1_requires_actual_verified_fed_r4_event_not_daily_lean(dir):
    r=audited_horizon_context(market_direction=dir,
                              daily_direction="BUY",fed_r4_direction="WAIT")
    assert r["d1_event_research_watch"]=="WAIT"
    assert r["d1_context_only_not_backtest_approved"]==dir
    assert r["entry_permission"] is False
    assert r["execution_authority"] is False
    assert r["market_context_model_was_historically_replayed"] is False

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_even_real_fomc_r4_watch_not_extended_for_five_days(side):
    r=audited_horizon_context(market_direction=side,daily_direction=side,
                              fed_r4_direction=side)
    assert r["contract"]==CONTRACT
    assert r["d1_event_research_watch"]==side
    assert r["d3"].startswith("WAIT")
    assert r["d5"].startswith("WAIT")
    assert r["causal_winner_between_fed_and_yield_dxy"]=="UNDETERMINED"
    assert not r["bidirectional_80pct_validated"]

def test_no_fake_event_wins_or_prospective_accuracy():
    rows=audited_horizon_context()["evidence"]
    assert len(rows)==8
    assert all(x["genuine_point_in_time_tested"] is False for x in rows)
    assert all(x["independent_prospective_validated"] is False for x in rows)
    assert all(x["production_order_authority"] is False for x in rows)

def test_invalid_direction_rejected():
    with pytest.raises(ValueError,match="UNRECOGNIZED_DIRECTION"):
        audited_horizon_context(market_direction="LONG")
