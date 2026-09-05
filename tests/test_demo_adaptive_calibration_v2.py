from fx_scanner.demo_adaptive_calibration_v2 import (
    build_adaptive_calibration_v2_report,
    calibration_v2_stage,
)


def _row(*, symbol="BTCUSD", setup="CONTINUATION", direction="LONG", regime="TREND", entry_mode="HL_PULLBACK", confirmation="BOS", exit_type="SL_HIT", pullback_atr=0.15, drift=None, mae=None, mfe=None):
    payload = {
        "symbol": symbol,
        "setup_type": setup,
        "direction": direction,
        "regime": regime,
        "entry_mode": entry_mode,
        "confirmation": confirmation,
        "exit_type": exit_type,
        "entry_low": 100.0,
        "entry_high": 100.0,
        "planned_sl": 99.0,
        "exit_price": 99.0 if exit_type == "SL_HIT" else 102.0,
        "net_pnl_estimate": -1.0 if exit_type == "SL_HIT" else 2.0,
        "pullback_atr": pullback_atr,
    }
    if drift is not None:
        payload["live_entry_drift_r"] = drift
    if mae is not None:
        payload["mae_r"] = mae
    if mfe is not None:
        payload["mfe_r"] = mfe
    return {"payload": payload}


def test_v2_stage_contract_is_progressive_and_sltp_not_automatic():
    assert calibration_v2_stage(0) == "OBSERVE"
    assert calibration_v2_stage(10) == "GATE_ADAPT"
    assert calibration_v2_stage(20) == "PATTERN_ADAPT"
    assert calibration_v2_stage(50) == "SLTP_SHADOW"
    assert calibration_v2_stage(100) == "BOUNDED_SLTP_READY"

    report = build_adaptive_calibration_v2_report([_row(exit_type="TP_HIT") for _ in range(100)])
    assert report.stage == "BOUNDED_SLTP_READY"
    assert report.automatic_gate_mutation_allowed is True
    assert report.automatic_pattern_mutation_allowed is True
    assert report.automatic_sltp_mutation_allowed is False


def test_v2_keeps_symbol_regime_direction_cohorts_separate():
    rows = [
        _row(symbol="SOLUSD", regime="RANGE", direction="LONG") for _ in range(6)
    ] + [
        _row(symbol="BTCUSD", regime="TREND", direction="LONG", exit_type="TP_HIT") for _ in range(6)
    ]
    report = build_adaptive_calibration_v2_report(rows)
    assert len(report.cohorts) == 2
    assert any(key.startswith("SOLUSD|CONTINUATION|LONG|RANGE") for key in report.cohorts)
    assert any(key.startswith("BTCUSD|CONTINUATION|LONG|TREND") for key in report.cohorts)
    assert any(item.code == "COHORT_PERSISTENT_WEAKNESS" and item.scope.startswith("SOLUSD|") for item in report.diagnostics)


def test_v2_flags_early_entry_and_chase_only_with_repeated_evidence():
    rows = [
        _row(pullback_atr=0.10, drift=0.40, exit_type="SL_HIT") for _ in range(6)
    ]
    report = build_adaptive_calibration_v2_report(rows)
    codes = {item.code for item in report.diagnostics}
    assert "ENTRY_TOO_EARLY_PROBABLE" in codes
    assert "CHASE_ENTRY_PROBABLE" in codes


def test_v2_stop_too_tight_is_shadow_diagnosis_only():
    rows = [
        _row(mae=-1.0, mfe=1.5, exit_type="SL_HIT") for _ in range(6)
    ]
    report = build_adaptive_calibration_v2_report(rows)
    finding = next(item for item in report.diagnostics if item.code == "STOP_TOO_TIGHT_PROBABLE")
    assert finding.severity == "SHADOW_ONLY"
    assert report.automatic_sltp_mutation_allowed is False


def test_v2_snapshot_coverage_measures_missing_regime_context():
    complete = _row(exit_type="TP_HIT")
    missing = _row(exit_type="SL_HIT")
    missing["payload"].pop("regime")
    report = build_adaptive_calibration_v2_report([complete, missing])
    assert report.snapshot_coverage == 0.5
