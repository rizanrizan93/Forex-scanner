from datetime import UTC, datetime

import pandas as pd

from fx_scanner.research_xau_histdata_download_v193 import (
    _date_window,
    _normalize_frame,
)


def test_histdata_fixed_est_is_normalized_to_utc():
    frame = pd.DataFrame(
        {
            "datetime": ["20120103 083000", "20120103 083100"],
            "open": [1600.0, 1601.0],
            "high": [1601.0, 1602.0],
            "low": [1599.0, 1600.0],
            "close": [1600.5, 1601.5],
            "volume": [0.0, 0.0],
        }
    )
    out = _normalize_frame(frame)
    assert out["timestamp"].iloc[0].to_pydatetime() == datetime(
        2012, 1, 3, 13, 30, tzinfo=UTC
    )
    assert out["timestamp"].iloc[1].to_pydatetime() == datetime(
        2012, 1, 3, 13, 31, tzinfo=UTC
    )


def test_histdata_window_covers_pre_event_conditioning():
    start, end = _date_window(2012)
    assert start.isoformat() == "2011-10-01"
    assert end.isoformat() == "2013-01-02"


def test_histdata_ohlc_validation_rejects_inconsistent_row():
    frame = pd.DataFrame(
        {
            "datetime": ["20120103 083000"],
            "open": [1600.0],
            "high": [1599.0],
            "low": [1598.0],
            "close": [1600.5],
            "volume": [0.0],
        }
    )
    try:
        _normalize_frame(frame)
    except RuntimeError as exc:
        assert "OHLC validation failed" in str(exc)
    else:
        raise AssertionError("expected inconsistent OHLC to fail")
