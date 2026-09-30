from __future__ import annotations

from fx_scanner.research_xau_depth_competing_risk_v281 import (
    band_competing_risk,
    evaluate_oos,
    fit_volatility_thresholds,
    grouped_competing_risk,
)


def _row(
    *,
    year: int,
    max_depth: float,
    reaction: bool = False,
    broken: bool = False,
    timeframe: str = "H1",
    direction: str = "SHORT",
    session: str = "LONDON",
    transition_state: str = "STABLE",
    atr: float = 10.0,
) -> dict:
    return {
        "year": year,
        "timeframe": timeframe,
        "direction": direction,
        "session": session,
        "reaction_hit": reaction,
        "break_hit": broken,
        "turning_depth": max_depth if reaction else None,
        "max_depth_reached": max_depth,
        "atr_points": atr,
        "transition_state": transition_state,
        "level_opposing_pressure": 20.0,
        "early_opposing_pressure": 20.0,
        "late_opposing_pressure": 20.0,
        "fade_delta": 0.0,
    }


def test_v281_denominator_is_all_episodes_that_reached_band_lower_bound() -> None:
    rows = [
        _row(year=2024, max_depth=0.15, reaction=True),
        _row(year=2024, max_depth=0.25, reaction=True),
        _row(year=2024, max_depth=1.05, broken=True),
        _row(year=2024, max_depth=0.05),
    ]
    bands = band_competing_risk(rows)
    band_20_30 = bands[2]
    assert band_20_30["band"] == "20-30%"
    assert band_20_30["at_risk"] == 2
    assert band_20_30["reversal_050"] == 1
    assert band_20_30["break_invalid"] == 1
    assert band_20_30["stall_unresolved"] == 0
    assert band_20_30["p_reversal_given_reached_band"] == 0.5
    assert band_20_30["p_break_given_reached_band"] == 0.5


def test_v281_deeper_band_can_show_higher_conditional_break_risk() -> None:
    rows = []
    for _ in range(80):
        rows.append(_row(year=2024, max_depth=0.15, reaction=True))
    for _ in range(20):
        rows.append(_row(year=2024, max_depth=1.05, broken=True))
    bands = band_competing_risk(rows)
    assert bands[0]["at_risk"] == 100
    assert bands[0]["p_break_given_reached_band"] == 0.20
    assert bands[5]["at_risk"] == 20
    assert bands[5]["p_break_given_reached_band"] == 1.0
    lo, hi = bands[5]["break_wilson_95"]
    assert lo is not None and hi is not None
    assert 0.0 <= lo <= hi <= 1.0


def test_v281_retest_is_explicitly_not_measured() -> None:
    rows = [_row(year=2024, max_depth=0.25, reaction=True) for _ in range(10)]
    thresholds = fit_volatility_thresholds(rows)
    report = grouped_competing_risk(rows, volatility_thresholds=thresholds)
    assert report["touch_scope"]["FIRST_TOUCH"]["n"] == 10
    assert report["touch_scope"]["RETEST"]["n"] == 0
    assert report["touch_scope"]["RETEST"]["status"] == (
        "NOT_MEASURED_BY_V225_V250_FIRST_TOUCH_DATASET"
    )


def test_v281_volatility_thresholds_use_training_years_only() -> None:
    rows = [
        _row(year=2012, max_depth=0.2, reaction=True, atr=10.0),
        _row(year=2013, max_depth=0.2, reaction=True, atr=11.0),
        _row(year=2014, max_depth=0.2, reaction=True, atr=12.0),
        _row(year=2025, max_depth=0.2, reaction=True, atr=1000.0),
    ]
    thresholds = fit_volatility_thresholds(rows)
    assert thresholds["H1"]["high_cut"] < 100.0


def test_v281_oos_uses_2012_2024_train_and_2025_2026_test() -> None:
    rows = []
    for year in range(2012, 2025):
        for _ in range(6):
            rows.append(
                _row(
                    year=year,
                    max_depth=0.35,
                    reaction=True,
                    session="LONDON",
                    transition_state="FADE",
                    atr=10.0,
                )
            )
        for _ in range(2):
            rows.append(
                _row(
                    year=year,
                    max_depth=1.05,
                    broken=True,
                    session="LONDON",
                    transition_state="FADE",
                    atr=10.0,
                )
            )
    for year in (2025, 2026):
        for _ in range(5):
            rows.append(
                _row(
                    year=year,
                    max_depth=0.35,
                    reaction=True,
                    session="LONDON",
                    transition_state="FADE",
                    atr=10.0,
                )
            )
        for _ in range(2):
            rows.append(
                _row(
                    year=year,
                    max_depth=1.05,
                    broken=True,
                    session="LONDON",
                    transition_state="FADE",
                    atr=10.0,
                )
            )
    thresholds = fit_volatility_thresholds(rows)
    oos = evaluate_oos(rows, volatility_thresholds=thresholds)
    assert oos["train_years"] == "2012-2024"
    assert oos["test_years"] == "2025-2026"
    assert oos["train_episode_count"] == 13 * 8
    assert oos["test_episode_count"] == 2 * 7
    assert oos["test_band_exposures"] > 0
    assert oos["classification_accuracy_resolved_exposures"] is not None
    assert oos["break_probability_metrics"]["brier"] is not None
