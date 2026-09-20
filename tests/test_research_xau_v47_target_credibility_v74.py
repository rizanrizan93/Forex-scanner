from pathlib import Path

from fx_scanner.research_xau_v47_target_credibility_v74 import (
    D1_RANGE_LOOKBACK,
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    FROZEN_ROUTE,
    H1_ATR_PERIOD,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    STOP_ATR_BUCKETS,
    TARGET_RANGE_BUCKETS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v74_is_geometry_only_shadow():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v74_uses_predeclared_noise_and_target_geometry():
    assert H1_ATR_PERIOD == 14
    assert D1_RANGE_LOOKBACK == 60
    assert STOP_ATR_BUCKETS == (
        "LE_0_50",
        "GT_0_50_LE_1_00",
        "GT_1_00_LE_1_50",
        "GT_1_50",
        "UNAVAILABLE",
    )
    assert TARGET_RANGE_BUCKETS == (
        "LE_0_25",
        "GT_0_25_LE_0_50",
        "GT_0_50_LE_0_75",
        "GT_0_75",
        "UNAVAILABLE",
    )


def test_v74_does_not_modify_trade_geometry_or_execute():
    src=(ROOT / "src/fx_scanner/research_xau_v47_target_credibility_v74.py").read_text()
    runtime=(ROOT / "src/fx_scanner/research_xau_v47_target_credibility_v74_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert '"entry_changed": False' in src
    assert '"stop_changed": False' in src
    assert '"target_changed": False' in src
    assert '"trade_filter_applied": False' in src
    assert '"bucket_selected_as_winner": False' in src
    assert '"threshold_grid_search": False' in src
