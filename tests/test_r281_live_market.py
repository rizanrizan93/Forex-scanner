"""Read-only R28.1 shadow input tests. No HTTP calls or broker actions."""
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from r281_live_market import aggregate, combine_history, read_m1, live_frame


def payload(now, n=2000, age=0):
    idx = pd.date_range(end=now-timedelta(minutes=1), periods=n, freq="min", tz="UTC")
    rows = []
    for t in idx:
        rows.append({"timestamp": t.isoformat(), "open": 4000., "high": 4001.,
                     "low": 3999., "close": 4000.})
    return {"contract": "RIZAN_MANUAL_R3_MARKET_V1", "symbol": "XAUUSD",
            "source": "CTRADER_MARKET_DATA_READ_ONLY",
            "execution_authority": False, "execution_influence": False,
            "as_of": (now-timedelta(seconds=age)).isoformat(), "m1": rows}


def test_complete_m1_only_and_contiguous_h1_close():
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    frame, meta = read_m1(now=now, payload=payload(now))
    assert len(frame) == 2000 and meta["bars"] == 2000
    h1 = aggregate(frame, "1h", now=now)
    assert len(h1) >= 30 and h1.index[-1] + pd.Timedelta(hours=1) <= now
    h4 = aggregate(frame, "4h", now=now)
    assert len(h4) >= 7
    assert h1.index.tz is not None


def test_no_late_publication_or_synthetic_incomplete_data():
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    with pytest.raises(ValueError, match="STALE"):
        read_m1(now=now, payload=payload(now, age=180))
    p = payload(now)
    p["m1"][-1]["close"] = 100_000.
    with pytest.raises(ValueError, match="CANDLE_INVALID"):
        read_m1(now=now, payload=p)
    p = payload(now)
    p["execution_authority"] = True
    with pytest.raises(ValueError, match="CONTRACT"):
        read_m1(now=now, payload=p)


def test_join_requires_scale_and_source_continuity():
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    frame, _ = read_m1(now=now, payload=payload(now))
    h1 = aggregate(frame, "1h", now=now)
    prior = h1.iloc[:-5].copy()
    result = combine_history(prior, h1, "1h")
    assert result is not None and len(result) == len(h1)
    bad = prior.copy()
    bad["c"] = 1000.
    assert combine_history(bad, h1, "1h") is None
    gap = prior.copy()
    gap.index = gap.index - pd.Timedelta(days=10)
    assert combine_history(gap, h1, "1h") is None


def test_fresh_market_frame_is_never_an_order():
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    frame, _ = read_m1(now=now, payload=payload(now))
    h1 = aggregate(frame, "1h", now=now)
    combined, meta = live_frame(h1.iloc[:-10], "1h", now=now, payload=payload(now))
    assert combined is not None and meta["status"] == "VALID_CTRADER_READONLY"
    assert meta["source"] == "CTRADER_MARKET_DATA_READ_ONLY"
