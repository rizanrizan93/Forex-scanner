from fx_scanner.demo_xau_canonical_position_manager import (
    _initial_risk_and_r,
    propose_protective_stop,
)
from fx_scanner.demo_xau_m15_canonical_policy import PositionStage


def test_initial_r_uses_original_signal_stop_not_active_stop():
    risk, current_r = _initial_risk_and_r(
        side="BUY",
        entry=4356.0,
        planned_stop=4348.0,
        current_price=4368.0,
    )
    assert risk == 8.0
    assert current_r == 1.5


def test_tp1_milestone_advances_buy_stop_near_entry_without_crowding_market():
    stop = propose_protective_stop(
        side="BUY",
        stage=PositionStage.PROTECT_RUNNER,
        entry=4356.0,
        current_price=4368.0,
        current_stop=4348.0,
        initial_risk=8.0,
        last_swing_low=4357.0,
        last_swing_high=4380.0,
    )
    assert stop is not None
    assert 4356.0 < stop < 4365.6
    assert stop > 4348.0


def test_runner_trail_uses_structure_but_never_tightens_inside_minimum_room():
    stop = propose_protective_stop(
        side="BUY",
        stage=PositionStage.TRAIL_RUNNER,
        entry=4356.0,
        current_price=4376.0,
        current_stop=4356.2,
        initial_risk=8.0,
        last_swing_low=4375.0,
        last_swing_high=4380.0,
    )
    assert stop is not None
    assert stop <= 4376.0 - 0.30 * 8.0
    assert stop > 4356.2


def test_stop_proposal_never_widens_existing_protection():
    buy = propose_protective_stop(
        side="BUY",
        stage=PositionStage.PROTECT_RUNNER,
        entry=4356.0,
        current_price=4368.0,
        current_stop=4360.0,
        initial_risk=8.0,
        last_swing_low=4357.0,
        last_swing_high=4380.0,
    )
    sell = propose_protective_stop(
        side="SELL",
        stage=PositionStage.PROTECT_RUNNER,
        entry=4363.0,
        current_price=4350.0,
        current_stop=4358.0,
        initial_risk=8.0,
        last_swing_low=4348.0,
        last_swing_high=4360.0,
    )
    assert buy is None
    assert sell is None


def test_sell_runner_protection_is_symmetric():
    stop = propose_protective_stop(
        side="SELL",
        stage=PositionStage.TRAIL_RUNNER,
        entry=4363.0,
        current_price=4343.0,
        current_stop=4371.0,
        initial_risk=8.0,
        last_swing_low=4340.0,
        last_swing_high=4348.0,
    )
    assert stop is not None
    assert 4343.0 + 0.30 * 8.0 <= stop < 4363.0
    assert stop < 4371.0
