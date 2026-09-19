from pathlib import Path

from fx_scanner.research_xau_canonical_ict_context_v65 import (
    CONTEXT_WINDOW_M15,
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FAMILY_IDS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v65_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v65_reuses_canonical_ict_context():
    assert CONTEXT_WINDOW_M15 == 700
    assert set(FAMILY_IDS) == {"L12", "L20"}


def test_v65_does_not_filter_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_canonical_ict_context_v65.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_canonical_ict_context_v65_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"canonical_ict_layer_reused_without_parameter_changes": True' in src
    assert '"trade_filter_applied": False' in src
    assert '"ict_feature_selected_as_winner": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
