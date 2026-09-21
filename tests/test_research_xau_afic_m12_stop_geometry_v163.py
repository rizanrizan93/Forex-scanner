from fx_scanner.research_xau_afic_m12_stop_geometry_v163 import (
    EXECUTION_INFLUENCE,LOCAL_BUFFER_ATR,PROMOTION_ELIGIBLE,STOP_VARIANTS
)

def test_v163_frozen_diagnostic_contract():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LOCAL_BUFFER_ATR==0.05
    assert STOP_VARIANTS==(
        "H1_ORIGIN_DISTAL_CONTROL",
        "M12_TOUCH_CONFIRM_EXTREME",
        "M12_CONFIRM_BAR_EXTREME",
        "M12_LOCAL3_EXTREME",
    )
