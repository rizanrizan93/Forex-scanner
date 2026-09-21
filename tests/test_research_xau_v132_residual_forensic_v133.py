from fx_scanner.research_xau_v132_residual_forensic_v133 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _residual_c2,
)


def test_v133_is_forensic_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def _eligible_long_record():
    return {
        "side": "LONG",
        "pct_atr14_pct": 0.20,
        "pct_atr_ratio_252": 0.20,
        "d20_pct_atr14_pct": -0.10,
        "d20_pct_atr_ratio_252": -0.20,
        "d20_pct_range20_atr": -0.30,
        "pct_ema200_distance_atr": 0.70,
        "d5_pct_trend60_atr": 0.10,
    }


def test_v133_residual_is_exact_v126_long_plus_triple_contraction():
    rec = _eligible_long_record()
    assert _residual_c2(rec) is True

    no_range_contraction = {**rec, "d20_pct_range20_atr": 0.01}
    assert _residual_c2(no_range_contraction) is False

    short_side = {
        **rec,
        "side": "SHORT",
        "pct_ema200_distance_atr": 0.30,
        "d5_pct_trend60_atr": -0.10,
    }
    assert _residual_c2(short_side) is False

    fails_frozen_v126 = {**rec, "pct_ema200_distance_atr": 0.49}
    assert _residual_c2(fails_frozen_v126) is False
