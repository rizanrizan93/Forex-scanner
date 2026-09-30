from fx_scanner.xau_competing_risk_prior_v285 import (
    depth_band_label,
    evaluate_v281_competing_risk_prior,
    evaluate_v281_contextual_competing_risk,
    historical_pressure_proxy_bucket,
    load_v281_context_prior,
    load_v281_dashboard_prior,
    volatility_bucket_from_atr,
)


def test_v285_prior_is_research_only_and_matches_v281_all_counts() -> None:
    payload = load_v281_dashboard_prior()
    assert payload["contract"] == "XAU_V281_DASHBOARD_COUNTS_1"
    assert payload["episode_count"] == 68185
    assert payload["execution_authority"] is False
    assert payload["execution_influence"] is False
    assert payload["ALL"][0] == ["00-10%", 68185, 50027, 17556, 602]
    assert payload["ALL"][4] == ["40-50%", 33987, 15923, 17556, 508]


def test_v285_source_specific_first_touch_crosses_to_break_dominant_at_40_50() -> None:
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


def test_v285_first_band_remains_reversal_dominant() -> None:
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


def test_v285_retest_never_exposes_first_touch_probability_as_applicable() -> None:
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


def test_v285_depth_band_labels_are_stable_at_edges() -> None:
    assert depth_band_label(0.0) == "00-10%"
    assert depth_band_label(0.0999) == "00-10%"
    assert depth_band_label(0.10) == "10-20%"
    assert depth_band_label(0.9999) == "90-100%"
    assert depth_band_label(1.5) == "90-100%"


def test_v286_context_prior_is_compact_research_only() -> None:
    payload = load_v281_context_prior()
    assert payload["contract"] == "XAU_V281_CONTEXT_DASHBOARD_COUNTS_1"
    assert payload["episode_count"] == 68185
    assert payload["touch_scope"] == "FIRST_TOUCH_ONLY"
    assert payload["retest_status"] == "NOT_MEASURED_BY_V225_V250_FIRST_TOUCH_DATASET"
    assert payload["volatility_thresholds_fit_on"] == "2012-2024_ONLY"
    assert payload["historical_pressure_source"] == "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM"
    assert payload["live_pressure_source"] == "CTRADER_LEVEL_II_DOM_SEPARATE_RUNTIME_SIGNAL"
    assert payload["execution_authority"] is False
    assert payload["execution_influence"] is False
    assert payload["calibrated_current_probability"] is False


def test_v286_volatility_bucket_uses_frozen_training_thresholds() -> None:
    assert volatility_bucket_from_atr(timeframe="H1", atr_points=2.0) == "LOW"
    assert volatility_bucket_from_atr(timeframe="H1", atr_points=3.5) == "MID"
    assert volatility_bucket_from_atr(timeframe="H1", atr_points=5.0) == "HIGH"
    assert volatility_bucket_from_atr(timeframe="UNKNOWN", atr_points=5.0) == "UNKNOWN"


def test_v286_live_dom_bridge_is_semantic_only_not_historical_dom() -> None:
    fading = historical_pressure_proxy_bucket("OPPOSING_FADING")
    assert fading["historical_proxy_bucket"] == "FADE"
    assert fading["bridge"] == "SEMANTIC_ONLY_NOT_CALIBRATED"
    assert fading["historical_source"] == "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM"
    assert fading["live_source"] == "CTRADER_LEVEL_II_DOM_SEPARATE_RUNTIME_SIGNAL"

    reaccel = historical_pressure_proxy_bucket("OPPOSING_REACCELERATION")
    assert reaccel["historical_proxy_bucket"] == "REACCELERATION"


def test_v286_context_selects_live_session_volatility_proxy_and_era_band() -> None:
    context = evaluate_v281_contextual_competing_risk(
        timeframe="H1",
        depth=0.45,
        session="LONDON",
        atr_points=3.5,
        live_pressure_state="OPPOSING_FADING",
        first_touch_calibrated=True,
        year=2026,
    )
    assert context["available"] is True
    assert context["band"] == "40-50%"
    assert context["session"] == "LONDON"
    assert context["volatility_bucket"] == "MID"
    assert context["pressure_bridge"]["historical_proxy_bucket"] == "FADE"
    assert context["era"] == "2025_2026"
    assert context["cells"]["session"]["selected"]["at_risk"] == 8990
    assert context["cells"]["volatility"]["selected"]["at_risk"] == 10065
    assert context["cells"]["historical_pressure_proxy"]["selected"]["at_risk"] == 3732
    assert context["cells"]["era"]["selected"]["at_risk"] == 4063
    assert context["execution_authority"] is False
    assert context["calibrated_current_probability"] is False


def test_v286_retest_context_is_not_exposed_as_live_probability() -> None:
    context = evaluate_v281_contextual_competing_risk(
        timeframe="H1",
        depth=0.45,
        session="LONDON",
        atr_points=3.5,
        live_pressure_state="OPPOSING_FADING",
        first_touch_calibrated=False,
        year=2026,
    )
    assert context["available"] is False
    assert context["reason"] == "RETEST_NOT_MEASURED_BY_V281"
    assert "cells" not in context
    assert context["execution_authority"] is False
