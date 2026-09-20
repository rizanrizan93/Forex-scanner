from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_xau_v24_champion_candidate_producer import (
    D1_COMPONENT,
    D1_MAX_HOLD_BARS,
    L12_COMPONENT,
    L20_COMPONENT,
    M15_MAX_HOLD_BARS,
    STRATEGY_ID,
    ChampionCandidate,
    _COMPONENT_SPEC,
    _d1_candidate,
    _dedupe,
)
from fx_scanner.demo_xau_v24_champion_time_exit import _COMPONENT_CONTRACTS
from fx_scanner.models import Bar

UTC = timezone.utc


def _d1_rows(*, rising: bool) -> tuple[Bar, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(202):
        base = 2000.0 + i * 2.5 if rising else 3000.0 - i * 2.5
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe="D1",
                timestamp=start + timedelta(days=i),
                open=base,
                high=base + 8.0,
                low=base - 8.0,
                close=base + (2.0 if rising else -2.0),
                tick_count=100,
                spread_avg=0.1,
                spread_max=0.2,
            )
        )
    return tuple(rows)


@pytest.mark.parametrize(("rising", "direction"), [(True, "LONG"), (False, "SHORT")])
def test_v24_d1_candidate_preserves_staggered_two_atr_two_r_contract(rising, direction):
    rows = _d1_rows(rising=rising)
    now = rows[-1].timestamp + timedelta(minutes=5)
    candidate = _d1_candidate(rows, now=now)

    assert candidate is not None
    assert candidate.component_id == D1_COMPONENT
    assert candidate.direction == direction
    assert candidate.entry_at == rows[-1].timestamp
    risk = abs(candidate.entry_price - candidate.stop_loss)
    reward = abs(candidate.take_profit - candidate.entry_price)
    assert risk == pytest.approx(2.0 * candidate.atr)
    assert reward / risk == pytest.approx(2.0)
    assert candidate.max_hold_bars == 30


def test_v24_component_contract_is_frozen_and_dedupe_prefers_l20_then_d1_then_l12():
    assert STRATEGY_ID == "XAU_V24_CHAMPION_DEMO_V1"
    assert _COMPONENT_SPEC[D1_COMPONENT]["priority"] == 2
    assert _COMPONENT_SPEC[L12_COMPONENT]["priority"] == 1
    assert _COMPONENT_SPEC[L20_COMPONENT]["priority"] == 3
    assert _COMPONENT_SPEC[L12_COMPONENT]["lookback"] == 12
    assert _COMPONENT_SPEC[L12_COMPONENT]["h1_adx_min"] == 12.0
    assert _COMPONENT_SPEC[L12_COMPONENT]["reward_r"] == 1.5
    assert _COMPONENT_SPEC[L20_COMPONENT]["lookback"] == 20
    assert _COMPONENT_SPEC[L20_COMPONENT]["h1_adx_min"] == 15.0
    assert _COMPONENT_SPEC[L20_COMPONENT]["reward_r"] == 2.0

    at = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
    base = dict(
        direction="LONG",
        signal_bar_at=at - timedelta(minutes=15),
        entry_at=at,
        entry_price=4400.0,
        stop_loss=4390.0,
        take_profit=4420.0,
        reward_r=2.0,
        atr=5.0,
    )
    d1 = ChampionCandidate(component_id=D1_COMPONENT, **base)
    l12 = ChampionCandidate(component_id=L12_COMPONENT, **{**base, "reward_r": 1.5})
    l20 = ChampionCandidate(component_id=L20_COMPONENT, **base)
    selected = _dedupe((l12, d1, l20))
    assert len(selected) == 1
    assert selected[0].component_id == L20_COMPONENT


def test_v24_time_exit_contracts_match_research_horizons():
    assert D1_MAX_HOLD_BARS == 30
    assert M15_MAX_HOLD_BARS == 16
    assert _COMPONENT_CONTRACTS[D1_COMPONENT] == ("D1", 86400, 30)
    assert _COMPONENT_CONTRACTS[L12_COMPONENT] == ("M15", 900, 16)
    assert _COMPONENT_CONTRACTS[L20_COMPONENT] == ("M15", 900, 16)
