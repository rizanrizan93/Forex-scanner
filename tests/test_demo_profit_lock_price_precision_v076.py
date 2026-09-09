from types import SimpleNamespace

from fx_scanner.demo_adaptive_profit_lock import normalize_profit_lock_stop


class Session:
    def __init__(self, *, digits=None, pip_position=None):
        self._digits = digits
        self._pip_position = pip_position

    def symbol_info(self, symbol):
        return SimpleNamespace(digits=self._digits, pipPosition=self._pip_position)


def test_euraud_profit_lock_rounds_to_five_decimal_broker_precision():
    stop, reason = normalize_profit_lock_stop(
        Session(digits=5),
        symbol="EURAUD",
        side="BUY",
        target_stop=1.611892,
        current_stop=1.61059,
        current_price=1.61264,
    )
    assert stop == 1.61189
    assert reason == "BROKER_PRICE_NORMALIZED_5DP"


def test_pip_position_fallback_derives_fractional_pip_digits():
    stop, reason = normalize_profit_lock_stop(
        Session(digits=None, pip_position=4),
        symbol="EURAUD",
        side="BUY",
        target_stop=1.611892,
        current_stop=1.61059,
        current_price=1.61264,
    )
    assert stop == 1.61189
    assert reason == "BROKER_PRICE_NORMALIZED_5DP"


def test_unknown_broker_precision_fails_closed():
    stop, reason = normalize_profit_lock_stop(
        Session(digits=None, pip_position=None),
        symbol="EURAUD",
        side="BUY",
        target_stop=1.611892,
        current_stop=1.61059,
        current_price=1.61264,
    )
    assert stop is None
    assert reason == "BROKER_PRICE_PRECISION_UNKNOWN_FAIL_CLOSED"


def test_rounding_that_breaks_monotonic_geometry_fails_closed():
    stop, reason = normalize_profit_lock_stop(
        Session(digits=5),
        symbol="EURAUD",
        side="BUY",
        target_stop=1.610591,
        current_stop=1.61059,
        current_price=1.61264,
    )
    assert stop is None
    assert reason == "BROKER_ROUNDED_STOP_GEOMETRY_INVALID"
