from pathlib import Path

from fx_scanner.research_xau_v47_causal_context_ensemble_v73 import (
    COLD_START_POLICY,
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FEATURE_NAMES,
    MIN_COMPLETED_TRAINING_TRADES,
    MODEL_LOOKBACK_TRADING_DAYS,
    POLICY_EFFECT,
    PREDICTION_THRESHOLD_R,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    RIDGE_LAMBDA,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v73_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v73_has_single_frozen_online_model():
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")
    assert MODEL_LOOKBACK_TRADING_DAYS == 252
    assert MIN_COMPLETED_TRAINING_TRADES == 60
    assert RIDGE_LAMBDA == 10.0
    assert PREDICTION_THRESHOLD_R == 0.0
    assert COLD_START_POLICY == "PASS_THROUGH"
    assert len(FEATURE_NAMES) > 20


def test_v73_keeps_suppressed_trades_in_training_and_cannot_execute():
    src=(ROOT / "src/fx_scanner/research_xau_v47_causal_context_ensemble_v73.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_causal_context_ensemble_v73_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert '"training_uses_only_completed_prior_trades": True' in src
    assert '"training_population": "all original V47-approved trades, including trades the overlay itself would suppress"' in src
    assert '"hyperparameter_grid_search": False' in src
    assert '"feature_selection_from_v73_outcomes": False' in src
    assert '"secondary_features_change_v69_forward_contract": False' in src
