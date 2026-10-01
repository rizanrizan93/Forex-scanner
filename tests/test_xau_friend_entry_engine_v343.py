from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.xau_friend_entry_engine_v343 import (
    DELTA_FRACTION,
    HISTORICAL_EVIDENCE,
    evaluate_friend_entry,
)


def _m5():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        SimpleNamespace(
            timestamp=start + timedelta(minutes=5 * i),
            open=2000.0 + i * 0.1,
            high=2001.0 + i * 0.1,
            low=1999.0 + i * 0.1,
            close=2000.2 + i * 0.1,
        )
        for i in range(40)
    ]


def test_v343_waits_for_parent_touch_instead_of_inventing_anchor():
    parent = {
        "direction": "LONG",
        "low": 1990.0,
        "high": 2000.0,
        "proximal": 1998.0,
        "distal": 1990.0,
        "lifecycle": {"touch_count": 0},
    }
    result = evaluate_friend_entry(
        parent_zone=parent,
        bars_m5=_m5(),
        as_of=datetime(2026, 9, 2, tzinfo=UTC),
        price_now=2005.0,
    )
    assert result["state"] == "WAIT_PARENT_TOUCH"
    assert result["execution_authority"] is False
    assert "A -> X=A" in result["formula"]


def test_v343_historical_selection_is_shadow_only():
    assert DELTA_FRACTION == 0.10
    assert HISTORICAL_EVIDENCE["selected_candidate"] == "D0.10|Y|TP5"
    assert HISTORICAL_EVIDENCE["oos_gate_pass"] is False
    assert HISTORICAL_EVIDENCE["oos_2025_2026"]["expectancy_r_all_fills"] < 0.10
