from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ATLAS = (
    ROOT / "src" / "fx_scanner" / "demo_xau_supply_demand_atlas_v182.py"
).read_text(encoding="utf-8")


def test_v305_v304_alignment_uses_reference_time_reconstruction() -> None:
    assert "select_reference(as_of=now, symbol=SYMBOL)" in ATLAS
    assert "RECONSTRUCTED_AT_REFERENCE_AVAILABLE_FROM" in ATLAS
    assert 'strategic_bias="NEUTRAL"' in ATLAS
    assert "NEUTRAL_NO_FUTURE_REGIME_LEAK" in ATLAS
    assert "reference_available" in ATLAS
    assert "baseline_projection = evaluate_bidirectional_m5_path" in ATLAS
    assert 'v304_result["baseline"] = v304_baseline' in ATLAS
