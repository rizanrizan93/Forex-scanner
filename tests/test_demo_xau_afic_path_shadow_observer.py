from datetime import datetime,timedelta,timezone

from fx_scanner.models import Bar
from fx_scanner.demo_xau_afic_path_shadow_observer import (
    FORWARD_CONTRACT,STRATEGY_ID,SYMBOL,_resample_completed
)

UTC=timezone.utc

def _bar(ts,px):
    return Bar("XAUUSD","M15",ts,px,px+1,px-1,px+0.2,1,0.1,0.2)

def test_afic_shadow_identity():
    assert SYMBOL=="XAUUSD"
    assert STRATEGY_ID=="XAU_AFIC_PATH_SHADOW_V1"
    assert FORWARD_CONTRACT=="XAU_AFIC_PATH_SHADOW_FORWARD_V1"

def test_afic_live_resample_excludes_forming_h4():
    start=datetime(2026,9,21,0,0,tzinfo=UTC)
    rows=tuple(_bar(start+timedelta(minutes=15*i),4300+i) for i in range(20))
    # At 04:45 UTC the 04:00-08:00 H4 bucket is still forming. Only the
    # completed 00:00-04:00 H4 bar may be used by the AFIC map.
    frame=_resample_completed(rows,"4h",as_of=datetime(2026,9,21,4,45,tzinfo=UTC))
    assert len(frame)==1
    assert frame.iloc[-1]["time"].to_pydatetime()==datetime(2026,9,21,4,0,tzinfo=UTC)
