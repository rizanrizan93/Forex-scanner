from pathlib import Path

from fx_scanner.research_xau_v47_forward_telemetry_v72 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    TELEMETRY_CONTRACT,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v72_is_secondary_telemetry_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert TELEMETRY_CONTRACT["primary_forward_hypothesis_changed"] is False
    assert TELEMETRY_CONTRACT["primary_grouping_changed"] is False
    assert TELEMETRY_CONTRACT["secondary_features_may_change_primary_decision"] is False


def test_v72_captures_all_predeclared_secondary_families():
    groups = TELEMETRY_CONTRACT["secondary_telemetry_only"]
    assert "h1_structure" in groups
    assert "h1_volatility" in groups
    assert "prior_day_realized_skew" in groups
    assert "last_break_event" in groups["h1_structure"]
    assert "vol_state" in groups["h1_volatility"]
    assert "skew_state" in groups["prior_day_realized_skew"]


def test_v72_observer_does_not_change_primary_grouping_or_execute():
    src = (
        ROOT / "src/fx_scanner/research_xau_v47_forward_observer_v70.py"
    ).read_text()
    assert '"primary_forward_group": (' in src
    assert '"SWEEP"' in src
    assert '"NON_SWEEP"' in src
    assert '"secondary_telemetry": {' in src
    assert "send_new_order" not in src
    assert "claim_signal_for_execution" not in src
    assert 'table("paper_trades")' not in src
    assert 'table("signals")' not in src
