from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_conviction_sizing import select_demo_conviction_sizing
from fx_scanner.demo_xau_m15_liquidity_sweep_fade import (
    FORWARD_DEMO_SCORE,
    RESEARCH_LADDER_R,
    STRATEGY_CONTRACT,
    STRATEGY_ID,
    TP1_R,
    TP2_R,
    build_xau_m15_liquidity_sweep_fade_plan,
    evaluate_xau_m15_liquidity_sweep_fade,
    forward_rank,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(index: int, *, open_: float, high: float, low: float, close: float, symbol: str = "XAUUSD") -> Bar:
    return Bar(
        symbol=symbol,
        timeframe="M15",
        timestamp=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=300 + index,
        spread_avg=0.25,
        spread_max=0.40,
    )


def _qualifying_short_bars() -> tuple[Bar, ...]:
    rows: list[Bar] = []
    for index in range(60):
        close = 4300.0 + 0.02 * index
        rows.append(
            _bar(
                index,
                open_=close - 0.05,
                high=close + 0.40,
                low=close - 0.40,
                close=close,
            )
        )
    for close in (4302.0, 4304.0, 4306.0, 4308.0, 4310.0, 4312.0, 4314.0, 4316.0):
        index = len(rows)
        rows.append(
            _bar(
                index,
                open_=close - 0.30,
                high=close + 0.40,
                low=close - 0.40,
                close=close,
            )
        )
    index = len(rows)
    rows.append(_bar(index, open_=4317.0, high=4319.0, low=4314.0, close=4316.0))
    return tuple(rows)


def _qualifying_long_bars() -> tuple[Bar, ...]:
    pivot = 8600.0
    rows = []
    for index, source in enumerate(_qualifying_short_bars()):
        rows.append(
            _bar(
                index,
                open_=pivot - float(source.open),
                high=pivot - float(source.low),
                low=pivot - float(source.high),
                close=pivot - float(source.close),
            )
        )
    return tuple(rows)


def test_detects_short_after_buyside_sweep_and_bearish_reclaim():
    rows = _qualifying_short_bars()
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )

    assert signal.strategy_id == STRATEGY_ID
    assert signal.contract == STRATEGY_CONTRACT
    assert signal.direction == "SHORT"
    assert signal.active is True
    assert signal.execution_eligible is True
    assert signal.reason == "ENTRY_WINDOW_ACTIVE"
    assert signal.sweep_price > signal.swept_level > rows[-1].close
    assert signal.structural_stop > signal.sweep_price
    assert signal.impulse_atr >= 1.50
    assert signal.extension_from_ema_atr >= 0.60
    assert signal.rejection_atr >= 0.35


def test_detects_long_as_exact_price_axis_mirror():
    rows = _qualifying_long_bars()
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )

    assert signal.direction == "LONG"
    assert signal.active is True
    assert signal.sweep_price < signal.swept_level < rows[-1].close
    assert signal.structural_stop < signal.sweep_price
    assert signal.impulse_atr >= 1.50


def test_no_fresh_sweep_fails_closed():
    rows = list(_qualifying_short_bars())
    prior_high = max(float(item.high) for item in rows[-13:-1])
    last = rows[-1]
    rows[-1] = _bar(
        len(rows) - 1,
        open_=last.open,
        high=prior_high,
        low=last.low,
        close=last.close,
    )
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        tuple(rows),
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    assert signal.active is False
    assert signal.direction is None
    assert "LIQUIDITY_HIGH_SWEPT" in signal.reason


def test_non_xau_bundle_fails_closed():
    rows = list(_qualifying_short_bars())
    last = rows[-1]
    rows[-1] = _bar(
        len(rows) - 1,
        open_=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        symbol="EURUSD",
    )
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        tuple(rows),
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    assert signal.active is False
    assert signal.reason == "INVALID_M15_BUNDLE"


def test_expired_signal_is_not_reactivated():
    rows = _qualifying_short_bars()
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=30),
    )
    assert signal.direction == "SHORT"
    assert signal.active is False
    assert signal.reason == "WAIT_NEXT_M15_OPEN"


def test_short_plan_preserves_telegram_ladder_shape_in_r_space():
    rows = _qualifying_short_bars()
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    price = rows[-1].close
    plan = build_xau_m15_liquidity_sweep_fade_plan(signal, current_price=price)
    risk = plan.stop_loss - price

    assert RESEARCH_LADDER_R == (0.30, 0.60, 0.90, 1.20, 1.50, 1.80)
    assert plan.direction == "SHORT"
    assert plan.tp1 == pytest.approx(price - TP1_R * risk)
    assert plan.tp2 == pytest.approx(price - TP2_R * risk)
    assert plan.rr1 == pytest.approx(1.20)
    assert plan.rr2 == pytest.approx(1.80)


def test_long_plan_is_symmetric():
    rows = _qualifying_long_bars()
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    price = rows[-1].close
    plan = build_xau_m15_liquidity_sweep_fade_plan(signal, current_price=price)
    risk = price - plan.stop_loss

    assert plan.direction == "LONG"
    assert plan.tp1 == pytest.approx(price + TP1_R * risk)
    assert plan.tp2 == pytest.approx(price + TP2_R * risk)


def test_short_rank_is_signed_but_conviction_is_equal():
    rows = _qualifying_short_bars()
    signal = evaluate_xau_m15_liquidity_sweep_fade(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    rank = forward_rank(signal)
    assert rank.direction == "SHORT"
    assert rank.pair_edge == pytest.approx(-FORWARD_DEMO_SCORE)
    assert rank.absolute_edge == pytest.approx(FORWARD_DEMO_SCORE)


def test_probationary_sizing_stays_at_b_tier():
    sizing = select_demo_conviction_sizing(
        {
            "symbol": "XAUUSD",
            "final_score": FORWARD_DEMO_SCORE,
            "data_coverage": 1.0,
            "rr2": TP2_R,
        },
        max_order_lots=0.50,
        max_risk_pct=5.0,
    )
    assert sizing.tier == "B"
    assert sizing.lots == pytest.approx(0.01)
    assert sizing.risk_budget_pct == pytest.approx(1.0)
