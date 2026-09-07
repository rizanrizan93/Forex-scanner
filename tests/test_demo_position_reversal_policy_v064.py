from types import SimpleNamespace
from uuid import uuid4

import fx_scanner.demo_position_reversal as policy_mod
from fx_scanner.execution.models import OrderSide


def _position(*, position_id: int, side_code: int, comment: str = "", volume: int = 1000):
    return SimpleNamespace(
        positionId=position_id,
        tradeData=SimpleNamespace(
            symbolId=7,
            tradeSide=side_code,
            comment=comment,
            volume=volume,
        ),
    )


class Session:
    account_id = 9001001

    def __init__(self, positions):
        self.positions = tuple(positions)

    def ensure_connected(self):
        return None

    def symbol_info(self, symbol):
        assert symbol == "EURUSD"
        return SimpleNamespace(symbolId=7)

    def reconcile(self):
        return SimpleNamespace(position=self.positions)


class Store:
    def record_order_event(self, **kwargs):
        return None


def _executor(positions, *, max_positions=10):
    return SimpleNamespace(
        gateway=SimpleNamespace(session=Session(positions)),
        demo={"max_concurrent_positions": max_positions},
        policy=SimpleNamespace(order={"comment_prefix": "FXIS"}),
        store=Store(),
    )


def _intent(side=OrderSide.BUY):
    return SimpleNamespace(symbol="EURUSD", side=side)


def test_same_direction_position_allows_stacking_even_if_unmanaged():
    executor = _executor([_position(position_id=11, side_code=1, comment="MANUAL")])
    plan = policy_mod._classify_exposure(executor, _intent(OrderSide.BUY), uncertain=set())
    assert plan.block is None
    assert plan.same_direction == 1
    assert plan.managed_opposite == ()


def test_unmanaged_opposite_position_blocks_reversal_without_close():
    executor = _executor([_position(position_id=12, side_code=2, comment="MANUAL")])
    plan = policy_mod._classify_exposure(executor, _intent(OrderSide.BUY), uncertain=set())
    assert plan.block == "UNMANAGED_OPPOSITE_EXPOSURE:12"
    assert plan.managed_opposite == ()


def test_scanner_linked_opposite_is_eligible_for_guarded_close(monkeypatch):
    signal_id = str(uuid4())
    executor = _executor(
        [_position(position_id=13, side_code=2, comment=f"FXIS:{signal_id}")]
    )
    monkeypatch.setattr(policy_mod, "_signal_matches_position", lambda *args, **kwargs: True)
    plan = policy_mod._classify_exposure(executor, _intent(OrderSide.BUY), uncertain=set())
    assert plan.block is None
    assert len(plan.managed_opposite) == 1
    assert plan.managed_opposite[0].position_id == 13
    assert plan.managed_opposite[0].signal_id == signal_id


def test_uncertain_opposite_close_is_quarantined_across_new_signals(monkeypatch):
    signal_id = str(uuid4())
    executor = _executor(
        [_position(position_id=14, side_code=2, comment=f"FXIS:{signal_id}")]
    )
    monkeypatch.setattr(policy_mod, "_signal_matches_position", lambda *args, **kwargs: True)
    plan = policy_mod._classify_exposure(
        executor,
        _intent(OrderSide.BUY),
        uncertain={"14"},
    )
    assert plan.block == "REVERSAL_CLOSE_UNCERTAIN_QUARANTINE:14"
    assert plan.managed_opposite == ()


def test_same_direction_stacking_still_respects_account_capacity():
    positions = [_position(position_id=100 + i, side_code=1) for i in range(10)]
    executor = _executor(positions, max_positions=10)
    plan = policy_mod._classify_exposure(executor, _intent(OrderSide.BUY), uncertain=set())
    assert plan.block == "BROKER_CAPACITY_FULL:10/10"


def test_uncertain_close_is_marked_and_never_blind_retried(monkeypatch):
    signal_id = str(uuid4())
    managed = policy_mod.ManagedPosition(15, 1000, "SELL", signal_id)
    executor = _executor([])
    uncertain: set[str] = set()
    monkeypatch.setattr(
        policy_mod,
        "_close_full_position",
        lambda *args, **kwargs: ("UNCERTAIN", "CollectorUnavailable:timeout"),
    )

    closed, reason = policy_mod._close_managed_opposites(
        executor,
        (managed,),
        uncertain,
    )

    assert not closed
    assert reason == "REVERSAL_CLOSE_UNCERTAIN:15"
    assert uncertain == {"15"}
