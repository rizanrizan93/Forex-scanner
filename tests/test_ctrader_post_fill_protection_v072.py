from types import SimpleNamespace

import pytest

from fx_scanner.execution.ctrader_protection import CTraderPostFillProtectionManager


POSITION_ID = 77
ACCOUNT_ID = 48498388
SYMBOL_ID = 11
VOLUME_CENTS = 100_000


def position(*, pid=POSITION_ID, sl=None, tp=None, side=1, symbol_id=SYMBOL_ID, volume=VOLUME_CENTS, price=1.1001):
    return SimpleNamespace(
        positionId=pid,
        price=price,
        stopLoss=sl,
        takeProfit=tp,
        tradeData=SimpleNamespace(symbolId=symbol_id, tradeSide=side, volume=volume),
    )


class FakeSession:
    account_id = ACCOUNT_ID

    def __init__(self, states, *, amend_error=None):
        self.states = list(states)
        self.last_state = self.states[-1] if self.states else []
        self.amend_error = amend_error
        self.amend_calls = []
        self.reconcile_calls = 0

    def reconcile(self):
        self.reconcile_calls += 1
        if self.states:
            state = self.states.pop(0)
            self.last_state = state
        else:
            state = self.last_state
        if isinstance(state, BaseException):
            raise state
        return SimpleNamespace(position=list(state))

    def send_amend_position_sltp(
        self,
        *,
        position_id,
        stop_loss,
        take_profit,
        client_msg_id,
        timeout,
    ):
        self.amend_calls.append(
            (position_id, stop_loss, take_profit, client_msg_id, timeout)
        )
        if self.amend_error is not None:
            raise self.amend_error
        return SimpleNamespace(executionType=4)


def symbol_info(*, sl_distance=0, tp_distance=0, distance_type=1):
    return SimpleNamespace(
        symbolId=SYMBOL_ID,
        digits=5,
        slDistance=sl_distance,
        tpDistance=tp_distance,
        distanceSetIn=distance_type,
    )


def quote(_symbol):
    return SimpleNamespace(bid=1.1000, ask=1.1002)


def manager(session, *, reconcile_attempts=1, amend_attempts=2):
    return CTraderPostFillProtectionManager(
        session,
        quote_provider=quote,
        reconcile_attempts=reconcile_attempts,
        amend_attempts=amend_attempts,
        poll_seconds=0,
        amend_timeout_seconds=0.1,
    )


def ensure(mgr, *, account_id=ACCOUNT_ID, position_id=POSITION_ID, info=None, stop=1.0950, tp=1.1100):
    return mgr.ensure(
        account_id=account_id,
        position_id=position_id,
        symbol_name="EURUSD",
        symbol_info=info or symbol_info(),
        expected_symbol_id=SYMBOL_ID,
        expected_trade_side=1,
        expected_volume_cents=VOLUME_CENTS,
        planned_stop_loss=stop,
        planned_take_profit=tp,
    )


def test_missing_sl_after_fill_is_amended_and_reconciled():
    missing = position(sl=None, tp=1.1100)
    protected = position(sl=1.0950, tp=1.1100)
    session = FakeSession([[missing], [missing], [protected]])

    result = ensure(manager(session))

    assert result.verified
    assert result.code == "PROTECTION_AMENDED_AND_VERIFIED"
    assert result.stop_loss == pytest.approx(1.0950)
    assert result.take_profit == pytest.approx(1.1100)
    assert len(session.amend_calls) == 1


def test_missing_tp_after_fill_is_amended_and_reconciled():
    missing = position(sl=1.0950, tp=None)
    protected = position(sl=1.0950, tp=1.1100)
    session = FakeSession([[missing], [missing], [protected]])

    result = ensure(manager(session))

    assert result.verified
    assert result.code == "PROTECTION_AMENDED_AND_VERIFIED"
    assert len(session.amend_calls) == 1


def test_broker_minimum_sl_distance_rejects_locally_before_amend():
    missing = position(sl=None, tp=1.1100)
    session = FakeSession([[missing]])
    # 100 broker points at 5 digits = 0.00100; planned stop is only 0.00050 below bid.
    info = symbol_info(sl_distance=100)

    result = ensure(manager(session), info=info, stop=1.0995)

    assert not result.verified
    assert result.code == "BROKER_MIN_DISTANCE_REJECTED"
    assert session.amend_calls == []


def test_amend_timeout_is_bounded_and_never_loops_forever():
    missing = position(sl=None, tp=1.1100)
    # initial, pre-amend1, reconcile1, pre-amend2, reconcile2
    session = FakeSession([[missing], [missing], [missing], [missing], [missing]], amend_error=TimeoutError("amend timeout"))

    result = ensure(manager(session, reconcile_attempts=1, amend_attempts=2))

    assert not result.verified
    assert result.code == "PROTECTION_AMEND_FAILED"
    assert len(session.amend_calls) == 2


def test_delayed_reconcile_after_amend_can_still_verify_protection():
    missing = position(sl=None, tp=1.1100)
    protected = position(sl=1.0950, tp=1.1100)
    # initial position discovery consumes first state. Pre-amend consumes second.
    # First post-amend reconcile is stale; second sees the amended protection.
    session = FakeSession([[missing], [missing], [missing], [protected]])

    result = ensure(manager(session, reconcile_attempts=2, amend_attempts=1))

    assert result.verified
    assert result.code == "PROTECTION_AMENDED_AND_VERIFIED"
    assert len(session.amend_calls) == 1


def test_duplicate_manager_invocation_is_idempotent_after_protection_exists():
    missing = position(sl=None, tp=1.1100)
    protected = position(sl=1.0950, tp=1.1100)
    session = FakeSession([[missing], [missing], [protected], [protected]])
    mgr = manager(session)

    first = ensure(mgr)
    second = ensure(mgr)

    assert first.verified and second.verified
    assert second.code == "PROTECTION_VERIFIED"
    assert len(session.amend_calls) == 1


def test_position_closed_before_amend_fails_closed_without_sending_amend():
    missing = position(sl=None, tp=1.1100)
    session = FakeSession([[missing], []])

    result = ensure(manager(session))

    assert not result.verified
    assert result.code == "POSITION_CLOSED_BEFORE_AMEND"
    assert session.amend_calls == []


def test_account_mismatch_fails_before_any_reconcile_or_amend():
    protected = position(sl=1.0950, tp=1.1100)
    session = FakeSession([[protected]])

    result = ensure(manager(session), account_id=999999)

    assert not result.verified
    assert result.code == "ACCOUNT_MISMATCH"
    assert session.reconcile_calls == 0
    assert session.amend_calls == []


def test_position_identity_mismatch_never_amends_wrong_position():
    wrong = position(pid=POSITION_ID, symbol_id=999, sl=None, tp=1.1100)
    session = FakeSession([[wrong]])

    result = ensure(manager(session))

    assert not result.verified
    assert result.code == "POSITION_SYMBOL_MISMATCH"
    assert session.amend_calls == []
