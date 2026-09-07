from pathlib import Path


def test_demo_fast_handoff_does_not_enable_same_symbol_stacking():
    source = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")

    assert "install_demo_position_policy" not in source
    assert "demo_position_reversal" not in source
