from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
CANONICAL = (
    ROOT / "src" / "fx_scanner" / "xau_canonical_decision_v240.py"
).read_text(encoding="utf-8")
ATLAS = (
    ROOT / "src" / "fx_scanner" / "demo_xau_supply_demand_atlas_v182.py"
).read_text(encoding="utf-8")


def test_v307_dashboard_uses_primary_reversal_labels() -> None:
    assert "Demand reversal utama" in DASHBOARD
    assert "Supply reversal utama" in DASHBOARD
    assert "PRIMARY REVERSAL DEMAND" in DASHBOARD
    assert "PRIMARY REVERSAL SUPPLY" in DASHBOARD


def test_v307_dashboard_reads_canonical_primary_reversal_fields() -> None:
    assert 'v240_decision.get("primary_reversal_demand")' in DASHBOARD
    assert 'v240_decision.get("primary_reversal_supply")' in DASHBOARD


def test_v307_canonical_exposes_single_reversal_authority() -> None:
    assert '"primary_reversal_demand": primary_reversal_demand or nearest_demand' in CANONICAL
    assert '"primary_reversal_supply": primary_reversal_supply or nearest_supply' in CANONICAL
    assert '"display_policy": "PRIMARY_REVERSAL_ZONE_ONLY"' in CANONICAL


def test_v307_atlas_preserves_raw_nearest_only_as_diagnostic() -> None:
    assert '"raw_nearest_demand"' in ATLAS
    assert '"raw_nearest_supply"' in ATLAS
    assert '"reversal_zone_policy": "PRIMARY_REVERSAL_ZONE_ONLY"' in ATLAS
    assert "DEEPLY_MITIGATED" in ATLAS
