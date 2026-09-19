from pathlib import Path

from fx_scanner.research_xau_asymmetric_regime_family_v44 import (
    EXECUTION_INFLUENCE,
    FROZEN_SHORT_VARIANT_ID,
    LONG_COST_R_CAP,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    SHORT_COST_R_CAP,
    _short_variant,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v44_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v44_uses_frozen_existing_short_family():
    variant = _short_variant()
    assert variant.variant_id == FROZEN_SHORT_VARIANT_ID
    assert variant.direction == "SHORT"
    assert variant.session == "US"
    assert FROZEN_SHORT_VARIANT_ID == "XAU_V2_US_SHORT_L10_ADX15_R15"


def test_v44_router_is_bounded():
    assert LONG_COST_R_CAP == 0.10
    assert SHORT_COST_R_CAP == 0.10
    assert len(ROUTES) == 6
    assert "ASYM_LONG_PLUS_SHORT_COST10" in ROUTES
    assert "ASYM_LONG_PLUS_STRONG_SHORT_COST10" in ROUTES


def test_v44_does_not_modify_entry_families_or_execution_authority():
    src = (ROOT / "src/fx_scanner/research_xau_asymmetric_regime_family_v44.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_asymmetric_regime_family_v44_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"short_family_retuned": False' in src
    assert '"entry_families_modified": False' in src
    assert '"dense_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
