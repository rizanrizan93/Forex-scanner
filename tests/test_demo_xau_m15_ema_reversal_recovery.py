from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_conviction_sizing import select_demo_conviction_sizing
from fx_scanner.demo_xau_m15_ema_reversal_recovery import (
    FORWARD_DEMO_SCORE,
    STRATEGY_ID,
    TP1_R,
    TP2_R,
    build_xau_m15_ema_reversal_plan,
    evaluate_xau_m15_ema_reversal_recovery,
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
        tick_count=200 + index,
        spread_avg=0.25,
        spread_max=0.40,
    )


def _qualifying_bars() -> tuple[Bar, ...]:
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
    rows.append(
        _bar(index, open_=4337.0, high=4342.0, low=4336.5, close=4341.0)
    )
    return tuple(rows)


def test_detects_long_after_extreme_selloff_and_bullish_reclaim():
    rows = _qualifying_bars()
    as_of = rows[-1].timestamp + timedelta(minutes=15)

    signal = evaluate_xau_m15_ema_reversal_recovery(rows, as_of=as_of)

    assert signal.strategy_id == STRATEGY_ID
    assert signal.direction == "LONG"
    assert signal.active is True
    assert signal.execution_eligible is True
    assert signal.reason == "ENTRY_WINDOW_ACTIVE"
    assert signal.ema20 < signal.ema50 < signal.ema200
    assert signal.downside_impulse_atr >= 2.0
    assert signal.extension_below_fast_atr >= 0.75
    assert signal.recovery_from_low_atr >= 0.60
    assert signal.structural_stop < signal.recent_low < rows[-1].close


def test_non_xau_bundle_fails_closed():
    rows = list(_qualifying_bars())
    last = rows[-1]
    rows[-1] = _bar(
        len(rows) - 1,
        open_=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        symbol="EURUSD",
    )
    signal = evaluate_xau_m15_ema_reversal_recovery(
        tuple(rows),
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    assert signal.active is False
    assert signal.direction is None
    assert signal.reason == "INVALID_M15_BUNDLE"


def test_expired_entry_window_does_not_reactivate_old_signal():
    rows = _qualifying_bars()
    signal = evaluate_xau_m15_ema_reversal_recovery(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=30),
    )
    assert signal.direction == "LONG"
    assert signal.active is False
    assert signal.reason == "WAIT_NEXT_M15_OPEN"


def test_plan_uses_structural_stop_and_staged_r_targets():
    rows = _qualifying_bars()
    signal = evaluate_xau_m15_ema_reversal_recovery(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=15),
    )
    price = rows[-1].close
    plan = build_xau_m15_ema_reversal_plan(signal, current_price=price)
    risk = price - plan.stop_loss

    assert plan.direction == "LONG"
    assert plan.stop_loss == pytest.approx(signal.structural_stop)
    assert plan.tp1 == pytest.approx(price + TP1_R * risk)
    assert plan.tp2 == pytest.approx(price + TP2_R * risk)
    assert plan.rr1 == pytest.approx(1.5)
    assert plan.rr2 == pytest.approx(3.0)


def test_probationary_score_stays_at_smallest_active_demo_tier():
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
