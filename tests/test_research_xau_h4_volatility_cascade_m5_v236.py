import pandas as pd
from fx_scanner.research_xau_h4_volatility_cascade_m5_v236_year import _m5_retest
from fx_scanner.research_xau_h4_volatility_cascade_m5_v236_aggregate import _select

def test_v236_m5_retest_long_hold():
    row=pd.Series({"low":99.8,"high":101.2,"open":100.0,"close":101.0,"atr14":1.0,"body":1.0,"close_loc":0.85})
    assert _m5_retest(row,direction="LONG",level=100.0,mode="RETEST_HOLD")
    assert _m5_retest(row,direction="LONG",level=100.0,mode="RETEST_DISPLACEMENT")

def test_v236_selection_train_only():
    rows=[]
    for y in range(2012,2019):
        for i in range(20):
            rows.append({"variant_id":"A","year":y,"gross_points":2.0 if i<13 else -1.0})
            rows.append({"variant_id":"B","year":y,"gross_points":1.0 if i<4 else -1.0})
    for y in range(2019,2027):
        for i in range(20):
            rows.append({"variant_id":"A","year":y,"gross_points":-10.0})
            rows.append({"variant_id":"B","year":y,"gross_points":10.0})
    selected,evidence=_select(rows)
    assert selected=="A"
    assert evidence["A"]["selection_passed"]
    assert not evidence["B"]["selection_passed"]
