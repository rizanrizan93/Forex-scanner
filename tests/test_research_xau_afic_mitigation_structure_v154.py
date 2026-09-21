from fx_scanner.research_xau_afic_mitigation_structure_v154 import (
    BODY_ATR_MIN,
    ENTRY_MODES,
    EXECUTION_INFLUENCE,
    HTF_VARIANTS,
    PROMOTION_ELIGIBLE,
    RETEST_WINDOW,
    TARGET_R,
)


def test_v154_preregistered_shadow_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert ENTRY_MODES == ("MID_LIMIT", "REJECTION_CLOSE")
    assert RETEST_WINDOW == 32
    assert TARGET_R == 1.50
    assert BODY_ATR_MIN == 0.80


def test_v154_htf_variants_are_frozen():
    ids = [x.variant_id for x in HTF_VARIANTS]
    assert ids == ["NONE", "H4_MATCH", "D1_H4_NOT_OPPOSED", "D1_H4_MATCH"]
    assert HTF_VARIANTS[0].selection_eligible is False
