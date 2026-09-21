from fx_scanner.research_xau_qualitative_reaccel_gate_v126 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    passes_qualitative_gate,
)


def test_v126_contract_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def _base(side="LONG"):
    return {
        "side": side,
        "pct_atr14_pct": 0.20,
        "pct_atr_ratio_252": 0.20,
        "d20_pct_atr14_pct": -0.20,
        "d20_pct_atr_ratio_252": -0.20,
        "pct_ema200_distance_atr": 0.70 if side == "LONG" else 0.30,
        "d5_pct_trend60_atr": 0.10 if side == "LONG" else -0.10,
    }


def test_v126_long_and_short_are_symmetric():
    assert passes_qualitative_gate(_base("LONG"))
    assert passes_qualitative_gate(_base("SHORT"))


def test_v126_rejects_noncompressing_or_wrong_trend_side():
    x = _base("LONG")
    x["d20_pct_atr14_pct"] = 0.01
    assert not passes_qualitative_gate(x)

    x = _base("LONG")
    x["pct_ema200_distance_atr"] = 0.49
    assert not passes_qualitative_gate(x)

    x = _base("SHORT")
    x["d5_pct_trend60_atr"] = 0.01
    assert not passes_qualitative_gate(x)
