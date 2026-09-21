from fx_scanner.research_xau_afic_external_liquidity_v153 import EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,VARIANTS
def test_v153_shadow_only():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert "H1_EXTERNAL_ROUTE" in VARIANTS
    assert "H1_EXTERNAL_D1_MATCH" in VARIANTS
