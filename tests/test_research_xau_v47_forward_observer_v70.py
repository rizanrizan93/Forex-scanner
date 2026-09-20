from pathlib import Path

from fx_scanner.research_xau_v47_forward_observer_v70 import (
    EVENT_TYPE,
    EXECUTION_INFLUENCE,
    HISTORY_BARS,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    PROSPECTIVE_EPOCH,
    route_eligibility,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v70_is_shadow_only_and_prospective():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert EVENT_TYPE == "DEMO_XAU_V47_FORWARD_EVALUATION"
    assert HISTORY_BARS == 60_000
    assert PROSPECTIVE_EPOCH.isoformat() == "2026-09-20T01:00:00+00:00"


def test_v70_exact_v47_route_eligibility_shape():
    assert route_eligibility(
        direction="LONG",
        d1_side=1,
        secular_regime="SECULAR_BULL",
        transition_outcome="REACCELERATION",
        post_transition_age_days=10,
        h1_close=2500.0,
        h1_ema20=2495.0,
        h1_ema50=2490.0,
        h1_ema200=2450.0,
        entry_friction_r=0.08,
    ) is True

    assert route_eligibility(
        direction="LONG",
        d1_side=1,
        secular_regime="SECULAR_BULL",
        transition_outcome="REACCELERATION",
        post_transition_age_days=10,
        h1_close=2500.0,
        h1_ema20=2495.0,
        h1_ema50=2490.0,
        h1_ema200=2450.0,
        entry_friction_r=0.11,
    ) is False

    assert route_eligibility(
        direction="SHORT",
        d1_side=-1,
        secular_regime="SECULAR_BEAR",
        transition_outcome="REACCELERATION",
        post_transition_age_days=10,
        h1_close=2400.0,
        h1_ema20=2405.0,
        h1_ema50=2410.0,
        h1_ema200=2450.0,
        entry_friction_r=0.08,
    ) is False


def test_v70_has_no_execution_or_paper_trade_path():
    src=(ROOT / "src/fx_scanner/research_xau_v47_forward_observer_v70.py").read_text()
    forbidden=(
        "send_new_order",
        "claim_signal_for_execution",
        'table("paper_trades")',
        'table("signals")',
        "EXECUTION_READY",
    )
    for token in forbidden:
        assert token not in src
    assert "record_order_event(" in src
    assert "write_heartbeat(" in src
