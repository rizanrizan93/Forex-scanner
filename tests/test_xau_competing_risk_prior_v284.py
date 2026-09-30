from fx_scanner.xau_competing_risk_prior_v284 import (
    depth_band_label,
    evaluate_v281_competing_risk_prior,
    load_v281_dashboard_prior,
)


def test_v284_prior_is_research_only_and_matches_v281_all_counts() -> None:
    payload = load_v281_dashboard_prior()
    assert payload["contract"] == "XAU_V281_DASHBOARD_COUNTS_1"
    assert payload["episode_count"] == 68185
    assert payload["execution_authority"] is False
    assert payload["execution_influence"] is False
    assert payload["ALL"][0] == ["00-10%", 68185, 50027, 17556, 602]
    assert payload["ALL"][4] == ["40-50%", 33987, 15923, 17556, 508]


def test_v284_source_specific_first_touch_crosses_to_break_dominant_at_40_50() -> None:
    prior = evaluate_v281_competing_risk_prior(
        timeframe="H1",
        direction="SHORT",
        depth=0.45,
        first_touch_calibrated=True,
    )
    assert prior["available"] is True
    assert prior["band"] == "40-50%"
    assert prior["first_break_dominant_band"] == "40-50%"
    selected = prior["selected"]
    assert selected["at_risk"] == 3782
    assert selected["break_invalid"] == 2032
    assert selected["reversal_050"] == 1613
    assert selected["p_break"] > selected["p_reversal"]
    assert len(selected["break_wilson_95"]) == 2
    assert prior["execution_authority"] is False
    assert prior["calibrated_current_probability"] is False


def test_v284_first_band_remains_reversal_dominant() -> None:
    prior = evaluate_v281_competing_risk_prior(
        timeframe="M15",
        direction="LONG",
        depth=0.05,
        first_touch_calibrated=True,
    )
    assert prior["band"] == "00-10%"
    assert prior["selected"]["dominance"] == "REVERSAL_DOMINANT"
    assert prior["selected"]["p_reversal"] > 0.74
    assert prior["selected"]["p_break"] == 6119 / 24476


def test_v284_retest_never_exposes_first_touch_probability_as_applicable() -> None:
    prior = evaluate_v281_competing_risk_prior(
        timeframe="H1",
        direction="SHORT",
        depth=0.15,
        first_touch_calibrated=False,
    )
    assert prior["available"] is False
    assert prior["reason"] == "RETEST_NOT_MEASURED_BY_V281"
    assert "selected" not in prior
    assert prior["execution_authority"] is False


def test_v284_depth_band_labels_are_stable_at_edges() -> None:
    assert depth_band_label(0.0) == "00-10%"
    assert depth_band_label(0.0999) == "00-10%"
    assert depth_band_label(0.10) == "10-20%"
    assert depth_band_label(0.9999) == "90-100%"
    assert depth_band_label(1.5) == "90-100%"
