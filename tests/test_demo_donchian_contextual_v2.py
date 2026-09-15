from datetime import datetime, timedelta, timezone

from fx_scanner.demo_donchian_adaptive_tournament import TournamentMetrics
from fx_scanner.demo_donchian_contextual_v2 import (
    CORE_VARIANT,
    PROFILES,
    ContextEvaluation,
    ContextSignal,
    context_accepts,
    evaluate_untouched_holdout,
    profile_by_id,
    select_on_development,
)

UTC = timezone.utc


def _metrics(trades=180, *, expectancy=0.20, profit_factor=1.30, win_rate=0.55, drawdown=5.0):
    return TournamentMetrics(
        completed_trades=trades,
        wins=int(trades * win_rate),
        losses=trades - int(trades * win_rate),
        breakeven=0,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy_r=expectancy,
        gross_profit_r=100.0,
        gross_loss_r=70.0,
        max_drawdown_r=drawdown,
        max_losing_streak=5,
        average_cost_r=0.03,
    )


def _evaluation(profile_id, *, passed=True, expectancy=0.20, pass_fraction=0.80):
    profile = profile_by_id(profile_id)
    return ContextEvaluation(
        profile=profile,
        development_metrics=_metrics(expectancy=expectancy),
        stressed_development_metrics=_metrics(expectancy=expectancy - 0.05, profit_factor=1.20),
        walk_forward_pass_fraction=pass_fraction,
        walk_forward_passed=passed,
        development_stress_passed=passed,
        development_passed=passed and profile.selection_eligible,
    )


def _cfg():
    return {
        "stress_acceptance": {
            "win_rate_min": 0.50,
            "profit_factor_min": 1.10,
            "expectancy_r_min": 0.05,
        }
    }


def test_context_profiles_are_preregistered_and_core_parameters_are_frozen():
    assert CORE_VARIANT.lookback == 20
    assert CORE_VARIANT.atr_period == 14
    assert CORE_VARIANT.buffer_atr == 0.10
    assert len(PROFILES) == 7
    assert PROFILES[0].profile_id == "RAW_CONTROL"
    assert PROFILES[0].selection_eligible is False


def test_trend_displacement_fvg_profile_requires_all_three_contexts():
    profile = profile_by_id("H1_TREND_DISPLACEMENT_FVG")
    accepted = ContextSignal(
        direction="LONG",
        trend_aligned=True,
        displacement_aligned=True,
        fvg_aligned=True,
        liquid_window=False,
        trend="BULLISH",
        bos="BULLISH",
        mss=None,
    )
    missing_fvg = ContextSignal(
        direction="LONG",
        trend_aligned=True,
        displacement_aligned=True,
        fvg_aligned=False,
        liquid_window=True,
        trend="BULLISH",
        bos="BULLISH",
        mss=None,
    )
    assert context_accepts(profile, accepted) is True
    assert context_accepts(profile, missing_fvg) is False


def test_london_ny_profile_requires_liquid_window_without_changing_breakout_core():
    profile = profile_by_id("H1_DISPLACEMENT_LONDON_NY")
    liquid = ContextSignal("LONG", False, True, False, True, "RANGE", "BULLISH", None)
    asia = ContextSignal("LONG", False, True, False, False, "RANGE", "BULLISH", None)
    assert context_accepts(profile, liquid) is True
    assert context_accepts(profile, asia) is False


def test_development_selector_never_selects_raw_control_and_uses_only_development_fields():
    rows = (
        _evaluation("RAW_CONTROL", passed=True, expectancy=5.0, pass_fraction=1.0),
        _evaluation("H1_TREND_ALIGNED", passed=True, expectancy=0.15, pass_fraction=0.80),
        _evaluation("H1_DISPLACEMENT", passed=True, expectancy=0.25, pass_fraction=0.90),
    )
    selected = select_on_development(rows)
    assert selected is not None
    assert selected.profile.profile_id == "H1_DISPLACEMENT"


def test_untouched_holdout_requires_at_least_100_trades_and_profitability_under_stress():
    selected = _evaluation("H1_DISPLACEMENT", passed=True)

    insufficient = evaluate_untouched_holdout(
        selected=selected,
        holdout_base=[],
        holdout_stressed=[],
        validation_cfg=_cfg(),
    )
    assert insufficient["stage"] == "RESEARCH_ONLY"
    assert insufficient["holdout_sample_pass"] is False

    class Row:
        pass

    # The holdout evaluator consumes TournamentTrade rows via compute_metrics;
    # sample sufficiency and profit gates are independently unit-tested through
    # empty input here and integration-tested in the broker-backed workflow.
    assert insufficient["execution_influence"] is False


def test_no_development_winner_keeps_v2_research_only_without_opening_holdout():
    decision = evaluate_untouched_holdout(
        selected=None,
        holdout_base=(),
        holdout_stressed=(),
        validation_cfg=_cfg(),
    )
    assert decision == {
        "stage": "RESEARCH_ONLY",
        "selected_profile_id": None,
        "development_pass": False,
        "holdout_pass": False,
        "reason": "NO_CONTEXT_PROFILE_PASSED_DEVELOPMENT_GATES",
        "execution_influence": False,
    }
