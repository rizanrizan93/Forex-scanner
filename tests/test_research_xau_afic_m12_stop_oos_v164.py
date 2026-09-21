from datetime import datetime, timezone
from fx_scanner.research_xau_afic_m12_stop_oos_v164 import *
def test_v164_holdout_contract():
    assert HOLDOUT_START==datetime(2023,1,1,tzinfo=timezone.utc)
    assert HOLDOUT_END==datetime(2025,1,1,tzinfo=timezone.utc)
    assert LOCAL_BUFFER_ATR==0.05
    assert len(STOP_VARIANTS)==4
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
