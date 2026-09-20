from pathlib import Path

from fx_scanner.research_xau_v47_forward_sweep_telemetry_v82 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    SWEEP_TELEMETRY_CONTRACT,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v82_is_raw_telemetry_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert SWEEP_TELEMETRY_CONTRACT["primary_forward_hypothesis_changed"] is False
    assert SWEEP_TELEMETRY_CONTRACT["primary_grouping_changed"] is False
    assert SWEEP_TELEMETRY_CONTRACT["v77_target_groups_changed"] is False
    assert SWEEP_TELEMETRY_CONTRACT["thresholds_added"] is False
    assert SWEEP_TELEMETRY_CONTRACT["score_added"] is False
    assert SWEEP_TELEMETRY_CONTRACT["feature_can_change_primary_decision"] is False


def test_v82_records_raw_geometry_without_execution_path():
    src=(ROOT / "src/fx_scanner/research_xau_v47_forward_observer_v70.py").read_text()
    assert '"sweep_telemetry": sweep_telemetry' in src
    assert '"penetration_atr"' in src
    assert '"reclaim_atr"' in src
    assert '"body_atr"' in src
    assert '"close_location"' in src
    assert '"age_m15_bars"' in src
    assert "send_new_order" not in src
    assert "claim_signal_for_execution" not in src
    assert 'table("signals")' not in src
    assert 'table("paper_trades")' not in src


def test_v82_does_not_change_primary_group_expression():
    src=(ROOT / "src/fx_scanner/research_xau_v47_forward_observer_v70.py").read_text()
    assert '"primary_forward_group": (' in src
    assert '"SWEEP"' in src
    assert '"NON_SWEEP"' in src
