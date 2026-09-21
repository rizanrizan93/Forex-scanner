from fx_scanner.research_xau_afic_selector_validation_v161 import (
    EXECUTION_INFLUENCE,LIVE_EXECUTION_ENABLED,MAX_H4_DIRECTIONAL_CLOSE_LOC,
    MAX_ZONE_DISTANCE_ATR,PROMOTION_ELIGIBLE,
)
def test_v161_preregistered_selector():
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert PROMOTION_ELIGIBLE is False
    assert MAX_ZONE_DISTANCE_ATR==0.75
    assert MAX_H4_DIRECTIONAL_CLOSE_LOC==0.65
