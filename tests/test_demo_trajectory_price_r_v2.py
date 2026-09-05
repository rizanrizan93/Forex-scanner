from fx_scanner.demo_broker_pnl import _price_r_sample
from fx_scanner.execution.broker_gateway import BrokerBackend, BrokerPositionSnapshot


def _position(*, side, open_price, current_price, stop_loss):
    return BrokerPositionSnapshot(
        backend=BrokerBackend.CTRADER,
        position_id="1",
        symbol="EURUSD",
        side=side,
        volume=0.01,
        open_price=open_price,
        current_price=current_price,
        stop_loss=stop_loss,
        take_profit=None,
        profit=None,
        swap=None,
        magic=None,
        comment=None,
        opened_at=None,
    )


def test_buy_price_r_uses_actual_open_to_sl_and_bid_side_close_price():
    risk, value = _price_r_sample(
        _position(side="BUY", open_price=1.1000, current_price=1.1040, stop_loss=1.0980)
    )
    assert round(risk, 6) == 0.002
    assert round(value, 6) == 2.0


def test_sell_price_r_uses_actual_open_to_sl_and_ask_side_close_price():
    risk, value = _price_r_sample(
        _position(side="SELL", open_price=1.1000, current_price=1.0970, stop_loss=1.1020)
    )
    assert round(risk, 6) == 0.002
    assert round(value, 6) == 1.5


def test_price_r_fails_closed_without_valid_broker_stop_or_current_price():
    assert _price_r_sample(
        _position(side="BUY", open_price=1.1000, current_price=None, stop_loss=1.0980)
    ) == (None, None)
    assert _price_r_sample(
        _position(side="BUY", open_price=1.1000, current_price=1.1010, stop_loss=1.1015)
    ) == (None, None)
