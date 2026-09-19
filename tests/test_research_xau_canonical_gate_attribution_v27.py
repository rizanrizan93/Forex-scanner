from pathlib import Path

from fx_scanner.research_xau_canonical_gate_attribution_v27 import (
    DIAGNOSTIC_ONLY,
    MODES,
    MODE_EXACT_FULL,
    MODE_EXACT_MODEL,
    MODE_NO_SWEEP_RETRACE,
    MODE_ORDERED_NO_RETRACE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v27_has_exact_and_one_gate_counterfactuals():
    assert set(MODES) == {
        MODE_EXACT_MODEL,
        MODE_EXACT_FULL,
        MODE_ORDERED_NO_RETRACE,
        MODE_NO_SWEEP_RETRACE,
    }
    assert DIAGNOSTIC_ONLY is True


def test_v27_does_not_lower_canonical_score_threshold():
    source = (
        ROOT / "src/fx_scanner/research_xau_canonical_gate_attribution_v27.py"
    ).read_text()
    assert "score < 75.0" in source
    assert "evaluate_xau_m15_ema_smc_reclaim_execution" in source
    assert '"promotion_eligible": False' in source


def test_v27_is_demo_shadow_only():
    runtime = (
        ROOT / "src/fx_scanner/research_xau_canonical_gate_attribution_v27_runtime.py"
    ).read_text()
    workflow = (
        ROOT / ".github/workflows/ctrader-xau-canonical-gate-attribution-v27.yml"
    ).read_text()
    assert "V27_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
