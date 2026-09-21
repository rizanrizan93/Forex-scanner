from fx_scanner.research_xau_afic_liquidity_forecast_v152 import (
    EXECUTION_INFLUENCE,LADDER_STEP_USD,MAX_LADDER_STEPS,PROMOTION_ELIGIBLE,build_ladder
)
def test_v152_contract_is_shadow_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LADDER_STEP_USD==3.0 and MAX_LADDER_STEPS==7

def test_v152_user_supplied_buy_ladder_reconstructs_exactly():
    assert build_ladder(4278.0,4299.0,"LONG")==(
        4281.0,4284.0,4287.0,4290.0,4293.0,4296.0,4299.0
    )

def test_v152_user_supplied_sell_ladder_reconstructs_exactly():
    assert build_ladder(4349.0,4331.0,"SHORT")==(
        4346.0,4343.0,4340.0,4337.0,4334.0,4331.0
    )
