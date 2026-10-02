from fx_scanner.xau_macro_attribution_v357 import evaluate_broader_macro_bias


def _row(delta, freshness="FRESH"):
    return {
        "delta": delta,
        "freshness": freshness,
        "current": 1.0,
        "previous": 1.0,
        "provider": "TEST",
    }


def test_v357_bullish_when_usd_and_yields_fall_with_dovish_event():
    out = evaluate_broader_macro_bias(
        cross_asset={
            "USD_BROAD_PROXY": _row(-0.35),
            "US2Y": _row(-5.0),
            "US10Y": _row(-4.0),
            "REAL_YIELD_10Y": _row(-3.0),
        },
        event_context={
            "focal_event": {
                "title": "Employment Situation",
                "gold_bias": "GOLD_BULLISH",
                "gold_bias_confidence": "LOW",
                "gold_bias_basis": "CONSENSUS_VS_PREVIOUS",
            }
        },
    )
    assert out["broader_macro_bias"] == "BULLISH_XAU"
    assert out["macro_score"] > 20
    assert out["fed_repricing_proxy"]["state"] == "DOVISH_REPRICING_PROXY"
    assert out["consensus_relationship"] == "CONSENSUS_ALIGNED_WITH_BROADER_MACRO"
    assert out["execution_authority"] is False


def test_v357_bearish_when_usd_and_yields_rise():
    out = evaluate_broader_macro_bias(
        cross_asset={
            "USD_BROAD_PROXY": _row(0.40),
            "US2Y": _row(6.0),
            "US10Y": _row(5.0),
            "REAL_YIELD_10Y": _row(4.0),
        },
        event_context={
            "focal_event": {
                "title": "Consumer Price Index",
                "gold_bias": "GOLD_BEARISH",
                "gold_bias_confidence": "LOW",
            }
        },
    )
    assert out["broader_macro_bias"] == "BEARISH_XAU"
    assert out["macro_score"] < -20
    assert out["fed_repricing_proxy"]["state"] == "HAWKISH_REPRICING_PROXY"


def test_v357_flags_event_vs_cross_asset_divergence():
    out = evaluate_broader_macro_bias(
        cross_asset={
            "USD_BROAD_PROXY": _row(0.50),
            "US2Y": _row(8.0),
            "US10Y": _row(7.0),
            "REAL_YIELD_10Y": _row(6.0),
        },
        event_context={
            "focal_event": {
                "title": "Employment Situation",
                "gold_bias": "GOLD_BULLISH",
                "gold_bias_confidence": "LOW",
            }
        },
    )
    assert out["broader_macro_bias"] == "BEARISH_XAU"
    assert out["event_consensus_bias"] == "BULLISH_XAU"
    assert out["consensus_relationship"] == "CONSENSUS_DIVERGENT_FROM_BROADER_MACRO"


def test_v357_stale_inputs_are_excluded_not_neutralized():
    out = evaluate_broader_macro_bias(
        cross_asset={
            "USD_BROAD_PROXY": _row(1.5, freshness="STALE"),
            "US2Y": _row(-4.0),
            "US10Y": _row(-2.0, freshness="STALE"),
            "REAL_YIELD_10Y": _row(-3.0),
        },
        event_context={},
    )
    assert "USD_BROAD_PROXY" in out["missing_components"]
    assert "US10Y" in out["missing_components"]
    assert out["coverage"] < 1.0


def test_v357_post_release_event_gets_stronger_weight_but_no_execution_authority():
    out = evaluate_broader_macro_bias(
        cross_asset={},
        event_context={
            "focal_event": {
                "title": "Employment Situation",
                "gold_bias": "GOLD_BULLISH",
                "gold_bias_confidence": "POST_RELEASE",
                "gold_bias_basis": "ACTUAL_VS_FORECAST",
            }
        },
    )
    assert out["components"]["EVENT_CONSENSUS"]["score"] == 70.0
    assert out["event_consensus_bias"] == "BULLISH_XAU"
    assert out["broader_macro_bias"] == "UNAVAILABLE"
    assert out["state"] == "BROAD_MACRO_PARTIAL"
    assert out["confidence"] == "LOW"
    assert out["execution_authority"] is False


def test_v357_no_data_fails_closed():
    out = evaluate_broader_macro_bias(cross_asset={}, event_context={})
    assert out["state"] == "MACRO_DATA_UNAVAILABLE"
    assert out["broader_macro_bias"] == "UNAVAILABLE"
    assert out["macro_score"] is None
