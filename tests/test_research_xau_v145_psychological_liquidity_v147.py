from fx_scanner.research_xau_v145_psychological_liquidity_v147 import (
    EXECUTION_INFLUENCE,MAX_LATTICE_STEPS,PROMOTION_ELIGIBLE,
    ROUND_100_USD,ROUND_50_USD,ROUND_STEP_USD,
)
def test_v147_frozen_lattice():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert ROUND_STEP_USD==10.0
    assert ROUND_50_USD==50.0
    assert ROUND_100_USD==100.0
    assert MAX_LATTICE_STEPS==20
