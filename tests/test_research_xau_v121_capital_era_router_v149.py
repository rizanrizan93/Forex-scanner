from fx_scanner.research_xau_v121_capital_era_router_v149 import (
    BOOTSTRAP_THRESHOLD_USD,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,
    _admit,L20_ID,CORE_ID,D1_ID,L12_ID,
)
def test_v149_frozen_capital_state():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert BOOTSTRAP_THRESHOLD_USD==1000.0
    assert _admit(CORE_ID,"CAPITAL_ERA_ROUTER",100.0)
    assert _admit(D1_ID,"CAPITAL_ERA_ROUTER",100.0)
    assert not _admit(L20_ID,"CAPITAL_ERA_ROUTER",999.99)
    assert _admit(L20_ID,"CAPITAL_ERA_ROUTER",1000.0)
    assert not _admit(L12_ID,"CAPITAL_ERA_ROUTER",10000.0)
