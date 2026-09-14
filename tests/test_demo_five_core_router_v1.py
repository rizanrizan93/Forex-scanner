from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_five_core_authority import (
    AUTHORITY_CONTRACT,
    DEMOTION_REASON,
    EXECUTION_SYMBOLS,
    PREVIOUS_DEMOTION_REASON,
    PROMOTION_REASON,
    SHADOW_SYMBOLS,
    execution_authorized,
)
from fx_scanner.demo_five_core_candidate_producer import (
    HISTORY_WINDOW_CALENDAR_FACTOR,
    _history_window_seconds,
)
from fx_scanner.demo_five_core_router import (
    D1_MAX_HOLD_BARS,
    FIVE_CORE_SYMBOLS,
    FORWARD_DEMO_SCORE,
    H4_MAX_HOLD_BARS,
    FiveCoreSignal,
    NO_TRADE_SYMBOLS,
    PAIR_STRATEGY_IDS,
    build_gbpusd_h4_mean_revert_plan,
    build_usdjpy_d1_donchian55_plan,
    build_xau_d1_tsmom_plan,
    evaluate_usdjpy_d1_donchian55_200,
    evaluate_xau_d1_tsmom_60_200,
)
from fx_scanner.demo_trade_plan_geometry import plan_geometry_evidence
from fx_scanner.models import Bar

UTC = timezone.utc


