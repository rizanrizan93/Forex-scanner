from fx_scanner.research_xau_v145_auction_dwell_v148 import (
    CONFIRM_BARS,DWELL_MARGIN_ATR,EXECUTION_INFLUENCE,
    MIN_DWELL_CLOSES,PROMOTION_ELIGIBLE,
)
def test_v148_frozen_auction_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert CONFIRM_BARS==4
    assert MIN_DWELL_CLOSES==3
    assert DWELL_MARGIN_ATR==0.05
