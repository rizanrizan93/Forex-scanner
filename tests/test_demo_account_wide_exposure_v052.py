from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_autotrade_after_exposure_is_account_wide_not_snapshot_count():
    source = (ROOT / "src/fx_scanner/demo_calibration_autotrade.py").read_text()

    assert "snapshot_positions_after = len(pnl_snapshot.positions)" in source
    assert "open_positions_after = int(gateway.position_count())" in source
    assert "broker_snapshot_positions" in source
    assert 'broker_position_source": "CTRADER_RECONCILE_ACCOUNT_WIDE"' in source
    assert "free_slots_after = max(0, max_positions - open_positions_after)" in source


def test_demo_autotrade_safety_contract_is_unchanged():
    source = (ROOT / "src/fx_scanner/demo_calibration_autotrade.py").read_text()

    assert "max_concurrent_positions" in source
    assert "CTRADER_DEMO_ADAPTIVE_CALIBRATION_ENABLED" in source
    assert "apply_demo_calibration_threshold" in source
    assert "apply_demo_calibration_risk" in source
    assert "ExecutionMode.AUTO" in source
