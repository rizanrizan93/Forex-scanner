from fx_scanner.research_xau_afic_displacement_origin_v154 import (
    EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,reconstruct_example
)

def test_v154_shadow_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

def test_v154_reconstructs_supplied_buy_target_geometry():
    round_level,terminal,ladder=reconstruct_example(4278.0,4265.0,"LONG")
    assert round_level==4300.0
    assert terminal==4299.0
    assert ladder==(4281.0,4284.0,4287.0,4290.0,4293.0,4296.0,4299.0)

def test_v154_reconstructs_supplied_sell_target_geometry():
    round_level,terminal,ladder=reconstruct_example(4349.0,4359.0,"SHORT")
    assert round_level==4330.0
    assert terminal==4331.0
    assert ladder==(4346.0,4343.0,4340.0,4337.0,4334.0,4331.0)
