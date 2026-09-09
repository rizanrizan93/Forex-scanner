from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_strategy_outcome_comparison import (
    BASELINE_LABEL,
    EMA_ACTIVE_LABEL,
    EMA_INACTIVE_LABEL,
    build_strategy_outcome_report,
)

UTC = timezone.utc


def _row(index, *, active, exit_type, pnl, realized_r, comparable=True, mae_r=None, mfe_r=None):
    payload = {
        "exit_type": exit_type,
        "net_pnl_estimate": pnl,
        "realized_r": realized_r,
        "direction": "LONG",
        "strategy_lab_version": 2 if comparable else 1,
        "ema4_policy_effect": "OBSERVATION_ONLY" if comparable else None,
        "strategy_hypotheses": [
            {
                "family": "FOUR_EMA_PULLBACK",
                "score": 75.0 if active else 40.0,
                "active": active,
                "policy_effect": "OBSERVATION_ONLY",
            }
        ] if comparable else [],
    }
    if mae_r is not None:
        payload["mae_r"] = mae_r
    if mfe_r is not None:
        payload["mfe_r"] = mfe_r
    return {
        "observed_at": datetime(2026, 9, 9, 8, 0, tzinfo=UTC) + timedelta(minutes=index),
        "payload": payload,
    }


def test_strategy_outcome_report_compares_only_post_ema_shadow_trades():
    rows = (
        _row(0, active=True, exit_type="TP_HIT", pnl=2.0, realized_r=1.5, mae_r=-0.2, mfe_r=1.8),
        _row(1, active=True, exit_type="SL_HIT", pnl=-1.0, realized_r=-1.0, mae_r=-1.0, mfe_r=0.2),
        _row(2, active=False, exit_type="SL_HIT", pnl=-2.0, realized_r=-1.0, mae_r=-1.1, mfe_r=0.1),
        _row(3, active=True, exit_type="BREAKEVEN", pnl=0.0, realized_r=0.0, mae_r=-0.3, mfe_r=0.7),
        _row(4, active=True, exit_type="TP_HIT", pnl=99.0, realized_r=5.0, comparable=False),
    )

    report = build_strategy_outcome_report(rows)
    baseline = report["cohorts"][BASELINE_LABEL]
    active = report["cohorts"][EMA_ACTIVE_LABEL]
    inactive = report["cohorts"][EMA_INACTIVE_LABEL]

    assert report["comparable_closed_rows"] == 4
    assert report["legacy_or_noncomparable_closed_rows"] == 1
    assert report["candidate_stage"] == "OBSERVE"
    assert report["policy_effect"] == "SHADOW_ONLY"
    assert report["execution_mutation"] is False

    assert baseline["decisive"] == 3
    assert baseline["wins"] == 1
    assert baseline["losses"] == 2
    assert baseline["win_rate"] == pytest.approx(1 / 3)
    assert baseline["expectancy_r"] == pytest.approx(-0.125)
    assert baseline["profit_factor"] == pytest.approx(2 / 3)
    assert baseline["max_drawdown_r"] == pytest.approx(2.0)
    assert baseline["max_consecutive_losses"] == 2

    assert active["closed"] == 3
    assert active["decisive"] == 2
    assert active["win_rate"] == pytest.approx(0.5)
    assert active["expectancy_r"] == pytest.approx(1 / 6)
    assert active["profit_factor"] == pytest.approx(2.0)
    assert active["max_drawdown_r"] == pytest.approx(1.0)
    assert active["avg_mae_r"] == pytest.approx(-0.5)
    assert active["avg_mfe_r"] == pytest.approx(0.9)

    assert inactive["closed"] == 1
    assert inactive["losses"] == 1
    assert report["candidate_uplift_vs_comparable_baseline"]["win_rate_delta_pp"] == pytest.approx(100 * (0.5 - 1 / 3))
    assert report["candidate_uplift_vs_comparable_baseline"]["expectancy_r_delta"] == pytest.approx(1 / 6 + 0.125)
    assert report["candidate_uplift_vs_comparable_baseline"]["max_drawdown_r_delta"] == pytest.approx(-1.0)


def test_zero_loss_profit_factor_stays_json_finite():
    report = build_strategy_outcome_report(
        (_row(0, active=True, exit_type="TP_HIT", pnl=2.0, realized_r=1.2),)
    )
    active = report["cohorts"][EMA_ACTIVE_LABEL]

    assert active["profit_factor"] is None
    assert active["win_rate"] == 1.0
