from datetime import datetime, timezone
from pathlib import Path

from fx_scanner.demo_donchian_adaptive_tournament import DonchianVariant
from fx_scanner.demo_donchian_lifecycle import (
    FrozenCandidate,
    demotion_required,
    promotion_state,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _candidate():
    variant = DonchianVariant(20, 14, 0.10)
    return FrozenCandidate(
        strategy_id=variant.strategy_id,
        variant=variant,
        frozen_at=datetime(2026, 9, 15, tzinfo=UTC),
        historical_decision={"stage": "FORWARD_SHADOW_ELIGIBLE"},
    )


def _metrics(trades, *, win_rate=0.55, profit_factor=1.30, expectancy=0.15, drawdown=5.0):
    return {
        "completed_trades": trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy,
        "max_drawdown_r": drawdown,
    }


def _acceptance():
    return {"win_rate_min": 0.50, "profit_factor_min": 1.10, "expectancy_r_min": 0.05}


def test_forward_candidate_cannot_promote_before_100_closed_trades():
    state = promotion_state(
        candidate=_candidate(),
        forward_metrics=_metrics(99),
        stress_acceptance=_acceptance(),
        drawdown_limit_r=12.0,
    )
    assert state["state"] == "FORWARD_SHADOW_PROVISIONAL"
    assert state["execution_influence"] is False


def test_forward_candidate_becomes_limited_promotion_eligible_at_100_if_all_gates_pass():
    state = promotion_state(
        candidate=_candidate(),
        forward_metrics=_metrics(100),
        stress_acceptance=_acceptance(),
        drawdown_limit_r=12.0,
    )
    assert state["state"] == "DEMO_LIMITED_PROMOTION_ELIGIBLE"
    assert state["metrics_pass"] is True
    assert state["execution_influence"] is False


def test_forward_candidate_fails_if_expectancy_or_drawdown_gate_fails():
    weak = promotion_state(
        candidate=_candidate(),
        forward_metrics=_metrics(100, expectancy=-0.01),
        stress_acceptance=_acceptance(),
        drawdown_limit_r=12.0,
    )
    drawdown = promotion_state(
        candidate=_candidate(),
        forward_metrics=_metrics(100, drawdown=13.0),
        stress_acceptance=_acceptance(),
        drawdown_limit_r=12.0,
    )
    assert weak["state"] == "FORWARD_SHADOW_FAILED"
    assert drawdown["state"] == "FORWARD_SHADOW_FAILED"


def test_promoted_candidate_requires_demotion_on_recent_edge_decay():
    state = {"state": "DEMO_LIMITED_PROMOTION_ELIGIBLE"}
    assert demotion_required(
        state=state,
        recent_metrics=_metrics(30, profit_factor=0.85, expectancy=0.02),
    ) is True
    assert demotion_required(
        state=state,
        recent_metrics=_metrics(30, profit_factor=1.20, expectancy=0.10),
    ) is False
    assert demotion_required(
        state=state,
        recent_metrics=_metrics(29, profit_factor=0.50, expectancy=-1.0),
    ) is False


def test_donchian_workflows_are_research_only_and_never_unlock_live_trading():
    tournament = (ROOT / ".github/workflows/ctrader-demo-donchian-tournament.yml").read_text()
    forward = (ROOT / ".github/workflows/ctrader-demo-donchian-forward-shadow.yml").read_text()
    combined = tournament + forward
    assert "FX_LIVE_TRADING_ENABLED" not in combined
    assert "I_UNDERSTAND_LIVE_ORDERS" not in combined
    assert "demo_donchian_tournament_runtime" in tournament
    assert "demo_donchian_forward_shadow" in forward
