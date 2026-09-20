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
from fx_scanner.demo_xau_v24_champion_time_exit import (
    _COMPONENT_CONTRACTS,
    _completed_utc_d1_bars_since_open,
)
from fx_scanner.demo_xau_v24_utc_d1_context import UtcD1Context
from fx_scanner.models import Bar

UTC = timezone.utc


def _m15_bar(timestamp: datetime, price: float = 4400.0) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=timestamp,
        open=price,
        high=price + 2.0,
        low=price - 2.0,
        close=price + 1.0,
        tick_count=100,
        spread_avg=0.1,
        spread_max=0.2,
    )


@pytest.mark.parametrize(("direction", "entry_price"), [("LONG", 4400.0), ("SHORT", 4400.0)])
def test_v24_d1_candidate_preserves_utc_staggered_two_atr_two_r_contract(direction, entry_price):
    target_day = datetime(2026, 9, 21, tzinfo=UTC).date()
    signal_day = target_day - timedelta(days=1)
    context = UtcD1Context(
        target_day=target_day,
        signal_day=signal_day,
        direction=direction,
        atr14=10.0,
        ema200=4300.0,
        ret60=0.10 if direction == "LONG" else -0.10,
        close=4400.0,
        closes_tail=tuple(4300.0 + i for i in range(61)),
        history_days=500,
        seed_day=target_day - timedelta(days=700),
        source="TEST",
    )
    entry_at = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
    candidate = _d1_candidate(
        context,
        (_m15_bar(entry_at, entry_price),),
        now=entry_at + timedelta(minutes=5),
    )

    assert candidate is not None
    assert candidate.component_id == D1_COMPONENT
    assert candidate.direction == direction
    assert candidate.signal_bar_at == datetime.combine(signal_day, datetime.min.time(), tzinfo=UTC)
    assert candidate.entry_at == entry_at
    risk = abs(candidate.entry_price - candidate.stop_loss)
    reward = abs(candidate.take_profit - candidate.entry_price)
    assert risk == pytest.approx(20.0)
    assert reward / risk == pytest.approx(2.0)
    assert candidate.max_hold_bars == 30


def test_v24_d1_candidate_uses_first_available_m15_bar_of_utc_target_day():
    target_day = datetime(2026, 9, 20, tzinfo=UTC).date()
    context = UtcD1Context(
        target_day=target_day,
        signal_day=target_day - timedelta(days=2),
        direction="LONG",
        atr14=8.0,
        ema200=4300.0,
        ret60=0.08,
        close=4400.0,
        closes_tail=tuple(4300.0 + i for i in range(61)),
        history_days=500,
        seed_day=target_day - timedelta(days=700),
        source="TEST",
    )
    sunday_open = datetime(2026, 9, 20, 21, 0, tzinfo=UTC)
    bars = (
        _m15_bar(sunday_open, 4450.0),
        _m15_bar(sunday_open + timedelta(minutes=15), 4452.0),
    )
    candidate = _d1_candidate(context, bars, now=sunday_open + timedelta(minutes=5))
    assert candidate is not None
    assert candidate.entry_at == sunday_open
    assert candidate.entry_price == 4450.0


class _H1Session:
    def __init__(self, rows):
        self.rows = tuple(rows)

    def historical_bars(self, symbol, timeframe, *, from_time, to_time, count):
        assert symbol == "XAUUSD"
        assert timeframe == "H1"
        return tuple(
            row
            for row in self.rows
            if from_time <= row.timestamp < to_time
        )


def test_v24_d1_time_exit_counts_completed_utc_trading_days_not_broker_d1():
    opened = datetime(2026, 9, 20, 21, 0, tzinfo=UTC)
    rows = []
    for day in (
        datetime(2026, 9, 20, tzinfo=UTC),
        datetime(2026, 9, 21, tzinfo=UTC),
        datetime(2026, 9, 22, tzinfo=UTC),
    ):
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe="H1",
                timestamp=day + timedelta(hours=21 if day.date() == opened.date() else 0),
                open=4400.0,
                high=4410.0,
                low=4390.0,
                close=4405.0,
                tick_count=100,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    session = _H1Session(rows)
    assert _completed_utc_d1_bars_since_open(
        session,
        opened_at=opened,
        now=datetime(2026, 9, 23, 0, 1, tzinfo=UTC),
    ) == 3


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



def test_v24_forward_adapter_is_demo_only_and_has_no_live_unlock():
    from pathlib import Path

    source = Path("src/fx_scanner/demo_xau_v24_champion_candidate_producer.py").read_text()
    workflow = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert 'mode="DEMO_ONLY"' in source
    assert '"live_execution_enabled": False' in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow



def test_v24_forward_adapter_never_fetches_broker_native_d1():
    from pathlib import Path

    source = Path("src/fx_scanner/demo_xau_v24_champion_candidate_producer.py").read_text()
    assert "raw_d1" not in source
    assert '"d1_source": "UTC_CALENDAR_D1_FROM_CTRADER_H1_PARITY_V124"' in source
    assert '"XAU_V24_CHAMPION_FORWARD_V2_UTC_D1"' in source
