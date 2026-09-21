from fx_scanner.research_xau_afic_symmetric_htf_v153 import (
    BASE_SIGNAL_VARIANT_ID,
    EXECUTION_INFLUENCE,
    PROMOTION_ELIGIBLE,
    RETEST_BARS,
    VARIANTS,
)


def test_v153_symmetric_preregistered_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert BASE_SIGNAL_VARIANT_ID == "V18_L12_ADX12_NOD1_R150"
    assert RETEST_BARS == 2
    assert len(VARIANTS) == 6
    assert len({x.variant_id for x in VARIANTS}) == 6


def test_v153_control_and_pd_variant():
    controls = [x for x in VARIANTS if not x.selection_eligible]
    assert len(controls) == 1
    assert controls[0].variant_id == "AFIC_V153_CONTROL"
    pd = [x for x in VARIANTS if x.require_h4_pd]
    assert len(pd) == 1
    assert pd[0].variant_id == "AFIC_V153_D1_H4_MATCH_PD"
