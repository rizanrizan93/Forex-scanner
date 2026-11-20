"""Replay accounting fixtures; outcomes synthetic, not measured market accuracy."""
import pandas as pd
import pytest
from fx_scanner.fed_r64_liquidity_replay import replay_liquidity_guard, wilson95


def data():
    idx=pd.date_range("2026-11-19T10:05:00Z",periods=120,freq="5min")
    d=pd.DataFrame({"open":100.,"high":100.5,"low":99.5,"close":100.},index=idx)
    d.loc[d.index[37:47],["open","high","low","close"]]=[99.,99.5,98.5,99.]
    d.loc[d.index[77:88],["open","high","low","close"]]=[102.,102.5,101.5,102.]
    return d


def ledger(index):
    return pd.DataFrame([
        {"signal_at":index[35],"side":"SELL",
         "macro_received_at":index[35],"price_received_at":index[35]},
        {"signal_at":index[75],"side":"BUY",
         "macro_received_at":index[75],"price_received_at":index[75]},
    ])


def test_replay_synthetic_accounting_and_next_bar_open_only():
    d=data()
    result=replay_liquidity_guard(d,ledger(d.index),horizon_bars=12,spread_points=.20)
    assert result["status"]=="EVALUATED"
    assert result["candidate_baseline"]["n"]==2
    assert result["candidate_guarded"]["n"]+result["blocked"]["n"]==2
    assert result["sample_years"]==[2026]
    assert result["validated_live_80pct"] is False
    assert result["usable_for_auto_trading"] is False
    assert all("entry_next_open" in x for x in result["events"])
    assert 0<=result["coverage_pct"]<=100


def test_source_arriving_after_signal_rejected():
    d=data()
    s=ledger(d.index)
    s.loc[0,"macro_received_at"]=d.index[36]
    with pytest.raises(ValueError,match="NON_CAUSAL"):
        replay_liquidity_guard(d,s)


def test_duplicate_signals_cannot_double_count_samples():
    d=data()
    s=ledger(d.index)
    s=pd.concat([s,s.iloc[[0]]],ignore_index=True)
    with pytest.raises(ValueError,match="DUPLICATE"):
        replay_liquidity_guard(d,s)


def test_m5_future_bar_mutation_does_not_affect_veto_at_signal_time():
    d=data()
    a=replay_liquidity_guard(d,ledger(d.index),horizon_bars=12)
    d.loc[d.index[41],["open","high","low","close"]]=[100.,150.,50.,100.]
    b=replay_liquidity_guard(d,ledger(d.index),horizon_bars=12)
    assert a["events"][0]["guard_state"]==b["events"][0]["guard_state"]
    assert a["events"][0]["guard_veto"]==b["events"][0]["guard_veto"]


def test_wilson_lower_bound_is_conservative():
    assert 0 < wilson95(9,11)<9/11
    assert wilson95(0,0) is None


def test_absent_complete_ledger_reports_insufficient_not_fake_win_rate():
    d=data()
    l=ledger(d.index)
    l["signal_at"]=pd.Timestamp("2026-11-18T00:00:00Z")
    l.loc[1,"signal_at"]=pd.Timestamp("2026-11-18T01:00:00Z")
    l["macro_received_at"]=l["signal_at"]
    l["price_received_at"]=l["signal_at"]
    out=replay_liquidity_guard(d,l)
    assert out["status"]=="INSUFFICIENT_PAIRED_SIGNALS"
    assert out["candidate_baseline"]["correct_pct"] is None
