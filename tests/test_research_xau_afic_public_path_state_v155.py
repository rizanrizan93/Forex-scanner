from fx_scanner.research_xau_afic_public_path_state_v155 import (
    EXECUTION_INFLUENCE,LOCKED_PROSPECTIVE_FIXTURE,PROMOTION_ELIGIBLE,PUBLIC_EVIDENCE,VARIANTS
)

def test_v155_shadow_only_and_public_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert "PUBLIC_SHORT_M15_ENGULF" in VARIANTS
    assert "MIRROR_BIDIR_H1_BREAK" in VARIANTS
    assert any("M15" in x for x in PUBLIC_EVIDENCE)
    assert any("H1 breakdown" in x for x in PUBLIC_EVIDENCE)

def test_v155_locked_fixture_not_mutated():
    x=LOCKED_PROSPECTIVE_FIXTURE
    assert x["reference_zone"]==[4323.05,4328.64]
    assert x["first_liquidity"]==4304.55
    assert x["reaction_supply"]==[4350.24,4359.0]
    assert x["bearish_invalidation"]==[4368.0,4373.0]
    assert x["downside_objective"]==4290.0
    assert x["deep_demand"]==[4257.30,4275.05]
