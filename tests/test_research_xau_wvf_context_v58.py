from pathlib import Path

from fx_scanner.research_xau_wvf_context_v58 import (
    BASE_ROUTE,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    WVF_LOOKBACK_H1,
    WVF_PERCENTILE,
    WVF_PERCENTILE_WINDOW,
    WVF_STATES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v58_is_context_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v58_reuses_v49_wvf_definition():
    assert BASE_ROUTE == "LONG_REACCEL_COST10"
    assert WVF_LOOKBACK_H1 == 22
    assert WVF_PERCENTILE_WINDOW == 50
    assert WVF_PERCENTILE == 0.85
    assert WVF_STATES == ("EXTREME", "NON_EXTREME", "UNAVAILABLE")


def test_v58_does_not_filter_size_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_wvf_context_v58.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_wvf_context_v58_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"wvf_parameters_identical_to_v49": True' in src
    assert '"trade_filter_applied": False' in src
    assert '"position_sizing_changed": False' in src
    assert '"threshold_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src
