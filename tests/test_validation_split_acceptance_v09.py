from datetime import datetime, timedelta, timezone

from fx_scanner.config import load_project_config
from fx_scanner.validation.acceptance import evaluate_acceptance
from fx_scanner.validation.backtest import TradeIntent
from fx_scanner.validation.metrics import PerformanceMetrics
from fx_scanner.validation.monte_carlo import MonteCarloResult
from fx_scanner.validation.perturbation import PerturbationResult
from fx_scanner.validation.split import chronological_split
from fx_scanner.validation.walk_forward import WalkForwardResult

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def intent(i):
    return TradeIntent(
        f"T{i}",
        "EURUSD",
        "LONG",
        BASE + timedelta(hours=i),
        1.1000,
        1.1002,
        1.0990,
        1.1020,
        0.0001,
        "SETUP",
        "TREND",
    )


def good_metrics(trades=300):
    return PerformanceMetrics(
        completed_trades=trades,
        wins=180,
        losses=120,
        breakeven=0,
        win_rate=0.60,
        profit_factor=1.50,
        expectancy_r=0.20,
        gross_profit_r=180.0,
        gross_loss_r=120.0,
        max_drawdown_r=6.0,
        max_losing_streak=5,
        average_cost_r=0.05,
    )


def test_chronological_split_keeps_equal_timestamps_in_one_partition():
    values = [intent(i) for i in range(10)]
    split = chronological_split(
        values,
        train_fraction=0.60,
        validation_fraction=0.20,
        oos_fraction=0.20,
    )
    assert len(split.train) == 6
    assert len(split.validation) == 2
    assert len(split.oos) == 2
    assert max(x.signal_at for x in split.train) < min(x.signal_at for x in split.validation)
    assert max(x.signal_at for x in split.validation) < min(x.signal_at for x in split.oos)


def test_acceptance_stays_blocked_until_demo_forward_and_perturbation_pass():
    cfg = load_project_config()
    metrics = good_metrics()
    wf = WalkForwardResult((), 1.0, True)
    mc = MonteCarloResult(1000, 5, 4.0, 8.0, 3, 6, 20.0, 20.0)
    variants = {f"V{i}": metrics for i in range(5)}
    perturb = PerturbationResult(variants, 1.0, True)

    pending = evaluate_acceptance(
        base_oos=metrics,
        stressed_oos=metrics,
        walk_forward=wf,
        monte_carlo=mc,
        regime_metrics={"TREND": metrics, "RANGE": metrics},
        acceptance_cfg=cfg.risk["acceptance"],
        validation_cfg=cfg.validation,
        demo_forward_passed=False,
        parameter_perturbation=perturb,
    )
    assert not pending.passed
    assert "DEMO_FORWARD_PENDING" in pending.blockers

    passed = evaluate_acceptance(
        base_oos=metrics,
        stressed_oos=metrics,
        walk_forward=wf,
        monte_carlo=mc,
        regime_metrics={"TREND": metrics, "RANGE": metrics},
        acceptance_cfg=cfg.risk["acceptance"],
        validation_cfg=cfg.validation,
        demo_forward_passed=True,
        parameter_perturbation=perturb,
    )
    assert passed.passed
    assert passed.blockers == ()


def test_acceptance_fails_closed_when_monte_carlo_or_perturbation_missing():
    cfg = load_project_config()
    metrics = good_metrics()
    wf = WalkForwardResult((), 1.0, True)
    decision = evaluate_acceptance(
        base_oos=metrics,
        stressed_oos=metrics,
        walk_forward=wf,
        monte_carlo=None,
        regime_metrics={"TREND": metrics, "RANGE": metrics},
        acceptance_cfg=cfg.risk["acceptance"],
        validation_cfg=cfg.validation,
        demo_forward_passed=True,
        parameter_perturbation=None,
    )
    assert not decision.passed
    assert "MONTE_CARLO_MISSING" in decision.blockers
    assert "PARAMETER_PERTURBATION_MISSING" in decision.blockers
