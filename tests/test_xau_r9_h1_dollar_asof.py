import numpy as np
import pandas as pd
import pytest
from research.zone_rebound.xau_r9_h1_dollar_asof import join_r6_events, conditional_gate

def sample():
    opens = pd.date_range("2025-06-02 00:00", periods=8, freq="h", tz="UTC")
    macro = pd.DataFrame({"source_open_utc": opens,
      "source_close_utc": opens + pd.Timedelta(hours=1),
      "available_utc": opens + pd.Timedelta(minutes=62),
      "close": [100, 101, 102, 103, 104, 105, 106, 107],
      "ret_1h": [np.nan] + [0.01] * 7,
      "ret_3h": [np.nan]*3 + [0.03]*5,
      "ret_6h": [np.nan]*6 + [0.06]*2})
    return macro

def event(iso):
    return pd.DataFrame({"entry_ns": [pd.Timestamp(iso).value], "side": [1]})

def test_future_h1_not_visible_before_close_plus_lag():
    m=sample()
    before=join_r6_events(event("2025-06-02T02:01:00Z"),m)
    after=join_r6_events(event("2025-06-02T02:02:00Z"),m)
    assert before.source_open_utc.iloc[0] == pd.Timestamp("2025-06-02T00:00:00Z")
    assert after.source_open_utc.iloc[0] == pd.Timestamp("2025-06-02T01:00:00Z")
    assert not before.macro_valid.iloc[0]
    assert after.macro_valid.iloc[0]

def test_quote_age_expiry():
    z=join_r6_events(event("2025-06-02T08:30:00Z"),sample(),max_age_minutes=20)
    assert not z.macro_valid.iloc[0]
    assert np.isnan(z.ret_1h.iloc[0])

def test_aligned_vs_contrarian():
    m=sample()
    z=join_r6_events(event("2025-06-02T04:03:00Z"),m)
    assert len(conditional_gate(z,mode="aligned")) == 0
    assert len(conditional_gate(z,mode="contrarian")) == 1

def test_future_macro_rejected_by_asof():
    m=sample()
    z=join_r6_events(event("2025-06-02T00:01:00Z"),m)
    assert pd.isna(z.available_utc.iloc[0])
    assert not z.macro_valid.iloc[0]

def test_invalid_macro_order():
    m=sample().iloc[::-1].copy()
    with pytest.raises(ValueError,match="chronology"):
        join_r6_events(event("2025-06-02T04:03:00Z"),m)
