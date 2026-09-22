from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.models import Bar
from fx_scanner.research_xau_afic_independent_path_confirm_v166 import (
    CANDIDATE_RULE,
    CONTROL_RULE,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    PROMOTION_ELIGIBLE,
    RULES,
    _confirmation_fires,
    _map_stub,
)
from fx_scanner.research_xau_afic_h4_map_selector_v161 import (
    PRIMARY_SELECTOR,
    _selected,
)

UTC = timezone.utc


def _bar(ts, o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=ts,
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        tick_count=1,
        spread_avg=0.1,
        spread_max=0.1,
    )


def test_v166_is_research_only_and_two_rule_preregistered_comparison():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert RULES == (CONTROL_RULE, CANDIDATE_RULE)
    assert CONTROL_RULE == "STRICT_ENGULF_REJECT"
    assert CANDIDATE_RULE == "DIRECTIONAL_REJECTION"


def test_directional_rejection_can_fire_without_strict_engulf():
    zone = SimpleNamespace(direction="SHORT", low=100.0, high=105.0)
    rows = (
        _bar(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), 103, 104, 101, 102),
        _bar(datetime(2026, 1, 1, 0, 15, tzinfo=UTC), 104, 106, 99, 99.5),
    )
    assert _confirmation_fires(rows, 1, zone, CANDIDATE_RULE) is True
    assert _confirmation_fires(rows, 1, zone, CONTROL_RULE) is False


def test_map_stub_preserves_v161_frozen_selector_contract():
    zone = SimpleNamespace(high=100.0, low=95.0)
    stub = _map_stub(
        map_at=datetime(2026, 1, 1, tzinfo=UTC),
        continuation="LONG",
        zone=zone,
        price=102.0,
    )
    assert stub.continuation_direction == "LONG"
    assert PRIMARY_SELECTOR == "NEAR_WEAK_H4_CLOSE"
    assert _selected(
        {
            "zone_distance_atr": 0.75,
            "h4_directional_close_location": 0.65,
        },
        PRIMARY_SELECTOR,
    )
    assert not _selected(
        {
            "zone_distance_atr": 0.76,
            "h4_directional_close_location": 0.65,
        },
        PRIMARY_SELECTOR,
    )
    assert not _selected(
        {
            "zone_distance_atr": 0.75,
            "h4_directional_close_location": 0.66,
        },
        PRIMARY_SELECTOR,
    )
