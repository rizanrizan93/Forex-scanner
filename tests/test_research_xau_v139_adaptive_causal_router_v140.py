from datetime import datetime, timedelta, timezone

from fx_scanner.demo_donchian_adaptive_tournament import TournamentTrade
from fx_scanner.research_xau_v139_adaptive_causal_router_v140 import (
    DECISION_THRESHOLD_R,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    SHRINKAGE_ALPHA,
    WARMUP_COMPLETED_CANDIDATES,
)


def test_v140_contract_is_shadow_only_and_preregistered():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert WARMUP_COMPLETED_CANDIDATES == 40
    assert SHRINKAGE_ALPHA == 20.0
    assert DECISION_THRESHOLD_R == 0.0
