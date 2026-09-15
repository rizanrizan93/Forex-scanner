from datetime import datetime, timedelta, timezone

from fx_scanner.demo_donchian_adaptive_tournament import (
    ATR_PERIODS,
    BREAKOUT_BUFFERS_ATR,
    LOOKBACKS,
    DonchianVariant,
    TournamentCosts,
    TournamentMetrics,
    VariantEvaluation,
    choose_candidate,
    parameter_grid,
    simulate_variant,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(index: int, close: float, *, spread: float = 0.0001) -> Bar:
    open_price = close - 0.0001
    return Bar(
        symbol="EURUSD",
        timeframe="H1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        open=open_price,
        high=max(open_price, close) + 0.0003,
        low=min(open_price, close) - 0.0003,
        close=close,
        tick_count=100 + index,
        spread_avg=spread,
        spread_max=spread * 1.2,
    )


def _costs() -> TournamentCosts:
    return TournamentCosts(0.8, 0.2, 0.2, 0.0)


def _validation_cfg():
    return {
        "walk_forward": {
            "train_fraction": 0.60,
            "test_fraction": 0.20,
            "minimum_train_trades": 100,
            "minimum_test_trades": 30,
            "step_fraction": 0.20,
            "fold_win_rate_min": 0.50,
            "fold_profit_factor_min": 1.10,
            "fold_expectancy_r_min": 0.05,
            "minimum_pass_fraction": 0.67,
        },
        "stress_acceptance": {
            "win_rate_min": 0.50,
            "profit_factor_min": 1.10,
            "expectancy_r_min": 0.05,
        },
        "parameter_perturbation": {
            "minimum_variants": 6,
            "minimum_pass_fraction": 0.80,
        },
    }


def _metrics(expectancy=0.30, profit_factor=1.50, drawdown=4.0):
    return TournamentMetrics(
        completed_trades=180,
        wins=105,
        losses=75,
        breakeven=0,
        win_rate=105 / 180,
        profit_factor=profit_factor,
        expectancy_r=expectancy,
        gross_profit_r=210.0,
        gross_loss_r=140.0,
        max_drawdown_r=drawdown,
        max_losing_streak=5,
        average_cost_r=0.03,
    )


def _evaluation(variant, *, expectancy=0.30, eligible=True):
    return VariantEvaluation(
        variant=variant,
        base_metrics=_metrics(expectancy=expectancy),
        stressed_metrics=_metrics(expectancy=expectancy - 0.05, profit_factor=1.30),
        folds=(),
        walk_forward_pass_fraction=0.80 if eligible else 0.50,
        walk_forward_passed=eligible,
        stress_passed=eligible,
        preliminary_eligible=eligible,
    )


def test_parameter_grid_is_preregistered_and_bounded_to_48_variants():
    rows = parameter_grid()
    assert len(rows) == len(LOOKBACKS) * len(ATR_PERIODS) * len(BREAKOUT_BUFFERS_ATR) == 48
    assert len({row.strategy_id for row in rows}) == 48
    assert DonchianVariant(20, 14, 0.10).strategy_id == "DONCHIAN_H1_L20_ATR14_B10_V1"


def test_simulator_uses_prior_channel_and_can_enter_next_h1_after_close_breakout():
    closes = [1.1000 + 0.00002 * index for index in range(30)]
    # Force a completed H1 close materially above the prior channel, then trend
    # strongly enough for the fixed 2R target to be observable later.
    closes[21] = 1.1100
    for index in range(22, 30):
        closes[index] = 1.1100 + 0.0020 * (index - 21)
    bars = tuple(_bar(index, close) for index, close in enumerate(closes))
    trades = simulate_variant(
        bars,
        symbol="EURUSD",
        pip_size=0.0001,
        variant=DonchianVariant(20, 14, 0.10),
        costs=_costs(),
    )

    assert trades
    first = trades[0]
    assert first.signal_index == 21
    assert first.entry_at > first.signal_at
    assert first.direction == "LONG"
    assert first.strategy_id == "DONCHIAN_H1_L20_ATR14_B10_V1"
    assert first.cost_r > 0


def test_simulator_does_not_open_overlapping_positions_per_symbol_variant():
    closes = [1.1000 + 0.00002 * index for index in range(80)]
    for index in range(21, 80):
        closes[index] = 1.1100 + 0.0008 * (index - 21)
    bars = tuple(_bar(index, close) for index, close in enumerate(closes))
    trades = simulate_variant(
        bars,
        symbol="EURUSD",
        pip_size=0.0001,
        variant=DonchianVariant(20, 14, 0.0),
        costs=_costs(),
    )

    for previous, current in zip(trades, trades[1:]):
        assert current.signal_index > previous.exit_index


def test_candidate_requires_six_axis_neighbors_and_80_percent_stability():
    selected = DonchianVariant(20, 14, 0.10)
    neighbors = (
        DonchianVariant(10, 14, 0.10),
        DonchianVariant(30, 14, 0.10),
        DonchianVariant(20, 10, 0.10),
        DonchianVariant(20, 20, 0.10),
        DonchianVariant(20, 14, 0.0),
        DonchianVariant(20, 14, 0.20),
    )
    rows = [_evaluation(selected, expectancy=0.50)]
    rows.extend(_evaluation(item, expectancy=0.20) for item in neighbors)
    decision = choose_candidate(rows, _validation_cfg())

    assert decision["selected_strategy_id"] == selected.strategy_id
    assert decision["neighbor_count"] == 6
    assert decision["passing_neighbors"] == 6
    assert decision["parameter_stability_pass"] is True
    assert decision["stage"] == "FORWARD_SHADOW_ELIGIBLE"
    assert decision["execution_influence"] is False


def test_candidate_stays_unstable_if_neighbor_robustness_is_below_80_percent():
    selected = DonchianVariant(20, 14, 0.10)
    neighbors = (
        DonchianVariant(10, 14, 0.10),
        DonchianVariant(30, 14, 0.10),
        DonchianVariant(20, 10, 0.10),
        DonchianVariant(20, 20, 0.10),
        DonchianVariant(20, 14, 0.0),
        DonchianVariant(20, 14, 0.20),
    )
    rows = [_evaluation(selected, expectancy=0.50)]
    rows.extend(
        _evaluation(item, expectancy=0.20, eligible=index < 4)
        for index, item in enumerate(neighbors)
    )
    decision = choose_candidate(rows, _validation_cfg())

    assert decision["neighbor_count"] == 6
    assert decision["passing_neighbors"] == 4
    assert decision["parameter_stability_pass"] is False
    assert decision["stage"] == "HISTORICAL_CANDIDATE_UNSTABLE"
