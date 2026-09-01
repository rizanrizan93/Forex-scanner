from types import SimpleNamespace

from fx_scanner.cli import _build_ctrader_demo_smoke_intent
from fx_scanner.config import load_project_config
from fx_scanner.execution.models import OrderSide, OrderType


class Gateway:
    def market_quote(self, symbol):
        assert symbol == "EURUSD"
        return SimpleNamespace(bid=1.0999, ask=1.1000)


def test_controlled_demo_smoke_geometry_is_fixed_and_small():
    cfg = load_project_config()
    intent = _build_ctrader_demo_smoke_intent(cfg, Gateway(), symbol="EURUSD")
    assert intent.symbol == "EURUSD"
    assert intent.side == OrderSide.BUY
    assert intent.order_type == OrderType.MARKET
    assert intent.volume == 0.01
    assert intent.risk_pct == 0.25
    assert intent.entry_price == 1.1000
    assert abs(intent.stop_loss - 1.0980) < 1e-12
    assert abs(intent.take_profit - 1.1040) < 1e-12
    assert intent.comment == "CONTROLLED_DEMO_ORDER_SMOKE"
