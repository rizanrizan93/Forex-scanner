from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fx_scanner.demo_trade_plan_geometry import plan_geometry_evidence
from fx_scanner.demo_xau_expansion_v42 import (
    MAX_HOLD_D1_BARS,
    RR,
    STOP_ATR,
    STRATEGY_ID,
    build_xau_expansion_v42_plan,
    evaluate_xau_d1_expansion_v42,
)
from fx_scanner.demo_xau_v42_deferred_profit_lock import _decision, deferred_lock_r
from fx_scanner.models import Bar

UTC = timezone.utc


def _expansion_bars(direction: str) -> tuple[Bar, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    long_side = direction == "LONG"
    for i in range(222):
        base = 2000.0 + 2.0 * i if long_side else 3000.0 - 2.0 * i
        open_price = base
        close = base + (1.0 if long_side else -1.0)
        high = max(open_price, close) + 5.0
        low = min(open_price, close) - 5.0
        if i == 220:
            close = base + (35.0 if long_side else -35.0)
            high = max(open_price, close) + 2.0
            low = min(open_price, close) - 2.0
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe="D1",
                timestamp=start + timedelta(days=i),
                open=open_price,
                high=high,
                low=low,
                close=close,
                tick_count=100,
                spread_avg=0.1,
                spread_max=0.2,
            )
        )
    return tuple(rows)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_promoted_v42_signal_and_geometry(direction):
    bars = _expansion_bars(direction)
    signal = evaluate_xau_d1_expansion_v42(
        bars,
        as_of=bars[-1].timestamp + timedelta(minutes=5),
    )
    assert signal.strategy_id == STRATEGY_ID
    assert signal.direction == direction
    assert signal.active is True
    assert signal.execution_eligible is True
    assert signal.signal_bar_at == bars[-2].timestamp
    assert signal.next_entry_at == bars[-1].timestamp
    assert signal.atr is not None and signal.atr > 0
    assert signal.adx is not None and signal.adx >= 22.0

    plan = build_xau_expansion_v42_plan(signal, current_price=float(bars[-1].open))
    assert plan.rr2 == pytest.approx(RR)
    risk = abs(float(bars[-1].open) - plan.stop_loss)
    assert risk == pytest.approx(STOP_ATR * float(signal.atr))
    assert abs(plan.tp2 - float(bars[-1].open)) == pytest.approx(RR * risk)
    evidence = plan_geometry_evidence(plan)
    assert evidence is not None
    assert evidence.entry_mode == STRATEGY_ID
    assert evidence.exit_model == "D1_EXPANSION_V42_DEFERRED_STEP_MAX7"
    assert MAX_HOLD_D1_BARS == 7


@pytest.mark.parametrize(
    ("favorable", "expected"),
    [
        (1.24, None),
        (1.25, 0.10),
        (1.74, 0.10),
        (1.75, 0.50),
        (2.24, 0.50),
        (2.25, 1.00),
        (2.49, 1.00),
        (2.50, 1.50),
        (3.00, 2.00),
    ],
)
def test_deferred_step_contract(favorable, expected):
    assert deferred_lock_r(favorable) == pytest.approx(expected) if expected is not None else deferred_lock_r(favorable) is None


def test_deferred_lock_uses_completed_h1_geometry_and_is_monotonic():
    favorable, lock, reason = _decision(
        side="BUY",
        entry=2500.0,
        original_stop=2475.0,
        current_stop=2475.0,
        h1_close=2532.0,
    )
    assert favorable == pytest.approx(1.28)
    assert lock == pytest.approx(0.10)
    assert reason == "DEFERRED_STEP_ADVANCE"

    favorable2, lock2, reason2 = _decision(
        side="BUY",
        entry=2500.0,
        original_stop=2475.0,
        current_stop=2515.0,
        h1_close=2532.0,
    )
    assert favorable2 == pytest.approx(1.28)
    assert lock2 == pytest.approx(0.10)
    assert reason2 == "NO_MONOTONIC_IMPROVEMENT"


def test_demo_pipeline_binds_promoted_v42_and_keeps_legacy_lock_off():
    text = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text(encoding="utf-8")
    assert 'CTRADER_DEMO_XAU_V42_PROFIT_LOCK_ENABLED: "1"' in text
    assert 'CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_ENABLED: "0"' in text
    assert "python -m fx_scanner.demo_xau_expansion_v42_candidate_producer" in text
    assert "python -m fx_scanner.demo_xau_expansion_v42_time_exit" in text
    assert "python -m fx_scanner.demo_xau_v42_deferred_profit_lock" in text
