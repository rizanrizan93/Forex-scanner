from fx_scanner.research_xau_v139_causal_technical_states_v140 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    causal_state,
)


def test_v140_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_causal_state_contract_is_fixed():
    assert causal_state(
        {"opportunity_cost": "SUPPORTIVE", "momentum_state": "GOLD_MOMENTUM_DOWN"}
    ) == "TAILWIND"
    assert causal_state(
        {"opportunity_cost": "HOSTILE", "momentum_state": "GOLD_MOMENTUM_UP"}
    ) == "RESILIENT_HEADWIND"
    assert causal_state(
        {"opportunity_cost": "HOSTILE", "momentum_state": "GOLD_MOMENTUM_DOWN"}
    ) == "FRAGILE_HEADWIND"
    assert causal_state(
        {"opportunity_cost": "MIXED", "momentum_state": "GOLD_MOMENTUM_UP"}
    ) == "MIXED"
