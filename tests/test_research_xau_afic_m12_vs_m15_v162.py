from datetime import datetime,timezone
from fx_scanner.models import Bar
from fx_scanner.research_xau_afic_m12_vs_m15_v162 import (
    EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,resample_bars
)

def test_v162_shadow_only_and_m12_alignment():
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    rows=[]
    for minute in range(24):
        rows.append(Bar(
            symbol="XAUUSD",timeframe="M1",
            timestamp=datetime(2026,1,2,0,minute,tzinfo=timezone.utc),
            open=100+minute,high=101+minute,low=99+minute,close=100.5+minute,
            tick_count=1,spread_avg=0.0,spread_max=0.0,
        ))
    x=resample_bars(rows,minutes=12,timeframe="M12")
    assert len(x)==2
    assert x[0].timestamp.minute==0
    assert x[1].timestamp.minute==12
