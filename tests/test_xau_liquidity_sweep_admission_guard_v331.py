from fx_scanner.xau_liquidity_sweep_admission_guard_v331 import (
    CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    build_liquidity_sweep_admission_guard,
)


def _supply_case():
    narrow = {
        "zone_id": "supply-4194-4200",
        "timeframe": "H1",
        "zone_class": "IMBALANCE",
        "pattern": "RBD",
        "direction": "SHORT",
        "low": 4194.22,
        "high": 4200.19,
        "proximal": 4194.22,
        "distal": 4200.19,
        "atr_points": 18.0,
        "distance_points": 4.0,
        "lifecycle": {"active": True},
        "liquidity": {
            "nearby_levels": [
                {"price": 4200.0, "source": "ROUND_NUMBER"},
            ]
        },
    }
    parent = {
        "zone_id": "parent-4219",
        "timeframe": "H1",
        "zone_class": "STRUCTURAL",
        "pattern": "STRUCTURAL_SUPPLY",
        "direction": "SHORT",
        "low": 4182.85,
        "high": 4219.29,
        "proximal": 4182.85,
        "distal": 4219.29,
        "atr_points": 20.0,
        "distance_points": 2.0,
        "lifecycle": {"active": True},
        "liquidity": {
            "nearby_levels": [
                {"price": 4215.0, "source": "H1_SWING_HIGH"},
                {"price": 4210.0, "source": "ROUND_NUMBER"},
            ]
        },
    }
    atlas = {
        "last_closed_m15_price": 4189.0,
        "zones": [narrow, parent],
        "nearest_supply": narrow,
        "nearest_demand": {},
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT",
                "source_zone": narrow,
                "primary_opposing_zone": narrow,
                "terminal_target_zone": narrow,
            }
        },
        "m5_path_projection": {
            "current_leg": {
                "direction": "SHORT",
                "source_zone": narrow,
                "micro_refinement": {},
            }
        },
    }
    plan = {
        "direction": "SHORT",
        "candidate": {
            "direction": "SHORT",
            "source_zone": narrow,
        },
    }
    return atlas, plan


def test_v331_blocks_zone_edge_fade_when_liquidity_extends_to_4215():
    atlas, plan = _supply_case()
    out = build_liquidity_sweep_admission_guard(
        atlas_evaluation=atlas,
        plan=plan,
        live_price=4189.0,
    )
    assert out["contract"] == CONTRACT
    assert out["source_aligned"] is True
    assert out["risk_grade"] == "HIGH"
    assert out["first_touch_warning"] is True
    # V317 separately regression-tests the exact 4215 parent/liquidity extension.
    # V331 only needs proof that the execution-source envelope extends beyond the
    # narrow 4200.19 edge and is therefore unsafe to fade without confirmation.
    assert out["sweep_band"]["high"] > 4200.19
    assert out["micro_reconfirmed"] is False
    assert out["hard_execution_block"] is True
    assert out["state"] == "WAIT_LIQUIDITY_SWEEP_CONFIRMATION"
    assert out["pre_touch_entry_allowed"] is False
    assert EXECUTION_INFLUENCE is True
    assert EXECUTION_AUTHORITY is False


def test_v331_releases_only_after_existing_m5_reclaim_mss_displacement():
    atlas, plan = _supply_case()
    atlas["micro_refinement"] = {
        "state": "M5_REFINEMENT_CONFIRMED_SHADOW",
        "direction": "SHORT",
        "reclaim_confirmed": True,
        "mss_confirmed": True,
        "displacement_confirmed": True,
        "reclaim_at": "2026-10-01T00:05:00+00:00",
        "mss_at": "2026-10-01T00:10:00+00:00",
        "displacement_at": "2026-10-01T00:15:00+00:00",
    }
    out = build_liquidity_sweep_admission_guard(
        atlas_evaluation=atlas,
        plan=plan,
        live_price=4208.0,
    )
    assert out["source_aligned"] is True
    assert out["risk_grade"] == "HIGH"
    assert out["micro_reconfirmed"] is True
    assert out["hard_execution_block"] is False
    assert out["state"] == "SWEEP_RISK_RECONFIRMED"
    assert out["zone_edge_fade_allowed"] is True


def test_v331_does_not_block_unrelated_direction():
    atlas, _ = _supply_case()
    long_plan = {
        "direction": "LONG",
        "candidate": {
            "direction": "LONG",
            "source_zone": {
                "zone_id": "other-demand",
                "direction": "LONG",
                "low": 4100.0,
                "high": 4110.0,
            },
        },
    }
    out = build_liquidity_sweep_admission_guard(
        atlas_evaluation=atlas,
        plan=long_plan,
        live_price=4189.0,
    )
    assert out["source_aligned"] is False
    assert out["hard_execution_block"] is False
    assert out["state"] == "NOT_ALIGNED_TO_CURRENT_EXECUTION_SOURCE"


def test_v331_is_wired_into_execution_and_decision_center():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    execution = (
        root / "src/fx_scanner/demo_xau_v229_depth_execution.py"
    ).read_text(encoding="utf-8")
    center = (
        root / "src/fx_scanner/demo_xau_decision_center_v296.py"
    ).read_text(encoding="utf-8")

    assert "build_liquidity_sweep_admission_guard" in execution
    assert "WAIT_LIQUIDITY_SWEEP_CONFIRMATION" in execution
    assert '"liquidity_sweep_guard": liquidity_sweep_guard' in execution
    assert '"name": "V331_LIQUIDITY_SWEEP"' in center
