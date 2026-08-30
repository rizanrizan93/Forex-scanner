from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.validation.backtest import (
    BacktestTrade,
    TradeIntent,
    TradeOutcome,
)
from fx_scanner.validation.metrics import compute_metrics, metrics_by_group
from fx_scanner.validation.monte_carlo import monte_carlo_returns
from fx_scanner.config import load_project_config
from fx_scanner.validation.perturbation import (
    apply_parameter_variant,
    canonical_parameter_variants,
    evaluate_parameter_perturbations,
)
from fx_scanner.validation.walk_forward import walk_forward_evaluate

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_trade(i, net_r, *, regime=None, setup="A"):
    intent = TradeIntent(
        trade_id=f"T{i}",
        symbol="EURUSD",
        direction="LONG",
        signal_at=BASE + timedelta(hours=i),
        entry_low=1.1000,
        entry_high=1.1002,
        stop_loss=1.0990,
        take_profit=1.1020,
        pip_size=0.0001,
        setup=setup,
        regime=regime or ("TREND" if i % 2 == 0 else "RANGE"),
    )
    outcome = (
        TradeOutcome.WIN if net_r > 0
        else TradeOutcome.LOSS if net_r < 0
        else TradeOutcome.BREAKEVEN
    )
    return BacktestTrade(
        intent,
        outcome,
        intent.signal_at + timedelta(minutes=5),
        intent.signal_at + timedelta(minutes=10),
        1.1002,
        1.1020 if net_r > 0 else 1.0990,
        net_r,
        net_r,
        0.05,
        1,
        False,
        "TEST",
    )


def profitable_trades(count=240):
    pattern = (2.0, 2.0, 2.0, -1.0)
    return [make_trade(i, pattern[i % len(pattern)]) for i in range(count)]


def test_performance_metrics_use_net_r_and_drawdown():
    metrics = compute_metrics(profitable_trades(40))
    assert metrics.completed_trades == 40
    assert metrics.win_rate == pytest.approx(0.75)
    assert metrics.profit_factor == pytest.approx(6.0)
    assert metrics.expectancy_r == pytest.approx(1.25)
    assert metrics.max_drawdown_r == pytest.approx(1.0)
    assert metrics.max_losing_streak == 1
    assert metrics.average_cost_r == pytest.approx(0.05)


def test_group_metrics_preserve_regime_and_setup():
    trades = profitable_trades(40)
    regimes = metrics_by_group(trades, field="regime")
    setups = metrics_by_group(trades, field="setup")
    assert set(regimes) == {"RANGE", "TREND"}
    assert set(setups) == {"A"}
    assert sum(x.completed_trades for x in regimes.values()) == 40


def test_walk_forward_is_chronological_and_passes_stable_sequence():
    result = walk_forward_evaluate(
        profitable_trades(240),
        train_fraction=0.60,
        test_fraction=0.20,
        step_fraction=0.20,
        minimum_train_trades=100,
        minimum_test_trades=30,
        fold_win_rate_min=0.50,
        fold_profit_factor_min=1.10,
        fold_expectancy_r_min=0.05,
        minimum_pass_fraction=0.67,
    )
    assert result.folds
    assert result.passed
    assert result.pass_fraction == pytest.approx(1.0)
    for fold in result.folds:
        assert fold.train_end == fold.test_start
        assert fold.train_start < fold.train_end <= fold.test_end


def test_monte_carlo_is_seeded_and_reports_sequence_risk():
    returns = [2.0, 2.0, -1.0, 2.0, -1.0] * 30
    first = monte_carlo_returns(returns, simulations=500, seed=123, block_size=5)
    second = monte_carlo_returns(returns, simulations=500, seed=123, block_size=5)
    assert first == second
    assert first.max_drawdown_r_p95 >= first.max_drawdown_r_p50
    assert first.losing_streak_p95 >= first.losing_streak_p50
    assert first.block_size == 5
    assert first.terminal_r_p05 <= first.terminal_r_p50


def test_parameter_perturbation_requires_broad_stability():
    good = compute_metrics(profitable_trades(40))
    variants = {variant.name: good for variant in canonical_parameter_variants()}
    result = evaluate_parameter_perturbations(
        variants,
        minimum_variants=6,
        profit_factor_min=1.10,
        expectancy_r_min=0.05,
        minimum_pass_fraction=0.80,
    )
    assert result.passed
    assert result.pass_fraction == pytest.approx(1.0)


def test_canonical_parameter_variants_are_deterministic_and_do_not_mutate_baseline():
    cfg = load_project_config()
    original = cfg.strategy["liquidity"]["equal_level_tolerance_atr"]
    variants = canonical_parameter_variants()
    assert [x.name for x in variants] == cfg.validation["parameter_perturbation"]["required_variants"]
    modified = apply_parameter_variant(cfg, variants[0])
    assert modified.strategy["liquidity"]["equal_level_tolerance_atr"] == pytest.approx(original * 0.90)
    assert cfg.strategy["liquidity"]["equal_level_tolerance_atr"] == original
