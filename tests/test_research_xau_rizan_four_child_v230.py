from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_rizan_four_child_v230 import (
    _child_result,
    _limit_side_valid,
    _price_index,
    summarize_children,
)


def _frame(rows):
    return pd.DataFrame(
        [
            {
                "timestamp": datetime(2026,1,1,tzinfo=UTC)+timedelta(minutes=i),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }
            for i,(o,h,l,c) in enumerate(rows)
        ]
    )


def test_v230_limit_side_requires_true_limit_geometry():
    assert _limit_side_valid("LONG", 99.0, 100.0)
    assert not _limit_side_valid("LONG", 100.0, 100.0)
    assert _limit_side_valid("SHORT", 101.0, 100.0)
    assert not _limit_side_valid("SHORT", 100.0, 100.0)


def test_v230_same_m1_bar_stop_and_tp_uses_stop_first():
    frame=_frame([
        (101.0,101.2,100.8,101.0),
        (100.5,103.0,97.0,100.0),
    ])
    px=_price_index(frame)
    result=_child_result(
        year=2026,
        parent_zone_id="h4",
        direction="LONG",
        source_layer="H4_HISTORICAL_HOTSPOT",
        slot=1,
        stage="PRE_TOUCH_LIMIT_REFERENCE",
        activation="PRE_TOUCH_LIMIT",
        activated_at=frame.iloc[0]["timestamp"],
        entry=100.0,
        stop=98.0,
        target=102.0,
        target_timeframe="M15",
        target_zone_id="supply",
        px_index=px,
        cancel_at=frame.iloc[-1]["timestamp"]+timedelta(minutes=1),
    )
    assert result.filled_at is not None
    assert result.outcome=="SL"
    assert result.exit_price==98.0
    assert result.pnl_points==-2.0
    assert result.r_multiple==-1.0


def test_v230_target_hit_calculates_fixed_001_lot_usd_equivalent():
    frame=_frame([
        (101.0,101.1,100.8,101.0),
        (100.5,100.8,99.9,100.4),
        (100.5,103.0,100.2,102.5),
    ])
    px=_price_index(frame)
    result=_child_result(
        year=2026,
        parent_zone_id="h4",
        direction="LONG",
        source_layer="M15_NESTED_LOCATOR",
        slot=1,
        stage="PRE_TOUCH_LIMIT_REFERENCE",
        activation="PRE_TOUCH_LIMIT",
        activated_at=frame.iloc[0]["timestamp"],
        entry=100.0,
        stop=98.0,
        target=102.0,
        target_timeframe="M15",
        target_zone_id="supply",
        px_index=px,
        cancel_at=frame.iloc[-1]["timestamp"]+timedelta(minutes=1),
    )
    assert result.outcome=="TP"
    assert result.pnl_points==2.0
    assert result.pnl_usd_001==2.0
    assert result.r_multiple==1.0


def test_v230_summary_separates_slots_and_cost_stress():
    parents=[{"year":2026,"source_layer":"M15_NESTED_LOCATOR"}]
    children=[
        {
            "slot":1,"activated_at":"2026-01-01T00:00:00+00:00",
            "filled_at":"2026-01-01T00:01:00+00:00","exit_at":"2026-01-01T00:02:00+00:00",
            "outcome":"TP","pnl_points":2.0,"pnl_usd_001":2.0,"r_multiple":1.0,
            "target_timeframe":"M15",
        },
        {
            "slot":2,"activated_at":"2026-01-01T00:00:00+00:00",
            "filled_at":"2026-01-01T00:01:00+00:00","exit_at":"2026-01-01T00:03:00+00:00",
            "outcome":"SL","pnl_points":-1.0,"pnl_usd_001":-1.0,"r_multiple":-1.0,
            "target_timeframe":"H1",
        },
        {
            "slot":3,"activated_at":None,"filled_at":None,"exit_at":None,
            "outcome":"NOT_ACTIVATED_OR_NO_TARGET","pnl_points":None,"pnl_usd_001":None,
            "r_multiple":None,"target_timeframe":None,
        },
        {
            "slot":4,"activated_at":None,"filled_at":None,"exit_at":None,
            "outcome":"NOT_ACTIVATED_OR_NO_TARGET","pnl_points":None,"pnl_usd_001":None,
            "r_multiple":None,"target_timeframe":None,
        },
    ]
    summary=summarize_children(children,parents=parents)
    assert summary["children_filled"]==2
    assert summary["tp"]==1
    assert summary["sl"]==1
    assert summary["gross_pnl_usd_001"]==1.0
    assert summary["profit_factor"]==2.0
    assert summary["cost_stress"]["0.5"]["net_pnl_usd_001"]==0.0
