from fx_scanner.research_xau_asia_sweep_v392 import _resolve_exit_bar, config_grid


def test_v392_grid_is_bounded_to_64_configs() -> None:
    grid = config_grid()
    assert len(grid) == 64
    assert len({row.config_id for row in grid}) == 64


def test_v392_same_bar_is_stop_first() -> None:
    assert _resolve_exit_bar(side=1, low=95.0, high=105.0, stop=96.0, target=104.0) == "LOSS"
    assert _resolve_exit_bar(side=-1, low=95.0, high=105.0, stop=104.0, target=96.0) == "LOSS"
