"""Full R4 captured-fixture → actual V4 candle criteria → R5 direction integration.

ALL CANDLES AND QUOTES ARE SYNTHETIC TEST DATA. This only validates
signal-flow and fail-closed controls, not PnL or real signal accuracy.
"""
import pandas as pd
import pytest
from fx_scanner.rejection_v4_research import evaluate_v4
from research.fed_expectation_r1.policy_information_watch_r4 import watch
from research.fed_expectation_r1.macro_entry_alignment_r5 import align_macro_v4

NOW=pd.Timestamp("2026-11-18T19:06:00Z")
EVENT={"event_id":"R5-FOMC","event_kind":"FOMC_MINUTES",
       "release_at":"2026-11-18T19:00:00Z",
       "source_url":"https://www.federalreserve.gov/monetarypolicy/fomcminutes20261028.htm"}
SOURCES={
    "OIS1Y_RATE_BP":("BPS",450,453),
    "TIPS10Y_INTRADAY_YIELD_BP":("BPS",140,142),
    "SP500_INDEX_LEVEL":("INDEX_LEVEL",6000,5988),
    "USD_INDEX_PROXY_LEVEL":("INDEX_LEVEL",100,100.2)
}

def fed_samples(dovish=False):
    samples=[]
    for series,(unit,prior,after) in SOURCES.items():
        if dovish:
            after={
                "OIS1Y_RATE_BP":447,
                "TIPS10Y_INTRADAY_YIELD_BP":138,
                "SP500_INDEX_LEVEL":6012,
                "USD_INDEX_PROXY_LEVEL":99.8,
            }[series]
        for b,v in [(False,prior),(True,after)]:
            ts="2026-11-18T19:04:00Z" if b else "2026-11-18T18:59:00Z"
            samples.append({
                "event_id":EVENT["event_id"],"series":series,
                "unit":unit,"value":v,"instrument":series,
                "provider":"SYNTHETIC_TEST_FIXTURE","source_url":"https://example.org/",
                "provenance_mode":"CAPTURED_REALTIME",
                "quote_frequency":"INTRADAY_CASH_TIPS" if "TIPS" in series else "INTRADAY",
                "bar_end_at":ts,"published_at":ts,"ingested_at":ts
            })
    return samples

def synthetic_v4(side):
    idx=pd.date_range(end=NOW-pd.Timedelta(minutes=1),periods=160,freq="min",tz="UTC")
    d=pd.DataFrame({"open":100., "close":100.,"high":100.2,"low":99.8},index=idx)
    if side=="BUY":
        d.iloc[-1]=[100.,100.8,100.9,99.]
        bid,ask=(100.77,100.82)
        opposite="SELL"
    else:
        d.iloc[-1]=[100.,99.2,101.,99.1]
        bid,ask=(99.18,99.23)
        opposite="BUY"
    m5idx=pd.date_range(end=NOW-pd.Timedelta(minutes=5),periods=40,freq="5min",tz="UTC")
    m5=pd.DataFrame({"open":100.,"close":100.,"high":103.,"low":97.},index=m5idx)
    r=evaluate_v4(d,m5,h1_bias=opposite,h4_bias=opposite,
                  atr_m5=2.,now=NOW,quote_valid=True,bid=bid,ask=ask)
    actual=next(x for x in r if x["side"]==side)
    assert actual["entry_status"]=="ENTRY_CANDIDATE"
    return r

@pytest.mark.parametrize("technical_side,dovish,expected_aligned",[
    ("BUY",False,0),("SELL",False,1),
    ("BUY",True,1),("SELL",True,0),
])
def test_real_v4_signal_is_filtered_by_opposing_fomc_engine(
    technical_side,dovish,expected_aligned
):
    macro=watch(EVENT,fed_samples(dovish),decision_at=NOW)
    assert macro["direction"]==("BUY" if dovish else "SELL")
    v4=synthetic_v4(technical_side)
    out=align_macro_v4(v4,macro,EVENT,evaluated_at=NOW)
    assert out["aligned_entry_candidate_n"]==expected_aligned
    assert out["eligible_for_live"] is False
    assert out["authority_to_send_orders"] is False

def test_no_macro_event_feed_blocks_both_sides_cleanly():
    v4=synthetic_v4("BUY")
    out=align_macro_v4(v4,None,None,evaluated_at=NOW)
    assert out["macro_direction"]=="WAIT"
    assert out["aligned_entry_candidate_n"]==0
    assert len(out["research_candidates"])==2
    assert all(x["macro_alignment_gate"]=="BLOCKED_NO_FOMC_MARKET_SOURCE"
               for x in out["research_candidates"])
