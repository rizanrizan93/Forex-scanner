from fx_scanner.research_xau_fvg_ce_capital_v96 import ENTRY_VARIANT,STARTING_BALANCE_USD,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v96_contract():
    assert ENTRY_VARIANT=="FVG_CE_4"
    assert STARTING_BALANCE_USD==100.0
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
