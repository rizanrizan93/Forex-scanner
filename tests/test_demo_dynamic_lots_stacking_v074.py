from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.demo_conditional_stacking import evaluate_same_symbol_stack
from fx_scanner.demo_fresh_ready_handoff import (
    DEMO_ORDER_LOT_CAP_ENV,
    DEMO_POSITION_CAP_ENV,
    DEMO_STACKING_ENV,
    load_demo_execution_policy,
)
from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType

UTC = timezone.utc


def _intent(*, side=OrderSide.BUY, volume=0.04, created_at=None):
    now = created_at or datetime.now(tz=UTC)
    return OrderIntent(
        signal_id=f"stack-test-{side.value}-{int(now.timestamp())}-{volume}",
        symbol="EURUSD",
        side=side,
        order_type=OrderType.MARKET,
        created_at=now,
        volume=volume,
        entry_price=1.1000,
        stop_loss=1.0950 if side == OrderSide.BUY else 1.1050,
        take_profit=1.1100 if side == OrderSide.BUY else 1.0900,
        risk_pct=1.0,
        comment="DEMO_AUTO:STACK_TEST",
    )


def _position(*, side=1, lots=0.04, opened_at=None, symbol_id=7):
    opened = opened_at or (datetime.now(tz=UTC) - timedelta(minutes=10))
    lot_size = 100_000
    return SimpleNamespace(
        positionId=123,
        stopLoss=1.0950 if side == 1 else 1.1050,
        takeProfit=1.1100 if side == 1 else 1.0900,
        tradeData=SimpleNamespace(
            symbolId=symbol_id,
            tradeSide=side,
            volume=int(round(lots * lot_size)),
            openTimestamp=int(opened.timestamp() * 1000),
        ),
    )


def _row(score=90.0, coverage=0.95, rr2=2.2):
    return {
        "final_score": score,
        "data_coverage": coverage,
        "rr2": rr2,
        "state": "EXECUTION_READY",
    }


def _safety(**overrides):
    base = {
        "allow_same_symbol_stacking": True,
        "stack_min_score": 85.0,
        "stack_min_coverage": 0.90,
        "stack_min_rr2": 2.0,
        "max_same_symbol_positions": 3,
        "min_stack_spacing_seconds": 300.0,
        "max_order_lots": 0.10,
        "max_same_symbol_lots": 0.30,
    }
    base.update(overrides)
    return base


def _symbol_info():
    return SimpleNamespace(lotSize=100_000)


def test_runtime_profile_can_enable_point_one_lot_and_stacking(monkeypatch):
    monkeypatch.setenv(DEMO_POSITION_CAP_ENV, "10")
    monkeypatch.setenv(DEMO_ORDER_LOT_CAP_ENV, "0.10")
    monkeypatch.setenv(DEMO_STACKING_ENV, "1")
    policy = load_demo_execution_policy()
    assert policy.demo_safety["max_concurrent_positions"] == 10
    assert policy.demo_safety["max_order_lots"] == 0.10
    assert policy.demo_safety["allow_same_symbol_stacking"] is True
    assert policy.demo_safety["max_same_symbol_positions"] == 3
    assert policy.demo_safety["max_same_symbol_lots"] == pytest.approx(0.30)
    assert policy.ctrader["environment"] == "DEMO"


def test_runtime_profile_rejects_lot_cap_above_point_one(monkeypatch):
    monkeypatch.setenv(DEMO_ORDER_LOT_CAP_ENV, "0.11")
    with pytest.raises(RuntimeError, match=r"CTRADER_DEMO_MAX_ORDER_LOTS must be in \[0.01,0.1\]"):
        load_demo_execution_policy()


def test_high_conviction_same_direction_stack_is_allowed_after_spacing():
    now = datetime.now(tz=UTC)
    block = evaluate_same_symbol_stack(
        row=_row(),
        intent=_intent(created_at=now),
        same_symbol_positions=(
            _position(side=1, lots=0.04, opened_at=now - timedelta(minutes=10)),
        ),
        symbol_info=_symbol_info(),
        demo_safety=_safety(),
    )
    assert block is None


def test_same_symbol_stack_blocks_opposite_direction():
    now = datetime.now(tz=UTC)
    block = evaluate_same_symbol_stack(
        row=_row(),
        intent=_intent(side=OrderSide.BUY, created_at=now),
        same_symbol_positions=(
            _position(side=2, opened_at=now - timedelta(minutes=10)),
        ),
        symbol_info=_symbol_info(),
        demo_safety=_safety(),
    )
    assert block == "BROKER_SYMBOL_OPPOSITE_EXPOSURE:EURUSD"


def test_same_symbol_stack_blocks_below_confidence_threshold():
    now = datetime.now(tz=UTC)
    block = evaluate_same_symbol_stack(
        row=_row(score=84.99),
        intent=_intent(created_at=now),
        same_symbol_positions=(
            _position(opened_at=now - timedelta(minutes=10)),
        ),
        symbol_info=_symbol_info(),
        demo_safety=_safety(),
    )
    assert block.startswith("BROKER_STACK_SCORE_BELOW_MIN")


def test_same_symbol_stack_blocks_too_soon():
    now = datetime.now(tz=UTC)
    block = evaluate_same_symbol_stack(
        row=_row(),
        intent=_intent(created_at=now),
        same_symbol_positions=(
            _position(opened_at=now - timedelta(seconds=299)),
        ),
        symbol_info=_symbol_info(),
        demo_safety=_safety(),
    )
    assert block.startswith("BROKER_STACK_SPACING_TOO_SHORT")


def test_same_symbol_stack_blocks_fourth_position():
    now = datetime.now(tz=UTC)
    positions = tuple(
        _position(
            side=1,
            lots=0.03,
            opened_at=now - timedelta(minutes=10 + idx),
        )
        for idx in range(3)
    )
    block = evaluate_same_symbol_stack(
        row=_row(),
        intent=_intent(created_at=now),
        same_symbol_positions=positions,
        symbol_info=_symbol_info(),
        demo_safety=_safety(),
    )
    assert block == "BROKER_SYMBOL_STACK_CAP:3/3"


def test_same_symbol_stack_blocks_aggregate_symbol_lot_cap():
    now = datetime.now(tz=UTC)
    block = evaluate_same_symbol_stack(
        row=_row(),
        intent=_intent(volume=0.10, created_at=now),
        same_symbol_positions=(
            _position(lots=0.10, opened_at=now - timedelta(minutes=10)),
            _position(lots=0.10, opened_at=now - timedelta(minutes=20)),
        ),
        symbol_info=_symbol_info(),
        demo_safety=_safety(max_same_symbol_lots=0.25),
    )
    assert block.startswith("BROKER_SYMBOL_LOT_CAP")
