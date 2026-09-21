from fx_scanner.research_xau_afic_htf_reconstruction_v152 import (
    BASE_ENTRY_MODE,
    EXECUTION_INFLUENCE,
    PROMOTION_ELIGIBLE,
    VARIANTS,
)


def test_v152_is_preregistered_shadow_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert BASE_ENTRY_MODE == "BREAKOUT_LEVEL_RETEST_2BAR"
    ids = [x.variant_id for x in VARIANTS]
    assert len(ids) == 6
    assert len(set(ids)) == 6
    controls = [x for x in VARIANTS if not x.selection_eligible]
    assert len(controls) == 1
    assert controls[0].variant_id == "AFIC_V152_CONTROL"


def test_v152_frozen_htf_hypotheses():
    by_id = {x.variant_id: x for x in VARIANTS}
    assert by_id["AFIC_V152_D1_MATCH"].d1_mode == "MATCH"
    assert by_id["AFIC_V152_H4_MATCH"].h4_mode == "MATCH"
    assert by_id["AFIC_V152_D1_H4_MATCH"].d1_mode == "MATCH"
    assert by_id["AFIC_V152_D1_H4_MATCH"].h4_mode == "MATCH"
    assert by_id["AFIC_V152_D1_H4_NOT_OPPOSED"].d1_mode == "NOT_OPPOSED"
    assert by_id["AFIC_V152_D1_H4_NOT_OPPOSED"].h4_mode == "NOT_OPPOSED"
    assert by_id["AFIC_V152_D1_H4_MATCH_PD"].require_h4_pd is True
