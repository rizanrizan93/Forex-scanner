from fx_scanner.xau_macro_shock_attribution_v252 import (
    CONTRACT,
    evaluate_xau_macro_shock_attribution,
)


def test_v252_bearish_xau_with_rising_dollar_and_yields_is_high_corroboration():
    out = evaluate_xau_macro_shock_attribution(
        xau_change_pct=-0.42,
        dxy_change_pct=0.35,
        dxy_age_seconds=30,
        us2y_change_bps=7.0,
        us2y_age_seconds=45,
        us10y_change_bps=5.5,
        us10y_age_seconds=50,
        technical_evidence=("H1_SUPPLY_REJECTION", "M15_BEARISH_DISPLACEMENT"),
        dom_direction="SELLER_CONTROL",
    )
    assert out["contract"] == CONTRACT
    assert out["state"] == "MACRO_TECHNICAL_CORROBORATED"
    assert out["attribution_confidence"] == "HIGH"
    assert out["aligned_macro_sources"] == 3
    assert out["claim_mode"] == "CORROBORATION_ONLY_NOT_PROVEN_CAUSE"
    assert out["execution_authority"] is False


def test_v252_stale_macro_is_excluded_and_cannot_create_high_confidence():
    out = evaluate_xau_macro_shock_attribution(
        xau_change_pct=-0.35,
        dxy_change_pct=0.50,
        dxy_age_seconds=3600,
        us2y_change_bps=8.0,
        us2y_age_seconds=3600,
        us10y_change_bps=6.0,
        us10y_age_seconds=3600,
        technical_evidence=("M15_BEARISH_DISPLACEMENT",),
    )
    assert out["fresh_macro_sources"] == 0
    assert out["state"] == "PARTIAL_CORROBORATION"
    assert out["attribution_confidence"] == "LOW"
    assert out["source_evidence"]["DXY"]["freshness"] == "STALE"


def test_v252_opposing_cross_asset_evidence_downgrades_attribution():
    out = evaluate_xau_macro_shock_attribution(
        xau_change_pct=-0.50,
        dxy_change_pct=-0.20,
        dxy_age_seconds=20,
        us2y_change_bps=-4.0,
        us2y_age_seconds=20,
        us10y_change_bps=3.0,
        us10y_age_seconds=20,
    )
    assert out["opposed_macro_sources"] == 2
    assert out["aligned_macro_sources"] == 1
    assert out["attribution_confidence"] == "LOW"


def test_v252_small_move_is_not_classified_as_shock():
    out = evaluate_xau_macro_shock_attribution(
        xau_change_pct=-0.05,
        dxy_change_pct=0.40,
        dxy_age_seconds=20,
        us2y_change_bps=5.0,
        us2y_age_seconds=20,
        us10y_change_bps=4.0,
        us10y_age_seconds=20,
    )
    assert out["move_detected"] is False
    assert out["state"] == "NO_MATERIAL_XAU_SHOCK"


def test_v252_missing_xau_move_fails_closed():
    out = evaluate_xau_macro_shock_attribution(xau_change_pct=None)
    assert out["state"] == "XAU_MOVE_UNAVAILABLE"
    assert out["execution_influence"] is False
    assert out["execution_authority"] is False
