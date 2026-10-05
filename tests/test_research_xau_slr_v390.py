from fx_scanner.research_xau_slr_v390 import (
    _resolve_exit_bar,
    config_grid,
    summarize_trades,
)


def test_v390_grid_is_bounded_to_64_configs() -> None:
    grid = config_grid()
    assert len(grid) == 64
    assert len({row.config_id for row in grid}) == 64


def test_v390_ambiguous_bar_is_stop_first_long_and_short() -> None:
    assert _resolve_exit_bar(side=1, low=95.0, high=105.0, stop=96.0, target=104.0) == "LOSS"
    assert _resolve_exit_bar(side=-1, low=95.0, high=105.0, stop=104.0, target=96.0) == "LOSS"


def test_v390_costs_reduce_expectancy() -> None:
    rows = [
        {"entry_at": "2024-01-01T00:00:00+00:00", "exit_at": "2024-01-01T01:00:00+00:00", "gross_r": 2.0, "risk_price": 4.0},
        {"entry_at": "2024-01-02T00:00:00+00:00", "exit_at": "2024-01-02T01:00:00+00:00", "gross_r": -1.0, "risk_price": 4.0},
    ]
    base = summarize_trades(rows, cost_price=0.40)
    stress = summarize_trades(rows, cost_price=0.80)
    assert stress["expectancy_r"] < base["expectancy_r"]
    assert stress["profit_factor_r"] < base["profit_factor_r"]
