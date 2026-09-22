from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.models import Bar
from fx_scanner.research_xau_afic_m15_confirm_semantics_v165 import (
    CONTROL_RULE,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    PROMOTION_ELIGIBLE,
    RULES,
    _directional_rejection,
    _sweep_reclaim,
)

UTC = timezone.utc


def _bar(o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        tick_count=1,
        spread_avg=0.1,
        spread_max=0.1,
    )


def test_v165_is_diagnostic_only_and_keeps_strict_control():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert CONTROL_RULE == "STRICT_ENGULF_REJECT"
    assert RULES == (
        "STRICT_ENGULF_REJECT",
        "DIRECTIONAL_REJECTION",
        "SWEEP_RECLAIM",
    )


def test_directional_rejection_short_requires_bear_close_beyond_proximal_edge():
    zone = SimpleNamespace(direction="SHORT", low=4351.0, high=4357.0)
    assert _directional_rejection((_bar(4356, 4358, 4349, 4350),), 0, zone)
    assert not _directional_rejection((_bar(4350, 4358, 4349, 4355),), 0, zone)


def test_sweep_reclaim_short_requires_distal_wick_and_close_back_inside():
    zone = SimpleNamespace(direction="SHORT", low=4351.0, high=4357.0)
    assert _sweep_reclaim((_bar(4356, 4358, 4354, 4356),), 0, zone)
    assert not _sweep_reclaim((_bar(4356, 4358, 4354, 4357.5),), 0, zone)
