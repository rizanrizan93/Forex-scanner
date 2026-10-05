from types import SimpleNamespace

from fx_scanner import demo_xau_v375_reaction_executor as executor


class FakeSession:
    def __init__(self, positions, symbol_id=101):
        self._positions = tuple(positions)
        self._symbol_id = symbol_id

    def symbol_id(self, symbol):
        assert symbol == "XAUUSD"
        return self._symbol_id

    def reconcile(self):
        return SimpleNamespace(position=self._positions)


def position(position_id, symbol_id, *, stop_loss=0.0, take_profit=0.0):
    return SimpleNamespace(
        positionId=position_id,
        stopLoss=stop_loss,
        takeProfit=take_profit,
        tradeData=SimpleNamespace(symbolId=symbol_id),
    )


def test_v393_unprotected_non_xau_does_not_block_xau_executor() -> None:
    session = FakeSession(
        [
            position(1, 202, stop_loss=0.0, take_profit=0.0),
            position(2, 101, stop_loss=4100.0, take_profit=4200.0),
        ]
    )
    ok, reason = executor._protected_xau_positions_only(session)
    assert ok is True
    assert reason == "ALL_XAU_POSITIONS_PROTECTED:1"


def test_v393_unprotected_xau_still_blocks() -> None:
    session = FakeSession([position(42056005, 101, stop_loss=0.0, take_profit=4200.0)])
    ok, reason = executor._protected_xau_positions_only(session)
    assert ok is False
    assert reason == "UNPROTECTED_XAU_POSITION:42056005"


def test_v393_unknown_position_symbol_fails_closed() -> None:
    session = FakeSession([position(7, 0, stop_loss=4100.0, take_profit=4200.0)])
    ok, reason = executor._protected_xau_positions_only(session)
    assert ok is False
    assert reason == "POSITION_SYMBOL_UNKNOWN:7"


def test_v393_run_installs_xau_scoped_guard(monkeypatch) -> None:
    monkeypatch.setattr(executor.base, "run", lambda: 0)
    assert executor.run() == 0
    assert executor.base._protected_positions_only is executor._protected_xau_positions_only
