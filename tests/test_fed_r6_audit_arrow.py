"""Regression: Fed R6 macro audit table is Arrow-safe with mixed source values."""

import pandas as pd
import pyarrow as pa

from fx_scanner.fed_r6_manual_entry_dashboard import (
    _audit_change,
    _macro_audit_rows,
)


def test_mixed_futures_proxy_and_numeric_delta_serializes_without_arrowinvalid():
    context = {
        "daily_yields": {
            "US2Y": {
                "yield_pct": 4.76,
                "daily_delta_bps": -4,
                "provider": "US_TREASURY_DAILY_XML",
                "observed_at": "2026-11-19T00:00:00Z",
                "valid_official_daily": True,
            },
            "US10Y": {
                "yield_pct": 5.04,
                "daily_delta_bps": None,
                "provider": None,
                "observed_at": None,
                "valid_official_daily": False,
            },
        },
        "dxy": {
            "current": 103.886,
            "change_pct": 0.0038,
            "source": "YAHOO_FINANCE_ICE_DXY_PROXY",
            "observed_at": "2026-11-20T02:48:00Z",
            "fresh": True,
        },
        "intraday_yield": {
            "futures_price": 106.125,
            "pressure": "YIELD_DOWN_PROXY",
            "basis": "TREASURY_FUTURES_PROXY",
            "observed_at": "2026-11-20T02:48:30Z",
            "available_for_direction": True,
        },
    }
    rows = _macro_audit_rows(context)
    assert [r["Perubahan"] for r in rows] == [
        "-4.00 bps", "—", "+0.0038 %", "YIELD_DOWN_PROXY"
    ]
    assert all(isinstance(cell, str) for row in rows for cell in row.values())
    df = pd.DataFrame(rows)
    table = pa.Table.from_pandas(df, preserve_index=False)
    assert table.num_rows == 4
    assert table.schema.field("Perubahan").type == pa.string()


def test_empty_and_nonfinite_delta_are_arrow_safe():
    assert _audit_change("", "bps") == "—"
    assert _audit_change(None, "%") == "—"
    assert _audit_change(float("nan"), "bps") == "—"
    assert _audit_change(float("inf"), "bps") == "—"
    assert _audit_change("YIELD_UP_PROXY") == "YIELD_UP_PROXY"
    rows = _macro_audit_rows({
        "dxy": {"change_pct": "", "current": None},
        "intraday_yield": {"pressure": "YIELD_UP_PROXY", "futures_price": None},
    })
    pa.Table.from_pylist(rows)
    assert rows[0]["Perubahan"] == "—"
    assert rows[1]["Perubahan"] == "YIELD_UP_PROXY"
