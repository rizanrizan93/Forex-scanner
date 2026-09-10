from fx_scanner.demo_closed_trade_reconciler import _classify_exit


class Obj:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


def _signal():
    return {"sl": 4400.07025, "tp2": 4382.244625}


def test_profit_locked_stop_is_not_classified_as_plain_sl_loss():
    close_order = Obj(orderType=4, isStopOut=False)
    assert _classify_exit(
        close_order=close_order,
        signal=_signal(),
        exit_price=4394.10,
        gross_profit=0.26,
        partial=False,
        adaptive_profit_lock=True,
    ) == "ADAPTIVE_PROFIT_LOCK_PROFIT"


def test_adaptive_profit_lock_preserves_loss_and_breakeven_outcomes():
    close_order = Obj(orderType=4, isStopOut=False)
    assert _classify_exit(
        close_order=close_order,
        signal=_signal(),
        exit_price=4401.0,
        gross_profit=-0.50,
        partial=False,
        adaptive_profit_lock=True,
    ) == "ADAPTIVE_PROFIT_LOCK_LOSS"
    assert _classify_exit(
        close_order=close_order,
        signal=_signal(),
        exit_price=4394.36,
        gross_profit=0.0,
        partial=False,
        adaptive_profit_lock=True,
    ) == "ADAPTIVE_PROFIT_LOCK_BREAKEVEN"
