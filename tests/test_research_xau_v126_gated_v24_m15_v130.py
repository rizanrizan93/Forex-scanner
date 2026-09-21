from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.research_xau_v126_gated_v24_m15_v130 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _route_raw_m15,
)


def test_v130_contract_is_shadow_only():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v130_routes_only_matching_side_inside_frozen_epoch():
    z=timezone.utc
    epochs=[{
        "start":"2025-01-01T00:00:00+00:00",
        "end_exclusive":"2025-02-01T00:00:00+00:00",
        "side":"LONG",
        "pct_atr14_pct":0.2,
        "pct_atr_ratio_252":0.2,
        "d20_pct_atr14_pct":-0.2,
        "d20_pct_atr_ratio_252":-0.2,
        "pct_ema200_distance_atr":0.7,
        "d5_pct_trend60_atr":0.1,
    }]
    long=SimpleNamespace(entry_at=datetime(2025,1,15,tzinfo=z),direction="LONG")
    short=SimpleNamespace(entry_at=datetime(2025,1,15,tzinfo=z),direction="SHORT")
    late=SimpleNamespace(entry_at=datetime(2025,2,2,tzinfo=z),direction="LONG")
    out=_route_raw_m15((long,short,late),epochs,end=datetime(2025,3,1,tzinfo=z))
    assert out==(long,)
