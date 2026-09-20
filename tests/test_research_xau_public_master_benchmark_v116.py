from datetime import datetime, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_public_master_benchmark_v116 import (
    TURTLE_S2_ID,
    RASCHKE_GRAIL_ID,
    CRABEL_NR4_ID,
    _first_touch_direction,
    POLICY_EFFECT,
    EXECUTION_INFLUENCE,
    PROMOTION_ELIGIBLE,
)

UTC=timezone.utc

def _bar(hour, high, low):
    return Bar(
        symbol="XAUUSD", timeframe="M15",
        timestamp=datetime(2026,1,2,hour,0,tzinfo=UTC),
        open=(high+low)/2, high=high, low=low, close=(high+low)/2,
        tick_count=1, spread_avg=0.1, spread_max=0.1,
    )

def test_v116_contract():
    assert TURTLE_S2_ID
    assert RASCHKE_GRAIL_ID
    assert CRABEL_NR4_ID
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False

def test_first_touch_uses_intraday_order():
    bars=(_bar(0,101,99),_bar(1,111,100),_bar(2,105,89))
    direction,index=_first_touch_direction(bars,110,90)
    assert direction=="LONG"
    assert index==1

def test_same_m15_double_touch_is_ambiguous():
    bars=(_bar(0,111,89),)
    direction,index=_first_touch_direction(bars,110,90)
    assert direction=="AMBIGUOUS"
    assert index==0
