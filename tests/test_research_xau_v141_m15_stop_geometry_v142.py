from fx_scanner.research_xau_v141_m15_stop_geometry_v142 import STOP_GEOMETRIES,BUFFER_ATR,MIN_RISK_ATR,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE
def test_v142_frozen_geometry_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert STOP_GEOMETRIES==("BASELINE_LOCAL6_B15","SWING3_B10","DISPLACEMENT_BAR_B10")
    assert BUFFER_ATR==0.10
    assert MIN_RISK_ATR==0.35
