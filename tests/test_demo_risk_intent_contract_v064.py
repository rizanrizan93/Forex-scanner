from datetime import datetime, timezone

import pytest

from fx_scanner.exceptions import DataContractError
from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType


UTC = timezone.utc


def _intent(*, risk_pct: float, comment: str) -> OrderIntent:
    return OrderIntent(
        signal_id=f"risk-contract-{risk_pct}-{comment or 'none'}",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.01,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=risk_pct,
        comment=comment,
    )


def test_demo_auto_intent_accepts_user_approved_ten_percent_ceiling():
    intent = _intent(risk_pct=10.0, comment="DEMO_AUTO:TREND_CONTINUATION:ELITE")
    assert intent.risk_pct == 10.0


def test_demo_auto_intent_rejects_above_ten_percent():
    with pytest.raises(DataContractError, match=r"\(0, 10\]"):
        _intent(risk_pct=10.01, comment="DEMO_AUTO:TREND_CONTINUATION:ELITE")


def test_non_demo_intent_keeps_one_percent_ceiling():
    with pytest.raises(DataContractError, match=r"\(0, 1\]"):
        _intent(risk_pct=10.0, comment="LIVE_OR_GENERIC")

    assert _intent(risk_pct=1.0, comment="LIVE_OR_GENERIC").risk_pct == 1.0
