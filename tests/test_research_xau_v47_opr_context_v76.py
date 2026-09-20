from datetime import datetime, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_v47_opr_context_v76 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    OPR_ATR_BUCKETS,
    OPR_MINUTES,
    POLICY_EFFECT,
    POSITION_STATES,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    build_opr_days,
)

UTC = timezone.utc


def _bar(ts, *, high=101.0, low=99.0, open_=100.0, close=100.5):
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_v76_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v76_opr_contract():
    assert OPR_MINUTES == 15
    assert POSITION_STATES == ("ABOVE", "INSIDE", "BELOW", "UNAVAILABLE")
    assert OPR_ATR_BUCKETS == (
        "LE_0_25",
        "GT_0_25_LE_0_50",
        "GT_0_50",
        "UNAVAILABLE",
    )


def test_v76_new_york_dst_mapping_and_availability():
    # 2026-09-18 is EDT, so 09:30 New York = 13:30 UTC.
    bar = _bar(datetime(2026, 9, 18, 13, 30, tzinfo=UTC))
    days = build_opr_days((bar,))
    row = days["2026-09-18"]
    assert row.source_bar_at.isoformat() == "2026-09-18T13:30:00+00:00"
    assert row.available_at.isoformat() == "2026-09-18T13:45:00+00:00"
