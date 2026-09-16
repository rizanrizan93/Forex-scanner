from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_xau_m15_ema_reversal_recovery import STRATEGY_ID as EMA_STRATEGY_ID
from fx_scanner.demo_xau_m15_liquidity_sweep_fade import STRATEGY_ID as SWEEP_STRATEGY_ID
from fx_scanner.models import Bar
from fx_scanner.research_xau_m15_dual_strategy import (
    MAX_HOLD_BARS,
    M15ResearchCosts,
    SignalEvent,
    extract_signal_events,
    infer_spread_proxy_pips,
    simulate_hold_variant,
)

UTC = timezone.utc


def _bar(index: int, *, open_: float, high: float, low: float, close: float, spread: float = 0.02) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=100 + index,
        spread_avg=spread,
        spread_max=spread,
    )


def _ema_reversal_long_with_next_bar() -> tuple[Bar, ...]:
    rows = []
    for index in range(221):
        close = 4400.0 - 0.2 * index
        open_ = close + 0.1
        rows.append(
            _bar(
                index,
                open_=open_,
                high=max(open_, close) + 0.4,
                low=min(open_, close) - 0.4,
                close=close,
            )
        )
    for close in (4354.0, 4352.0, 4350.0, 4348.0, 4346.0, 4344.0, 4342.0, 4338.0):
        index = len(rows)
        open_ = close + 1.0
        rows.append(
            _bar(
                index,
                open_=open_,
                high=open_ + 0.5,
                low=close - 0.8,
                close=close,
            )
        )
    index = len(rows)
    rows.append(_bar(index, open_=4337.0, high=4342.0, low=4336.5, close=4341.0))
    index = len(rows)
    rows.append(_bar(index, open_=4341.2, high=4342.0, low=4340.5, close=4341.5))
    return tuple(rows)


def test_preregistered_holds_are_locked_to_4_8_16_24_hours():
    assert MAX_HOLD_BARS == (16, 32, 64, 96)


def test_spread_proxy_requires_broker_evidence_instead_of_zero_cost_fallback():
    rows = (
        _bar(0, open_=100, high=101, low=99, close=100, spread=0.0),
        _bar(1, open_=100, high=101, low=99, close=100, spread=0.0),
    )
    evidence = infer_spread_proxy_pips(rows)
    assert evidence["available"] is False
    assert evidence["median_pips"] is None


def test_research_detector_reproduces_runtime_ema_reversal_geometry():
    events = extract_signal_events(_ema_reversal_long_with_next_bar())
    ema = events[EMA_STRATEGY_ID]

    assert ema
    assert ema[-1].direction == "LONG"
    assert ema[-1].reward_r == pytest.approx(3.0)
    assert ema[-1].signal_index == len(_ema_reversal_long_with_next_bar()) - 2
    assert events[SWEEP_STRATEGY_ID] is not None


def _outcome_bars(*, ambiguous: bool) -> tuple[Bar, ...]:
    rows = []
    for index in range(20):
        open_ = 100.0
        high = 100.4
        low = 99.6
        close = 100.0
        if index == 6:
            open_ = 100.0
            high = 102.1
            low = 99.5 if not ambiguous else 98.9
            close = 101.5
        rows.append(_bar(index, open_=open_, high=high, low=low, close=close))
    return tuple(rows)


def _event() -> SignalEvent:
    return SignalEvent(
        strategy_id=SWEEP_STRATEGY_ID,
        signal_index=4,
        direction="LONG",
        signal_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        atr=1.0,
        structural_stop=99.0,
        reward_r=1.8,
    )


def test_target_on_entry_bar_is_not_counted_but_next_bar_target_is():
    rows = list(_outcome_bars(ambiguous=False))
    rows[5] = _bar(5, open_=100.0, high=102.5, low=99.5, close=101.0)
    trades = simulate_hold_variant(
        tuple(rows),
        events=(_event(),),
        max_hold_bars=16,
        costs=M15ResearchCosts(2.0, 0.2, 0.2, 0.0),
    )

    assert len(trades) == 1
    assert trades[0].exit_index == 6
    assert trades[0].exit_reason == "TARGET_HIT"
    assert trades[0].gross_r == pytest.approx(1.8)
    assert trades[0].net_r < trades[0].gross_r


def test_same_bar_stop_and_target_is_scored_stop_first():
    trades = simulate_hold_variant(
        _outcome_bars(ambiguous=True),
        events=(_event(),),
        max_hold_bars=16,
        costs=M15ResearchCosts(2.0, 0.2, 0.2, 0.0),
    )

    assert len(trades) == 1
    assert trades[0].exit_reason == "STOP_FIRST_AMBIGUOUS"
    assert trades[0].gross_r == pytest.approx(-1.0)
    assert trades[0].net_r < -1.0
