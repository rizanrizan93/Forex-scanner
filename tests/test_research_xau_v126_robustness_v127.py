from fx_scanner.research_xau_v126_robustness_v127 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    RULES,
    _passes,
)
from fx_scanner.research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate


def _record(side="LONG"):
    return {
        "side":side,
        "pct_atr14_pct":0.2,
        "pct_atr_ratio_252":0.2,
        "d20_pct_atr14_pct":-0.2,
        "d20_pct_atr_ratio_252":-0.2,
        "pct_ema200_distance_atr":0.7 if side=="LONG" else 0.3,
        "d5_pct_trend60_atr":0.1 if side=="LONG" else -0.1,
    }


def test_v127_is_shadow_and_frozen():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert len(RULES)==6


def test_v127_base_gate_matches_v126():
    for side in ("LONG","SHORT"):
        x=_record(side)
        assert _passes(x)==passes_qualitative_gate(x)


def test_v127_ablation_only_removes_named_rule():
    x=_record("LONG")
    x["pct_atr14_pct"]=0.8
    assert not _passes(x)
    assert _passes(x,omit="ATR_LEVEL")
