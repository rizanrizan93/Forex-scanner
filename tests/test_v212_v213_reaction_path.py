from pathlib import Path

from fx_scanner.demo_xau_v212_zone_reaction_probability import (
    _features,
    evaluate_zone_probabilities,
)
from fx_scanner.demo_xau_v213_post_zone_path import (
    _stage,
    evaluate_post_zone_path,
)

ROOT = Path(__file__).resolve().parents[1]


def _zone() -> dict:
    return {
        "zone_id": "z1",
        "timeframe": "H1",
        "zone_class": "IMBALANCE",
        "pattern": "RBD",
        "direction": "SHORT",
        "low": 4284.0,
        "high": 4290.0,
        "status": "IN_ZONE_PREPARE_ONLY",
        "age_bucket": "H1_0_24H",
        "session_context": "OTHER_WIB",
        "htf_nesting_count": 2,
        "research_score": 72.0,
        "lifecycle": {"touch_count": 1, "freshness": "FIRST_TEST"},
        "liquidity": {"confluence_count": 3},
        "approach": {"state": "AGGRESSIVE_APPROACH"},
    }


def _research() -> dict:
    cohort = {
        "dimensions": {
            "timeframe": "H1",
            "direction": "SHORT",
            "nesting_bucket": "MULTI_HTF_NESTING",
            "approach_state": "AGGRESSIVE_APPROACH",
        },
        "n": 40,
        "holds": 30,
        "breaks": 6,
        "stalls": 4,
        "precision_hold": 0.75,
        "wilson_lower_95": 0.60,
        "hit_025": 0.85,
        "hit_050": 0.75,
        "hit_075": 0.60,
        "hit_100": 0.45,
        "median_mfe_atr": 0.95,
        "median_mae_atr": 0.60,
        "p75_mae_atr": 0.90,
        "median_bars_to_outcome": 3,
    }
    return {
        "destination_overall": {
            "zones": 100,
            "resolved_zones": 100,
            "touch_rate": 0.90,
        },
        "destination_by_zone_type": [
            {
                "dimensions": {
                    "timeframe": "H1",
                    "zone_class": "IMBALANCE",
                    "pattern": "RBD",
                    "direction": "SHORT",
                },
                "zones": 50,
                "resolved_zones": 50,
                "touch_rate": 0.96,
            }
        ],
        "holdout_overall": {
            "n": 200,
            "holds": 110,
            "breaks": 55,
            "stalls": 35,
            "precision_hold": 0.55,
            "hit_025": 0.70,
            "hit_050": 0.55,
            "hit_075": 0.42,
            "hit_100": 0.32,
            "median_mfe_atr": 0.60,
            "median_mae_atr": 0.70,
            "p75_mae_atr": 1.10,
            "median_bars_to_outcome": 4,
        },
        "holdout_groups": {
            "timeframe|direction|nesting_bucket|approach_state": [cohort]
        },
    }


def test_v212_features_and_shrunk_probability_are_shadow_only_inputs() -> None:
    zone = _zone()
    features = _features(zone)
    assert features["nesting_bucket"] == "MULTI_HTF_NESTING"
    assert features["liquidity_bucket"] == "MULTI_LIQUIDITY_CONFLUENCE"
    assert features["touch_bucket"] == "FIRST_TEST"

    rows = evaluate_zone_probabilities([zone], _research())
    result = rows[0]
    assert result["destination"]["p_touch"] == 0.96
    reaction = result["reaction"]
    assert 0.55 < reaction["p_hold_050"] < 0.75
    assert 0 < reaction["p_break"] < 1
    assert reaction["p_075_given_050"] is not None
    assert reaction["not_calibrated_probability_claim"] is True


def test_v213_stage_contract() -> None:
    assert _stage({
        "pocket_state": "CANDIDATE_M5_POCKET",
        "micro_refinement": {"state": "M5_TOUCH_WAIT_RECLAIM"},
    }) == "TOUCHED_WAIT_RECLAIM"
    assert _stage({
        "pocket_state": "CANDIDATE_M5_POCKET",
        "micro_refinement": {"state": "M5_RECLAIM_WAIT_MSS"},
    }) == "RECLAIMED_WAIT_MSS"
    assert _stage({
        "pocket_state": "CANDIDATE_M5_POCKET",
        "micro_refinement": {"state": "M5_MSS_WAIT_DISPLACEMENT"},
    }) == "MSS_WAIT_DISPLACEMENT"
    assert _stage({
        "pocket_state": "REFINED_M5_POCKET",
        "micro_refinement": {"state": "REFINED_M5_POCKET"},
    }) == "REFINED_REACTION_ACTIVE"


def test_v213_maps_targets_and_conditional_continuation_without_authority() -> None:
    projection = {
        "current_leg": {
            "direction": "SHORT",
            "pocket_state": "CANDIDATE_M5_POCKET",
            "m5_pocket": {"low": 4284.0, "high": 4290.0},
            "source_zone": {"zone_id": "z1"},
            "micro_refinement": {"state": "M5_TOUCH_WAIT_RECLAIM"},
            "reaction_target": {"price": 4280.0},
            "terminal_target_zone": {"low": 4264.0, "high": 4275.0},
            "target_ladder": [{"role": "CHECKPOINT", "price": 4280.0}],
        },
        "next_leg": {},
    }
    probability_details = {
        "zone_probabilities": evaluate_zone_probabilities([_zone()], _research())
    }
    evidence = {
        "all_evidence": {
            "enrolled": 10,
            "touched": 8,
            "reaction_precision_given_touch": 0.5,
        }
    }
    result = evaluate_post_zone_path(projection, probability_details, evidence)
    current = result["current_leg"]
    assert current["stage"] == "TOUCHED_WAIT_RECLAIM"
    assert current["reaction_target"]["price"] == 4280.0
    assert current["after_0_50_atr"]["p_extend_to_0_75"] is not None
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False


def test_v212_v213_run_in_maintenance_after_v201() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    v201 = "python -m fx_scanner.demo_xau_v201_reaction_ladder"
    v212 = "python -m fx_scanner.demo_xau_v212_zone_reaction_probability"
    v213 = "python -m fx_scanner.demo_xau_v213_post_zone_path"
    assert workflow.index(v201) < workflow.index(v212) < workflow.index(v213)


def test_v212_v213_dashboard_panel_is_observation_only() -> None:
    text = (ROOT / "streamlit_app.py").read_text()
    assert "V212/V213 — Probabilitas Reaksi & Jalur Setelah Zone" in text
    assert "P reaksi ≥0.50 ATR" in text
    assert "P break zone" in text
    assert "P lanjut 1.00 ATR | sudah 0.50" in text
    assert "bukan izin eksekusi" in text
