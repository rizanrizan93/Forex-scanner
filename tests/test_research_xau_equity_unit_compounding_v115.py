from fx_scanner.research_xau_equity_unit_compounding_v115 import (
    STARTING_BALANCE_USD,
    EQUITY_UNIT_USD,
    MIN_LOT,
    MAX_LOT,
    _target_lot,
    POLICY_EFFECT,
    EXECUTION_INFLUENCE,
    PROMOTION_ELIGIBLE,
)

def test_v115_contract():
    assert STARTING_BALANCE_USD==100.0
    assert EQUITY_UNIT_USD==100.0
    assert MIN_LOT==0.01
    assert MAX_LOT==0.50
    assert _target_lot(100.0)==0.01
    assert _target_lot(199.99)==0.01
    assert _target_lot(200.0)==0.02
    assert _target_lot(1000.0)==0.10
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
