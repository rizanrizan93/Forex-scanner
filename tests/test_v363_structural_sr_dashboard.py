from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (
    ROOT / "src" / "fx_scanner" / "xau_dual_engine_dashboard_v344.py"
).read_text(encoding="utf-8")
ENGINE = (
    ROOT / "src" / "fx_scanner" / "xau_sd_liquidity_engine_v342.py"
).read_text(encoding="utf-8")


def test_v363_dashboard_surfaces_structural_sr_lifecycle():
    assert "RIZAN STRUCTURAL S/R MAP" in DASHBOARD
    assert "Nearest support" in DASHBOARD
    assert "Nearest resistance" in DASHBOARD
    assert "S/R flip watch" in DASHBOARD
    assert "RECLAIM REQUIRED" in DASHBOARD
    assert "support ≠ auto BUY" in DASHBOARD
    assert "resistance ≠ auto SELL" in DASHBOARD


def test_v363_is_integrated_into_v342_without_becoming_third_execution_engine():
    assert "build_structural_sr_map" in ENGINE
    assert '"support_resistance_map": support_resistance_map' in ENGINE
    assert "CONTEXT_ONLY_NO_DIRECTION_SIGNAL" in ENGINE
