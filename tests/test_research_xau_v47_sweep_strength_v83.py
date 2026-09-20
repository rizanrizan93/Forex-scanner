from pathlib import Path

from fx_scanner.research_xau_v47_sweep_strength_v83 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    RAW_FEATURES,
    REQUIRED_COSTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v83_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v83_uses_only_v82_raw_fields_without_thresholds():
    assert RAW_FEATURES == (
        "age_m15_bars",
        "penetration_atr",
        "reclaim_atr",
        "body_atr",
        "close_location",
    )
    src=(ROOT / "src/fx_scanner/research_xau_v47_sweep_strength_v83.py").read_text()
    assert '"feature_thresholds_added": False' in src
    assert '"feature_buckets_added": False' in src
    assert '"score_added": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"v69_forward_contract_changed": False' in src
    assert '"v82_forward_telemetry_changed": False' in src


def test_v83_has_no_execution_path():
    src=(ROOT / "src/fx_scanner/research_xau_v47_sweep_strength_v83.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_sweep_strength_v83_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined
    assert '"execution_authority": False' in src