def _d1_bars(*, symbol: str = "XAUUSD", rising: bool) -> tuple[Bar, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(201):
        base = 100.0 + i * 0.20 if symbol == "USDJPY" else 2000.0 + i * 2.0
        if not rising:
            base = (200.0 - i * 0.20) if symbol == "USDJPY" else (3000.0 - i * 2.0)
        span = 0.10 if symbol == "USDJPY" else 10.0
        drift = 0.03 if symbol == "USDJPY" else 2.0
        rows.append(
            Bar(
                symbol=symbol,
                timeframe="D1",
                timestamp=start + timedelta(days=i),
                open=base,
                high=base + span,
                low=base - span,
                close=base + (drift if rising else -drift),
                tick_count=100,
                spread_avg=0.1,
                spread_max=0.2,
            )
        )
    return tuple(rows)


def test_five_core_registry_and_pair_specific_demo_authority_are_exact():
    assert FIVE_CORE_SYMBOLS == ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
    assert EXECUTION_SYMBOLS == frozenset(
        {"XAUUSD", "USDJPY", "GBPUSD", "EURAUD", "GBPAUD"}
    )
    assert SHADOW_SYMBOLS == frozenset()
    assert NO_TRADE_SYMBOLS == frozenset({"EURUSD", "AUDUSD"})
    assert PAIR_STRATEGY_IDS["XAUUSD"] == "D1_TSMOM_60_200"
    assert PAIR_STRATEGY_IDS["USDJPY"] == "D1_DONCHIAN55_200"
    assert PAIR_STRATEGY_IDS["GBPUSD"] == "H4_MEAN_REVERT_Z2_TO_SMA20"
    assert FORWARD_DEMO_SCORE == 60.0
    assert D1_MAX_HOLD_BARS == 30
    assert H4_MAX_HOLD_BARS == 12
    assert execution_authorized("XAUUSD") is True
    assert execution_authorized("USDJPY") is True
    assert execution_authorized("GBPUSD") is True
    assert execution_authorized("EURAUD") is True
    assert execution_authorized("GBPAUD") is True
    assert execution_authorized("EURUSD") is False
    assert execution_authorized("AUDUSD") is False
    assert AUTHORITY_CONTRACT == "PAIR_SPECIFIC_DEMO_AUTHORITY_V4_EURAUD_GBPAUD"
    assert PREVIOUS_DEMOTION_REASON == "PREREGISTERED_XAU_ROLLING_STABILITY_GATE_FAILED"
    assert PROMOTION_REASON == "USER_AUTHORIZED_DEMO_TRADING_DATA_COLLECTION"
    assert DEMOTION_REASON == "SUPERSEDED_BY_PAIR_SPECIFIC_DEMO_AUTHORITY_V4"


def test_slow_history_window_pads_24x5_calendar_gaps_without_expanding_fast_timeframes():
    count = 232
    d1_seconds = 24 * 60 * 60
    h4_seconds = 4 * 60 * 60
    m5_seconds = 5 * 60
    assert HISTORY_WINDOW_CALENDAR_FACTOR == {"D1": 1.65, "H4": 1.65}
    assert _history_window_seconds("D1", count, d1_seconds) == pytest.approx(d1_seconds * (count + 12) * 1.65)
    assert _history_window_seconds("H4", count, h4_seconds) == pytest.approx(h4_seconds * (count + 12) * 1.65)
    assert _history_window_seconds("M5", count, m5_seconds) == pytest.approx(m5_seconds * (count + 12))
    assert _history_window_seconds("D1", count, d1_seconds) > 365 * d1_seconds


@pytest.mark.parametrize(("rising", "expected"), [(True, "LONG"), (False, "SHORT")])
def test_xau_d1_tsmom_keeps_frozen_strategy_semantics_with_demo_authority(rising, expected):
    bars = _d1_bars(rising=rising)
    signal = evaluate_xau_d1_tsmom_60_200(bars, as_of=bars[-1].timestamp + timedelta(minutes=10))
    assert signal.active is True
    assert signal.execution_eligible is True
    assert execution_authorized("XAUUSD") is True
    assert signal.direction == expected
    assert signal.strategy_id == "D1_TSMOM_60_200"
    assert signal.next_entry_at == bars[-1].timestamp
    assert signal.signal_bar_at == bars[-2].timestamp
    assert signal.reason == "ENTRY_WINDOW_ACTIVE"
    assert signal.atr is not None and signal.atr > 0


def test_usdjpy_d1_donchian55_is_promoted_with_exact_two_r_geometry():
    bars = _d1_bars(symbol="USDJPY", rising=True)
    signal = evaluate_usdjpy_d1_donchian55_200(
        bars,
        as_of=bars[-1].timestamp + timedelta(minutes=5),
    )
    assert signal.active is True
    assert signal.direction == "LONG"
    assert signal.strategy_id == "D1_DONCHIAN55_200"
    assert execution_authorized("USDJPY") is True
    plan = build_usdjpy_d1_donchian55_plan(signal, current_price=float(bars[-1].open))
    assert plan.rr2 == pytest.approx(2.0)
    evidence = plan_geometry_evidence(plan)
    assert evidence is not None
    assert evidence.entry_mode == "D1_DONCHIAN55_200"
    assert evidence.exit_model == "D1_FIXED_ATR_STOP_TARGET_MAX30"


def test_xau_d1_signal_expires_after_entry_window():
    bars = _d1_bars(rising=True)
    signal = evaluate_xau_d1_tsmom_60_200(bars, as_of=bars[-1].timestamp + timedelta(minutes=31))
    assert signal.active is False
    assert signal.direction == "LONG"
    assert signal.reason == "WAIT_NEXT_D1_OPEN"


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_xau_plan_matches_frozen_two_r_contract(direction):
    bars = _d1_bars(rising=(direction == "LONG"))
    signal = evaluate_xau_d1_tsmom_60_200(bars, as_of=bars[-1].timestamp + timedelta(minutes=5))
    assert signal.direction == direction and signal.active
    plan = build_xau_d1_tsmom_plan(signal, current_price=2500.0)
    assert plan.rr2 == pytest.approx(2.0)
    assert plan.tp1 is None and plan.rr1 is None
    evidence = plan_geometry_evidence(plan)
    assert evidence is not None
    assert evidence.entry_mode == "D1_TSMOM_60_200"
    assert evidence.exit_model == "D1_FIXED_ATR_STOP_TARGET_MAX30"


def test_gbpusd_mean_reversion_plan_targets_frozen_signal_sma20():
    signal = FiveCoreSignal(
        symbol="GBPUSD",
        strategy_id="H4_MEAN_REVERT_Z2_TO_SMA20",
        direction="LONG",
        active=True,
        execution_eligible=True,
        atr=0.004,
        target_price=1.2600,
        reason="ENTRY_WINDOW_ACTIVE",
    )
    plan = build_gbpusd_h4_mean_revert_plan(signal, current_price=1.2500)
    assert plan.stop_loss == pytest.approx(1.2440)
    assert plan.tp2 == pytest.approx(1.2600)
    assert plan.rr2 == pytest.approx(0.0100 / 0.0060)
    evidence = plan_geometry_evidence(plan)
    assert evidence is not None
    assert evidence.entry_mode == "H4_MEAN_REVERT_Z2_TO_SMA20"
    assert evidence.exit_model == "H4_1P5ATR_STOP_SIGNAL_SMA20_TARGET_MAX12"
