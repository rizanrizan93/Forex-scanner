from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_five_core_router import (
    D1_MAX_HOLD_BARS,
    EXECUTION_SYMBOLS,
    FIVE_CORE_SYMBOLS,
    FORWARD_DEMO_SCORE,
    NO_TRADE_SYMBOLS,
    PAIR_STRATEGY_IDS,
    SHADOW_SYMBOLS,
    build_xau_d1_tsmom_plan,
    evaluate_xau_d1_tsmom_60_200,
)
from fx_scanner.demo_trade_plan_geometry import plan_geometry_evidence
from fx_scanner.models import Bar

UTC = timezone.utc


def _d1_bars(*, rising: bool) -> tuple[Bar, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(201):
        base = 2000.0 + i * 2.0 if rising else 3000.0 - i * 2.0
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe="D1",
                timestamp=start + timedelta(days=i),
                open=base,
                high=base + 10.0,
                low=base - 10.0,
                close=base + (2.0 if rising else -2.0),
                tick_count=100,
                spread_avg=0.1,
                spread_max=0.2,
            )
        )
    return tuple(rows)


def test_five_core_registry_is_exact_and_fail_closed():
    assert FIVE_CORE_SYMBOLS == ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
    assert EXECUTION_SYMBOLS == {"XAUUSD"}
    assert SHADOW_SYMBOLS == {"USDJPY"}
    assert NO_TRADE_SYMBOLS == {"EURUSD", "GBPUSD", "AUDUSD"}
    assert PAIR_STRATEGY_IDS["XAUUSD"] == "D1_TSMOM_60_200"
    assert PAIR_STRATEGY_IDS["USDJPY"] == "H4_COMPRESSION_BREAKOUT"
    assert FORWARD_DEMO_SCORE == 60.0
    assert D1_MAX_HOLD_BARS == 30


@pytest.mark.parametrize(
    ("rising", "expected"),
    [(True, "LONG"), (False, "SHORT")],
)
def test_xau_d1_tsmom_uses_completed_bar_and_next_d1_open(rising, expected):
    bars = _d1_bars(rising=rising)
    next_open = bars[-1].timestamp
    signal = evaluate_xau_d1_tsmom_60_200(
        bars,
        as_of=next_open + timedelta(minutes=10),
    )
    assert signal.active is True
    assert signal.execution_eligible is True
    assert signal.direction == expected
    assert signal.strategy_id == "D1_TSMOM_60_200"
    assert signal.next_entry_at == next_open
    assert signal.signal_bar_at == bars[-2].timestamp
    assert signal.reason == "ENTRY_WINDOW_ACTIVE"
    assert signal.atr is not None and signal.atr > 0


def test_xau_d1_signal_expires_after_entry_window():
    bars = _d1_bars(rising=True)
    signal = evaluate_xau_d1_tsmom_60_200(
        bars,
        as_of=bars[-1].timestamp + timedelta(minutes=31),
    )
    assert signal.active is False
    assert signal.direction == "LONG"
    assert signal.reason == "WAIT_NEXT_D1_OPEN"


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_xau_plan_matches_frozen_two_r_contract(direction):
    bars = _d1_bars(rising=(direction == "LONG"))
    signal = evaluate_xau_d1_tsmom_60_200(
        bars,
        as_of=bars[-1].timestamp + timedelta(minutes=5),
    )
    assert signal.direction == direction and signal.active
    plan = build_xau_d1_tsmom_plan(signal, current_price=2500.0)
    assert plan.rr2 == pytest.approx(2.0)
    assert plan.tp1 is None and plan.rr1 is None
    if direction == "LONG":
        assert plan.stop_loss < plan.entry_low < plan.entry_high < plan.tp2
    else:
        assert plan.tp2 < plan.entry_low < plan.entry_high < plan.stop_loss
    evidence = plan_geometry_evidence(plan)
    assert evidence is not None
    assert evidence.entry_mode == "D1_TSMOM_60_200"
    assert evidence.exit_model == "D1_FIXED_ATR_STOP_TARGET_MAX30"
