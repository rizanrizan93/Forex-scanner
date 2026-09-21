from fx_scanner.research_xau_v145_liquidity_memory_v146 import (
    EXECUTION_INFLUENCE,MAX_POOL_AGE_DAYS,MAX_TOUCH_BONUS,
    MEMORY_HALF_LIFE_DAYS,PROMOTION_ELIGIBLE,TOUCH_COOLDOWN_BARS,
)
def test_v146_frozen_memory_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert MEMORY_HALF_LIFE_DAYS==5.0
    assert MAX_POOL_AGE_DAYS==20.0
    assert MAX_TOUCH_BONUS==3
    assert TOUCH_COOLDOWN_BARS==4
