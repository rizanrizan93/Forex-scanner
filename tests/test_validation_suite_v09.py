from datetime import datetime, timedelta, timezone

from fx_scanner.config import load_project_config
from fx_scanner.models import Bar
from fx_scanner.validation.backtest import TradeIntent
from fx_scanner.validation.suite import run_validation_suite

UTC = timezone.utc
BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


def dataset(count=30):
    intents = []
    bars = []
    for i in range(count):
        signal = BASE + timedelta(minutes=15 * i)
        intents.append(
            TradeIntent(
                f"T{i}",
                "EURUSD",
                "LONG",
                signal,
                1.1000,
                1.1002,
                1.0990,
                1.1020,
                0.0001,
                "TREND_CONTINUATION",
                "TREND" if i % 2 == 0 else "RANGE",
                entry_expiry_bars=4,
                maximum_hold_bars=12,
            )
        )
        bars.extend(
            [
                Bar("EURUSD", "M5", signal, 1.1010, 1.1015, 1.1005, 1.1010, 100, 0.0001, 0.0002),
                Bar("EURUSD", "M5", signal + timedelta(minutes=5), 1.1005, 1.1010, 1.1000, 1.1005, 100, 0.0001, 0.0002),
                Bar("EURUSD", "M5", signal + timedelta(minutes=10), 1.1010, 1.1023, 1.1005, 1.1020, 100, 0.0001, 0.0002),
            ]
        )
    return intents, bars


def test_validation_suite_keeps_oos_separate_and_applies_cost_stress():
    cfg = load_project_config()
    intents, bars = dataset()
    report = run_validation_suite(
        intents=intents,
        bars_by_symbol={"EURUSD": bars},
        timeframe_seconds=300,
        acceptance_cfg=cfg.risk["acceptance"],
        validation_cfg=cfg.validation,
    )
    assert len(report.split.train) == 18
    assert len(report.split.validation) == 6
    assert len(report.split.oos) == 6
    assert report.base_metrics.completed_trades == 6
    assert report.stressed_metrics.completed_trades == 6
    assert report.stressed_metrics.expectancy_r < report.base_metrics.expectancy_r
    assert report.monte_carlo is not None
    assert not report.acceptance.passed
    assert "DEMO_FORWARD_PENDING" in report.acceptance.blockers
    assert "PARAMETER_PERTURBATION_MISSING" in report.acceptance.blockers
