from datetime import datetime, timezone

import pytest

from fx_scanner.exceptions import DataContractError
from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType


UTC = timezone.utc


def _intent(*, risk_pct: float, comment: str) -> OrderIntent:
    return OrderIntent(
        signal_id="signal-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime(2026, 9, 9, 3, 40, tzinfo=UTC),
        volume=0.01,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=risk_pct,
        comment=comment,
    )


def test_demo_auto_order_intent_accepts_three_percent_runtime_contract():
    intent = _intent(risk_pct=3.0, comment="DEMO_AUTO:HL_PULLBACK")
    assert intent.risk_pct == 3.0


def test_demo_auto_order_intent_rejects_above_three_percent():
    with pytest.raises(DataContractError, match=r"risk_pct must be in \(0, 3\]"):
        _intent(risk_pct=3.01, comment="DEMO_AUTO:HL_PULLBACK")


def test_non_demo_order_intent_keeps_one_percent_ceiling():
    with pytest.raises(DataContractError, match=r"risk_pct must be in \(0, 1\]"):
        _intent(risk_pct=1.01, comment="MANUAL")
