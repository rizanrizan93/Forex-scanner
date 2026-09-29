from pathlib import Path

from fx_scanner.xau_m30_entry_policy_v278 import (
    CONTRACT,
    evaluate_m30_entry_policy_v278,
    load_v278_evidence,
)


def _shadow(overlap: float = 0.82) -> dict:
    return {
        "nearest_supply": {
            "zone_id": "m30-supply",
            "direction": "SHORT",
            "canonical_overlap_ratio": overlap,
            "canonical_match_timeframe": "H1",
        }
    }


def test_v278_frozen_evidence_keeps_near_edge_above_deep_rejection() -> None:
    evidence = load_v278_evidence()
    near_rate = evidence["holdout_near_edge_hold_050_same_confirmed_population"]
    deep_rate = evidence["holdout_deep_rejection_hold_050_rate"]
    assert evidence["history_closed_m15_bars"] == 99999
    assert evidence["holdout_deep_rejection_confirm_n"] == 1381
    assert near_rate > deep_rate
    assert round(near_rate, 6) == round(0.7552498189717596, 6)
    assert round(deep_rate, 6) == round(0.6451846488052136, 6)
    assert evidence["policy_interpretation"]["deep_rejection_primary_promotion"] is False


def test_v278_ahead_of_zone_keeps_near_edge_primary() -> None:
    out = evaluate_m30_entry_policy_v278(
        deep_rejection={"state": "AHEAD_OF_PARENT_ZONE"},
        m30_shadow=_shadow(),
        composite_pressure={
            "available": True,
            "short_calibration_allowed": True,
        },
        direction="SHORT",
    )
    assert out["contract"] == CONTRACT
    assert out["lane"] == "NEAR_EDGE_FIRST_TOUCH"
    assert out["lane_state"] == "PRIMARY_NEAR_EDGE_ACTIVE"
    assert out["execution_authority"] is False
    assert out["high_overlap"] is True


def test_v278_deep_rejection_is_secondary_recovery_not_new_primary() -> None:
    out = evaluate_m30_entry_policy_v278(
        deep_rejection={"state": "DEEP_REJECTION_CONFIRMED"},
        m30_shadow=_shadow(),
        composite_pressure={
            "available": True,
            "short_calibration_allowed": True,
        },
        direction="SHORT",
    )
    assert out["lane"] == "DEEP_REJECTION_SECONDARY"
    assert out["lane_state"] == "RECOVERY_WATCH"
    assert out["policy"]["primary_demo_calibration_lane"] == "NEAR_EDGE_FIRST_TOUCH_L1"
    assert out["policy"]["secondary_recovery_lane"] == "DEEP_REJECTION_IF_PRIMARY_MISSED"


def test_v278_parent_invalidation_disables_both_lanes() -> None:
    out = evaluate_m30_entry_policy_v278(
        deep_rejection={"state": "PARENT_INVALIDATED"},
        m30_shadow=_shadow(),
        composite_pressure={},
        direction="SHORT",
    )
    assert out["lane"] == "NONE"
    assert out["lane_state"] == "SETUP_INVALID"


def test_v278_dashboard_and_executor_explain_recovery_role() -> None:
    root = Path(__file__).resolve().parents[1]
    dashboard = (root / "streamlit_app.py").read_text()
    executor = (
        root / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    atlas = (
        root / "src/fx_scanner/demo_xau_supply_demand_atlas_v182.py"
    ).read_text()
    assert "V278 frozen 100K-bar evidence" in dashboard
    assert "near-edge first-touch" in dashboard
    assert "deep-rejection hanya recovery/re-entry" in dashboard
    assert "SECONDARY_RECOVERY_ONLY_AFTER_PRIMARY_NEAR_EDGE_MISSED" in executor
    assert "m30_entry_policy_v278" in atlas
