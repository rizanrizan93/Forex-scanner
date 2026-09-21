from fx_scanner.research_xau_afic_runner_state_v156 import EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,VARIANTS
def test_v156_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert VARIANTS==("PUBLIC_SHORT_M15_ENGULF","MIRROR_BIDIR_M15_ENGULF")
