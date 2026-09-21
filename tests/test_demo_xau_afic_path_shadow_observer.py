from fx_scanner.demo_xau_afic_path_shadow_observer import (
    FORWARD_CONTRACT,STRATEGY_ID,SYMBOL
)

def test_afic_shadow_identity():
    assert SYMBOL=="XAUUSD"
    assert STRATEGY_ID=="XAU_AFIC_PATH_SHADOW_V1"
    assert FORWARD_CONTRACT=="XAU_AFIC_PATH_SHADOW_FORWARD_V1"
